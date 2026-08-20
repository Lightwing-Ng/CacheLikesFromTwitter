"""Flask application for the local web console."""

# Code version: v1.44.0-codex.1

from __future__ import annotations

import atexit
import os
import secrets
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, replace
from html import escape as escape_html
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

from flask import Flask, Response, abort, jsonify, make_response, redirect, render_template, request, send_file, session, url_for
from markdown_it import MarkdownIt
from markupsafe import Markup

from app.core.agent import (
    AGENT_ACCESS_SESSION_KEY,
    AGENT_MODEL_OPTIONS_BY_PLATFORM,
    AGENT_PLATFORM_OPTIONS,
    OPERATING_SYSTEM_OPTIONS as AGENT_OPERATING_SYSTEM_OPTIONS,
    AgentSourceCache,
    ComputerUseAgentService,
    ComputerUseSettingsStore,
    browser_options_for_host,
    is_allowed_agent_network_request,
    is_loopback_address,
    launch_terminal_authorization,
    list_agent_project_sessions,
    list_agent_sources,
    normalize_agent_project_url,
    open_agent_in_browser,
    validate_computer_use_settings,
    validate_agent_access_password,
)
from app.core.browser import browser_descriptors, build_browser_options, probe_browser_session
from app.core.foundation import (
    APP_VERSION,
    DEFAULT_HOST,
    DEFAULT_PORT,
    LOCAL_STORE_ROOT,
    MAX_CHATGPT_SCAN_WAIT_SECONDS,
    MAX_CHATGPT_STARTUP_TIMEOUT_SECONDS,
    MAX_MAX_MEDIA_FILE_SIZE_MIB,
    MIN_CHATGPT_SCAN_WAIT_SECONDS,
    MIN_CHATGPT_STARTUP_TIMEOUT_SECONDS,
    MIN_MAX_MEDIA_FILE_SIZE_MIB,
    CrawlConfig,
    TaskState,
    build_initial_snapshot,
    configure_logging,
    get_log_file_path,
    load_saved_config,
    save_config,
    utc_now,
)
from app.core.providers import (
    CacheLikesService,
    ChatGPTDownloadService,
    GeminiHistoryService,
    GrokDownloadService,
    GrokHistoryService,
    build_chatgpt_initial_snapshot,
    build_gemini_initial_snapshot,
    build_grok_history_snapshot,
    build_grok_initial_snapshot,
    chatgpt_conversation_id,
    fetch_chatgpt_conversation_history,
    is_chatgpt_conversation_url,
    list_chatgpt_agent_sources,
    list_chatgpt_project_sessions,
    normalize_chatgpt_conversation_url,
    probe_and_collect_chatgpt_sources,
    reset_chatgpt_state,
    reset_grok_state,
)
from app.core.storage import (
    LocalMediaCatalog,
    ShadowBackupError,
    ShadowBackupService,
    attach_media_references,
    build_chat_history_markdown,
    choose_settings_directory,
    choose_shadow_backup_destination,
    format_captured_at_timestamp_label,
    format_chat_message_timestamp_label,
    local_file_manager_label,
    media_route_relative_path,
    normalize_browser_filters,
    PromptStore,
    prompt_pointer_key,
    query_chat_history,
    reveal_media_path,
    resolve_browser_media_path,
)
from app.web.cache_sources import (
    LLM_CACHE_SOURCE_VIEWS,
    LLM_SWITCHER_SOURCE_VIEWS,
    MEDIA_CACHE_SOURCE_VIEWS,
    cache_source_views_for_page,
    get_cache_source_label,
    get_cache_source_view,
)
from app.web.navigation import build_agent_path, is_supported_agent_selection


CACHE_RECONCILE_PHASES = {"idle", "finished", "completed", "success", "stopped"}
PROMPT_MARKDOWN_RENDERER = MarkdownIt(
    "default",
    {"html": False, "linkify": False, "typographer": False},
)

_STORED_HTML_ALLOWED_TAGS = frozenset(
    {
        "a",
        "b",
        "blockquote",
        "br",
        "code",
        "del",
        "em",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "hr",
        "i",
        "li",
        "mark",
        "ol",
        "p",
        "pre",
        "s",
        "span",
        "strong",
        "sub",
        "sup",
        "table",
        "tbody",
        "td",
        "tfoot",
        "th",
        "thead",
        "tr",
        "u",
        "ul",
    }
)
_STORED_HTML_VOID_TAGS = frozenset({"br", "hr"})
_STORED_HTML_SKIPPED_TAGS = frozenset({"iframe", "object", "script", "style", "svg"})
_STORED_HTML_SKIPPED_CLASSES = frozenset({"screen-reader-user-query-label"})


def _safe_stored_html_url(value: str) -> str:
    """Keep only absolute HTTP(S) URLs from cached rich-text attributes."""
    candidate = str(value or "").strip()
    try:
        parsed = urlsplit(candidate)
    except ValueError:
        return ""
    return candidate if parsed.scheme in {"http", "https"} and parsed.netloc else ""


class _StoredHtmlSanitizer(HTMLParser):
    """Keep harmless rich-text structure while dropping cached page chrome."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.open_tags: list[str] = []
        self.skipped_tags: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if self.skipped_tags:
            if tag not in _STORED_HTML_VOID_TAGS:
                self.skipped_tags.append(tag)
            return
        attrs_map = dict(attrs)
        class_names = set(str(attrs_map.get("class") or "").split())
        if tag in _STORED_HTML_SKIPPED_TAGS or class_names & _STORED_HTML_SKIPPED_CLASSES:
            if tag not in _STORED_HTML_VOID_TAGS:
                self.skipped_tags.append(tag)
            return
        if tag not in _STORED_HTML_ALLOWED_TAGS:
            return

        safe_attrs: list[tuple[str, str]] = []
        if tag == "a":
            href = _safe_stored_html_url(attrs_map.get("href", ""))
            if href:
                safe_attrs.append(("href", href))
            title = str(attrs_map.get("title") or "").strip()
            if title:
                safe_attrs.append(("title", title))
        elif tag == "ol":
            start = str(attrs_map.get("start") or "").strip()
            if start.isdigit():
                safe_attrs.append(("start", start))
        elif tag in {"td", "th"}:
            for name in ("colspan", "rowspan"):
                value = str(attrs_map.get(name) or "").strip()
                if value.isdigit():
                    safe_attrs.append((name, value))
        elif tag == "span":
            math_value = str(attrs_map.get("data-math") or "").strip()
            if math_value:
                safe_attrs.append(("data-math", math_value))

        serialized_attrs = "".join(
            f' {name}="{escape_html(value, quote=True)}"' for name, value in safe_attrs
        )
        self.parts.append(f"<{tag}{serialized_attrs}>")
        if tag not in _STORED_HTML_VOID_TAGS:
            self.open_tags.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() not in _STORED_HTML_VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self.skipped_tags:
            if tag == self.skipped_tags[-1]:
                self.skipped_tags.pop()
            return
        if tag not in self.open_tags:
            return
        while self.open_tags:
            open_tag = self.open_tags.pop()
            self.parts.append(f"</{open_tag}>")
            if open_tag == tag:
                break

    def handle_data(self, data: str) -> None:
        if not self.skipped_tags:
            self.parts.append(escape_html(data))

    def handle_comment(self, _data: str) -> None:
        return

    def render(self) -> str:
        while self.open_tags:
            self.parts.append(f"</{self.open_tags.pop()}>")
        return "".join(self.parts).strip()


def sanitize_stored_html(value: str) -> str:
    """Sanitize cached rich text before marking it safe for a Jinja template."""
    source = str(value or "").replace("\x00", "").strip()
    if not source:
        return ""
    parser = _StoredHtmlSanitizer()
    parser.feed(source)
    parser.close()
    return parser.render()


def render_prompt_markdown(value: str) -> Markup:
    """Render stored ChatGPT prompt Markdown while escaping embedded HTML."""
    prompt = str(value or "").replace("\x00", "").strip()
    return Markup(PROMPT_MARKDOWN_RENDERER.render(prompt)) if prompt else Markup("")


def render_cached_message(content_text: str, content_html: str = "") -> Markup:
    """Render one cached message from sanitized rich text or Markdown fallback."""
    rich_text = sanitize_stored_html(content_html)
    return Markup(rich_text) if rich_text else render_prompt_markdown(content_text)


def build_browser_search_suggestions(
    *,
    view: str,
    media_items: Iterable[Any] = (),
    text_page: Any = None,
    prompt_page: Any = None,
) -> tuple[dict[str, str], ...]:
    """Build bounded, local-only search recommendations for the browser heading."""
    normalized_view = str(view or "").strip().lower()
    is_text_view = normalized_view == "text"
    is_prompt_view = normalized_view == "prompts"
    source_views = (
        LLM_SWITCHER_SOURCE_VIEWS
        if is_text_view or is_prompt_view
        else MEDIA_CACHE_SOURCE_VIEWS
    )
    suggestions: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(value: Any, detail: str) -> None:
        normalized = " ".join(str(value or "").split()).strip()[:120]
        if not normalized:
            return
        key = normalized.casefold()
        if key in seen:
            return
        seen.add(key)
        suggestions.append({"value": normalized, "detail": detail})

    for source in source_views:
        add(
            source.label,
            "Prompt source" if is_prompt_view else ("Chat source" if is_text_view else "Media source"),
        )

    if is_text_view and text_page is not None:
        sessions = [
            getattr(text_page, attribute, None)
            for attribute in ("current_session", "previous_session", "next_session")
        ]
        sessions.extend(getattr(text_page, "sessions", ()) or ())
        for session in sessions:
            if session is None:
                continue
            add(
                getattr(session, "conversation_title", ""),
                f"{get_cache_source_label(getattr(session, 'source', ''))} session",
            )
        for message in getattr(text_page, "items", ()) or ():
            add(
                getattr(message, "conversation_title", ""),
                f"{get_cache_source_label(getattr(message, 'source', ''))} session",
            )
    elif is_prompt_view and prompt_page is not None:
        for prompt in getattr(prompt_page, "items", ()) or ():
            source_label = get_cache_source_label(getattr(prompt, "source", ""))
            add(getattr(prompt, "conversation_title", ""), f"{source_label} session")
            add(getattr(prompt, "content_text", ""), f"{source_label} prompt")
    else:
        for item in media_items:
            source_label = get_cache_source_label(getattr(item, "source", ""))
            media_kind = str(getattr(item, "media_kind", "") or "media").title()
            detail = f"{source_label} · {media_kind}"
            add(getattr(item, "title", ""), detail)
            add(getattr(item, "filename", ""), detail)
            add(getattr(item, "creator", ""), f"{source_label} creator")

    return tuple(suggestions[:96])


@dataclass(frozen=True, slots=True)
class CacheRuntimeAdapter:
    """Connect one registered cache page to its task runtime."""

    state: TaskState
    service: Any
    hydrate_snapshot: Callable[[], Any]


def reconcile_cached_snapshot(snapshot: dict[str, Any], hydrated_payload: dict[str, Any]) -> dict[str, Any]:
    """Refresh persisted cache counters only for stable non-error task states."""
    if snapshot.get("running") or snapshot.get("phase") not in CACHE_RECONCILE_PHASES:
        return snapshot

    is_idle = snapshot.get("phase") == "idle"
    snapshot["account_name"] = hydrated_payload["account_name"]
    snapshot["output_dir"] = hydrated_payload["output_dir"]
    snapshot["downloaded_posts"] = hydrated_payload["downloaded_posts"]
    snapshot["downloaded_tweets"] = hydrated_payload["downloaded_tweets"]
    if "discovered_images" in hydrated_payload and (
        is_idle or "discovered_images" not in snapshot
    ):
        snapshot["discovered_images"] = hydrated_payload["discovered_images"]
    snapshot["downloaded_images"] = hydrated_payload["downloaded_images"]
    snapshot["downloaded_videos"] = hydrated_payload["downloaded_videos"]
    if is_idle:
        snapshot["message"] = hydrated_payload["message"]
    return snapshot


def create_app(local_store_root: Path | str | None = None) -> Flask:
    """Build and configure the Flask app."""
    configure_logging(APP_VERSION)
    app = Flask(
        __name__,
        template_folder=str(Path(__file__).resolve().parent / "templates"),
        static_folder=str(Path(__file__).resolve().parent / "static"),
    )
    app.config.update(
        SECRET_KEY=os.environ.get("CACHELIKES_SESSION_SECRET", "").strip()
        or secrets.token_urlsafe(32),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )

    media_catalog = LocalMediaCatalog(local_store_root or LOCAL_STORE_ROOT)
    app.extensions["local_media_catalog"] = media_catalog
    prompt_store = PromptStore(media_catalog.local_store_root)
    app.extensions["prompt_store"] = prompt_store
    agent_source_cache = AgentSourceCache(media_catalog.local_store_root)
    app.extensions["agent_source_cache"] = agent_source_cache
    shadow_backup_service = ShadowBackupService(media_catalog.local_store_root)
    app.extensions["shadow_backup_service"] = shadow_backup_service
    state = TaskState(version=APP_VERSION)
    service = CacheLikesService(state, shadow_backup_service=shadow_backup_service)
    grok_state = TaskState(version=APP_VERSION, snapshot_factory=build_grok_initial_snapshot)
    grok_service = GrokDownloadService(grok_state, shadow_backup_service=shadow_backup_service)
    grok_history_state = TaskState(
        version=APP_VERSION,
        snapshot_factory=lambda version: build_grok_history_snapshot(
            version=version,
            local_store_root=media_catalog.local_store_root,
        ),
    )
    grok_history_service = GrokHistoryService(
        grok_history_state,
        media_catalog.local_store_root,
        shadow_backup_service=shadow_backup_service,
    )
    app.extensions["grok_history_service"] = grok_history_service
    chatgpt_state = TaskState(version=APP_VERSION, snapshot_factory=build_chatgpt_initial_snapshot)
    chatgpt_service = ChatGPTDownloadService(chatgpt_state, shadow_backup_service=shadow_backup_service)
    app.extensions["chatgpt_service"] = chatgpt_service
    gemini_state = TaskState(
        version=APP_VERSION,
        snapshot_factory=lambda version: build_gemini_initial_snapshot(version, media_catalog.local_store_root),
    )
    gemini_service = GeminiHistoryService(
        gemini_state,
        media_catalog.local_store_root,
        shadow_backup_service=shadow_backup_service,
    )
    app.extensions["gemini_service"] = gemini_service
    saved_config = load_saved_config()
    computer_use_settings = ComputerUseSettingsStore()
    computer_use_agent_service = ComputerUseAgentService(computer_use_settings)
    app.extensions["computer_use_settings"] = computer_use_settings
    app.extensions["computer_use_agent_service"] = computer_use_agent_service
    atexit.register(computer_use_agent_service.stop_at_exit)

    def available_agent_browser_keys() -> set[str]:
        """Return Agent browsers supported by the current host."""
        return {str(option["key"]) for option in browser_options_for_host()}

    def agent_settings_for_route(browser: str, platform: str):
        """Render one canonical Agent route without mutating persisted preferences."""
        current = computer_use_settings.settings
        selected_platform = next(
            option for option in AGENT_PLATFORM_OPTIONS if option["key"] == platform
        )
        selected_models = AGENT_MODEL_OPTIONS_BY_PLATFORM[platform]
        selected_model = next(
            (option["key"] for option in selected_models if option["key"] == current.model),
            selected_models[0]["key"],
        )
        target_url = (
            current.target_url
            if current.platform == platform
            else str(selected_platform["home_url"])
        )
        return replace(
            current,
            browser=browser,
            platform=platform,
            model=selected_model,
            target_url=target_url,
        )

    @app.template_global("agent_entry_url")
    def agent_entry_url() -> str:
        """Return the canonical Agent URL for the current route or saved selection."""
        route_args = request.view_args or {}
        browser = str(route_args.get("browser") or computer_use_settings.settings.browser).strip().lower()
        platform = str(route_args.get("platform") or computer_use_settings.settings.platform).strip().lower()
        if not is_supported_agent_selection(browser, platform) or browser not in available_agent_browser_keys():
            browser = computer_use_settings.settings.browser
            if browser not in available_agent_browser_keys():
                browser = "edge"
            platform = computer_use_settings.settings.platform
        return url_for("agent_selected", browser=browser, platform=platform)

    @app.template_global("browser_media_url")
    def browser_media_url(relative_path: str) -> str:
        """Return the stable public URL for one stored media path."""
        return url_for(
            "browser_media",
            relative_path=media_route_relative_path(relative_path),
        )
    cache_runtimes = {
        "x": CacheRuntimeAdapter(
            state=state,
            service=service,
            hydrate_snapshot=lambda: build_initial_snapshot(APP_VERSION),
        ),
        "grok": CacheRuntimeAdapter(
            state=grok_state,
            service=grok_service,
            hydrate_snapshot=lambda: build_grok_initial_snapshot(APP_VERSION),
        ),
        "chatgpt": CacheRuntimeAdapter(
            state=chatgpt_state,
            service=chatgpt_service,
            hydrate_snapshot=lambda: build_chatgpt_initial_snapshot(
                APP_VERSION,
                project_name=saved_config.chatgpt_project_name,
            ),
        ),
        "gemini": CacheRuntimeAdapter(
            state=gemini_state,
            service=gemini_service,
            hydrate_snapshot=lambda: build_gemini_initial_snapshot(
                APP_VERSION,
                media_catalog.local_store_root,
            ),
        ),
    }

    @app.context_processor
    def inject_cache_source_views() -> dict[str, Any]:
        """Expose the ordered cache registry to every dock instance."""
        return {
            "cache_sources": MEDIA_CACHE_SOURCE_VIEWS,
            "llm_cache_sources": LLM_CACHE_SOURCE_VIEWS,
            "chat_history_sources": LLM_SWITCHER_SOURCE_VIEWS,
        }

    def serialize_media_item(item) -> dict[str, Any]:
        """Serialize one browser item without exposing local absolute paths."""
        media_url = (
            url_for("browser_deleted_preview", stable_id=item.stable_id)
            if item.is_deleted
            else url_for(
                "browser_media",
                relative_path=media_route_relative_path(item.relative_path),
            )
        )
        return {
            "id": item.stable_id,
            "source": item.source,
            "source_label": get_cache_source_label(item.source),
            "media_kind": item.media_kind,
            "media_kind_label": item.media_kind.title(),
            "relative_path": item.relative_path,
            "filename": item.filename,
            "title": item.title,
            "description": item.description,
            "prompt_markdown": item.prompt_markdown,
            "creator": item.creator,
            "project_name": item.project_name,
            "source_url": item.source_url,
            "resource_key": item.resource_key,
            "captured_at_label": item.captured_at_label,
            "content_bytes": item.content_bytes,
            "size_label": format_media_size(item.content_bytes),
            "media_url": media_url,
            "preview_url": media_url,
            "alt_text": item.alt_text,
            "width": item.width,
            "height": item.height,
            "is_deleted": item.is_deleted,
        }

    def serialize_prompt_item(item) -> dict[str, Any]:
        """Serialize one resolved prompt without exposing duplicated storage."""
        return {
            "id": item.stable_id,
            "source": item.source,
            "source_label": get_cache_source_label(item.source),
            "conversation_id": item.conversation_id,
            "message_key": item.message_key,
            "conversation_title": item.conversation_title,
            "conversation_url": item.conversation_url,
            "author_label": item.author_label,
            "content_text": item.content_text,
            "captured_at": item.captured_at,
            "added_at": item.added_at,
        }

    def build_reconciled_cache_snapshot(source_key: str) -> dict[str, Any]:
        """Refresh one registered source without discarding live task status."""
        runtime = cache_runtimes.get(source_key)
        if runtime is None:
            raise KeyError(source_key)
        return reconcile_cached_snapshot(runtime.state.snapshot(), asdict(runtime.hydrate_snapshot()))

    def build_reconciled_snapshot() -> dict[str, Any]:
        """Refresh X cache counters from disk without discarding live task status."""
        return build_reconciled_cache_snapshot("x")

    def build_reconciled_grok_snapshot() -> dict[str, Any]:
        """Refresh Grok cache counters from disk without discarding live task status."""
        return build_reconciled_cache_snapshot("grok")

    def build_reconciled_grok_history_snapshot() -> dict[str, Any]:
        """Refresh Grok text-history counters from disk without discarding live task status."""
        return reconcile_cached_snapshot(
            grok_history_state.snapshot(),
            asdict(
                build_grok_history_snapshot(
                    version=APP_VERSION,
                    local_store_root=media_catalog.local_store_root,
                )
            ),
        )

    def build_reconciled_chatgpt_snapshot() -> dict[str, Any]:
        """Refresh ChatGPT image counters from disk without discarding live task status."""
        return build_reconciled_cache_snapshot("chatgpt")

    def parse_int_field(
        field_name: str,
        fallback: int,
        minimum: int = 1,
        maximum: int | None = None,
    ) -> int:
        """Parse one integer form field while tolerating display separators."""
        raw_value = (request.form.get(field_name, str(fallback)) or str(fallback)).replace(",", "").strip()
        parsed = max(minimum, int(raw_value or fallback))
        if maximum is not None:
            parsed = min(maximum, parsed)
        return parsed

    def parse_float_field(
        field_name: str,
        fallback: float,
        minimum: float | None = None,
        maximum: float | None = None,
    ) -> float:
        """Parse one float form field while tolerating display separators."""
        raw_value = (request.form.get(field_name, str(fallback)) or str(fallback)).replace(",", "").strip()
        parsed = float(raw_value or fallback)
        if minimum is not None:
            parsed = max(minimum, parsed)
        if maximum is not None:
            parsed = min(maximum, parsed)
        return parsed

    def parse_checkbox_field(field_name: str, fallback: bool, preserve_missing: bool) -> bool:
        """Parse one checkbox while partial cache forms preserve unrelated settings."""
        raw_value = request.form.get(field_name)
        if raw_value is None:
            return fallback if preserve_missing else False
        return raw_value == "on"

    def parse_form_config(
        base: CrawlConfig | None = None,
        *,
        preserve_missing_booleans: bool = False,
    ) -> CrawlConfig:
        source = base or CrawlConfig()
        return CrawlConfig(
            headless=parse_checkbox_field("headless", source.headless, preserve_missing_booleans),
            download_workers=parse_int_field("download_workers", source.download_workers),
            max_media_file_size_mib=parse_int_field(
                "max_media_file_size_mib",
                source.max_media_file_size_mib,
                minimum=MIN_MAX_MEDIA_FILE_SIZE_MIB,
                maximum=MAX_MAX_MEDIA_FILE_SIZE_MIB,
            ),
            max_media_items=parse_int_field("max_media_items", source.max_media_items),
            max_scroll_rounds=parse_int_field("max_scroll_rounds", source.max_scroll_rounds),
            scroll_pause_seconds=parse_float_field("scroll_pause_seconds", source.scroll_pause_seconds),
            stale_round_limit=parse_int_field("stale_round_limit", source.stale_round_limit),
            x_browser=(request.form.get("x_browser", source.x_browser) or source.x_browser).strip().lower(),
            grok_browser=(request.form.get("grok_browser", source.grok_browser) or source.grok_browser).strip().lower(),
            chatgpt_browser=(request.form.get("chatgpt_browser", source.chatgpt_browser) or source.chatgpt_browser)
            .strip()
            .lower(),
            gemini_browser=(request.form.get("gemini_browser", source.gemini_browser) or source.gemini_browser)
            .strip()
            .lower(),
            gemini_max_conversations=parse_int_field(
                "gemini_max_conversations",
                source.gemini_max_conversations,
            ),
            gemini_scroll_pause_seconds=parse_float_field(
                "gemini_scroll_pause_seconds",
                source.gemini_scroll_pause_seconds,
                minimum=0.1,
            ),
            gemini_stale_round_limit=parse_int_field(
                "gemini_stale_round_limit",
                source.gemini_stale_round_limit,
            ),
            chatgpt_project_url=(
                request.form.get("chatgpt_project_url", source.chatgpt_project_url) or source.chatgpt_project_url
            ).strip()
            or source.chatgpt_project_url,
            chatgpt_project_name=(
                request.form.get("chatgpt_project_name", source.chatgpt_project_name) or source.chatgpt_project_name
            ).strip()
            or source.chatgpt_project_name,
            chatgpt_startup_timeout_seconds=parse_float_field(
                "chatgpt_startup_timeout_seconds",
                source.chatgpt_startup_timeout_seconds,
                minimum=MIN_CHATGPT_STARTUP_TIMEOUT_SECONDS,
                maximum=MAX_CHATGPT_STARTUP_TIMEOUT_SECONDS,
            ),
            chatgpt_scan_wait_seconds=parse_float_field(
                "chatgpt_scan_wait_seconds",
                source.chatgpt_scan_wait_seconds,
                minimum=MIN_CHATGPT_SCAN_WAIT_SECONDS,
                maximum=MAX_CHATGPT_SCAN_WAIT_SECONDS,
            ),
            chrome_user_data_dir=Path(
                request.form.get("chrome_user_data_dir", str(source.chrome_user_data_dir)).strip()
            ).expanduser(),
            chrome_profile_directory=request.form.get(
                "chrome_profile_directory", source.chrome_profile_directory
            ).strip()
            or source.chrome_profile_directory,
            account_name_override=request.form.get("account_name_override", source.account_name_override).strip(),
            shadow_backup_enabled=parse_checkbox_field(
                "shadow_backup_enabled",
                source.shadow_backup_enabled,
                preserve_missing_booleans,
            ),
            shadow_backup_auto_sync=parse_checkbox_field(
                "shadow_backup_auto_sync",
                source.shadow_backup_auto_sync,
                preserve_missing_booleans,
            ),
            shadow_backup_mirror_deletions=parse_checkbox_field(
                "shadow_backup_mirror_deletions",
                source.shadow_backup_mirror_deletions,
                preserve_missing_booleans,
            ),
            shadow_backup_destination=Path(
                (
                    request.form.get("shadow_backup_destination", str(source.shadow_backup_destination))
                    or str(source.shadow_backup_destination)
                ).strip()
            ).expanduser(),
        )

    def render_cache_source_page(source_key: str):
        """Render one source through the shared cache-page contract."""
        cache_source = get_cache_source_view(source_key)
        if cache_source is None or source_key not in cache_runtimes:
            abort(404)
        browser_options = build_browser_options(saved_config)
        selected_browser_id = str(
            getattr(saved_config, cache_source.browser_config_field, "") or ""
        )
        selected_browser_label = next(
            (
                option["label"]
                for option in browser_options
                if option["id"] == selected_browser_id
            ),
            "Safari" if selected_browser_id == "safari" else "background browser",
        )
        return render_template(
            cache_source.template_name,
            cache_source=cache_source,
            cache_source_options=cache_source_views_for_page(source_key),
            snapshot=build_reconciled_cache_snapshot(source_key),
            history_snapshot=(
                build_reconciled_grok_history_snapshot() if source_key == "grok" else None
            ),
            saved_config=saved_config,
            browser_options=browser_options,
            selected_browser_label=selected_browser_label,
            version=APP_VERSION,
            default_host=DEFAULT_HOST,
            default_port=DEFAULT_PORT,
            log_file_path=str(get_log_file_path()),
        )

    def cache_source_url(source_key: str) -> str:
        """Build the canonical page URL for one registered cache source."""
        return url_for("cache_source", source_key=source_key)

    def legacy_cache_source_redirect(source_key: str):
        """Redirect a legacy cache page path while preserving its query string."""
        location = cache_source_url(source_key)
        if request.query_string:
            location = f"{location}?{request.query_string.decode('latin-1')}"
        return redirect(location)

    @app.get("/cache/<source_key>")
    def cache_source(source_key: str):
        if get_cache_source_view(source_key) is None or source_key not in cache_runtimes:
            abort(404)
        return render_cache_source_page(source_key)

    @app.get("/")
    def index():
        return legacy_cache_source_redirect("x")

    @app.get("/grok")
    def grok():
        return legacy_cache_source_redirect("grok")

    @app.get("/chatgpt")
    def chatgpt():
        return legacy_cache_source_redirect("chatgpt")

    @app.get("/gemini")
    def gemini():
        return legacy_cache_source_redirect("gemini")

    @app.get("/settings")
    def settings():
        snapshot = build_reconciled_snapshot()
        grok_snapshot = build_reconciled_grok_snapshot()
        chatgpt_snapshot = build_reconciled_chatgpt_snapshot()
        return render_template(
            "settings.html",
            snapshot=snapshot,
            grok_snapshot=grok_snapshot,
            chatgpt_snapshot=chatgpt_snapshot,
            version=APP_VERSION,
            default_host=DEFAULT_HOST,
            default_port=DEFAULT_PORT,
            saved_config=saved_config,
            log_file_path=str(get_log_file_path()),
            local_store_root=str(media_catalog.local_store_root),
            shadow_backup_snapshot=shadow_backup_service.snapshot(),
            agent_settings=computer_use_settings.settings,
            agent_runtime_snapshot=computer_use_settings.snapshot(),
        )

    def is_agent_access_unlocked() -> bool:
        """Allow the host itself to bypass the LAN gate after validating the request network."""
        return is_loopback_address(request.remote_addr) or bool(
            session.get(AGENT_ACCESS_SESSION_KEY)
        )

    def render_agent_access_unlock(error_message: str = "", status_code: int = 200):
        """Render the no-store Agent password gate."""
        response = make_response(
            render_template(
                "agent_access_unlock.html",
                error_message=error_message,
                version=APP_VERSION,
            ),
            status_code,
        )
        response.headers["Cache-Control"] = "no-store, no-cache, max-age=0, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

    def require_local_agent_request(*, allow_locked: bool = False) -> None:
        """Keep the Agent control plane on loopback or a private network with a password gate."""
        host_name = urlsplit(f"//{request.host}").hostname
        if not is_allowed_agent_network_request(request.remote_addr, host_name):
            abort(403)
        origin = request.headers.get("Origin", "").strip()
        if origin:
            origin_parts = urlsplit(origin)
            expected_parts = urlsplit(request.host_url)
            if (
                origin_parts.scheme,
                origin_parts.hostname,
                origin_parts.port,
            ) != (
                expected_parts.scheme,
                expected_parts.hostname,
                expected_parts.port,
            ):
                abort(403)
        if not allow_locked and not is_agent_access_unlocked():
            abort(401)

    def load_agent_source_catalog(
        *,
        platform: str,
        browser: str,
        source_kind: str,
        project_url: str = "",
        collector: Callable[[], dict[str, Any]],
    ) -> dict[str, Any]:
        """Route every Agent catalog request through the shared cache policy."""
        force_refresh = request.args.get("refresh", "").strip().lower() in {"1", "true", "yes"}
        return agent_source_cache.get_or_collect(
            platform=platform,
            browser=browser,
            source_kind=source_kind,
            project_url=project_url,
            collector=collector,
            force_refresh=force_refresh,
        )

    def build_agent_snapshot() -> dict[str, Any]:
        """Add safe rendered Markdown to the Agent status payload."""
        snapshot = computer_use_agent_service.snapshot()
        snapshot["response_html"] = str(
            render_prompt_markdown(str(snapshot.get("response", "")))
        )
        rendered_history: list[dict[str, Any]] = []
        for raw_item in snapshot.get("history", []):
            if not isinstance(raw_item, dict):
                continue
            item = dict(raw_item)
            item["response_html"] = str(
                render_prompt_markdown(str(item.get("response", "")))
            )
            rendered_history.append(item)
        snapshot["history"] = rendered_history
        return snapshot

    def render_agent_page(browser: str, platform: str):
        """Render one Agent page using the browser/provider encoded by its URL."""
        agent_settings = agent_settings_for_route(browser, platform)
        runtime_snapshot = computer_use_settings.snapshot()
        return render_template(
            "agent.html",
            version=APP_VERSION,
            runtime_snapshot=runtime_snapshot,
            agent_snapshot=build_agent_snapshot(),
            settings=agent_settings,
            agent_project_name=(
                Path(agent_settings.workspace_path).name or agent_settings.workspace_path
            ),
            operating_system_options=AGENT_OPERATING_SYSTEM_OPTIONS,
            browser_options=browser_options_for_host(),
            platform_options=AGENT_PLATFORM_OPTIONS,
            model_options_by_platform=AGENT_MODEL_OPTIONS_BY_PLATFORM,
            render_prompt_markdown=render_prompt_markdown,
        )

    @app.get("/agent")
    def agent():
        """Redirect the legacy Agent entrypoint to the canonical selection URL."""
        require_local_agent_request(allow_locked=True)
        if not is_agent_access_unlocked():
            return render_agent_access_unlock()
        settings = computer_use_settings.settings
        browser = settings.browser if settings.browser in available_agent_browser_keys() else "edge"
        return redirect(build_agent_path(browser, settings.platform))

    @app.get("/agent/<browser>/<platform>")
    def agent_selected(browser: str, platform: str):
        """Render the Agent page for one explicit browser/provider selection."""
        require_local_agent_request(allow_locked=True)
        if (
            not is_supported_agent_selection(browser, platform)
            or browser.strip().lower() not in available_agent_browser_keys()
        ):
            abort(404)
        if not is_agent_access_unlocked():
            return render_agent_access_unlock()
        return render_agent_page(browser.strip().lower(), platform.strip().lower())

    @app.post("/agent/unlock")
    def unlock_agent():
        """Unlock the Agent control plane for the current private-network session."""
        require_local_agent_request(allow_locked=True)
        if not validate_agent_access_password(request.form.get("password")):
            return render_agent_access_unlock("The password is incorrect.", status_code=401)
        session[AGENT_ACCESS_SESSION_KEY] = True
        settings = computer_use_settings.settings
        browser = settings.browser if settings.browser in available_agent_browser_keys() else "edge"
        return redirect(
            url_for(
                "agent_selected",
                browser=browser,
                platform=settings.platform,
            ),
            code=303,
        )

    @app.get("/api/agent/status")
    def agent_status():
        require_local_agent_request()
        return jsonify(
            {
                "runtime": computer_use_settings.snapshot(),
                "agent": build_agent_snapshot(),
            }
        )

    @app.post("/api/agent/preferences")
    def save_agent_preferences():
        require_local_agent_request()
        payload = request.get_json(silent=True) or {}
        try:
            settings = computer_use_settings.update_preferences(
                workspace_path=str(payload.get("workspace_path", "")),
                operating_system=str(payload.get("operating_system", "")),
                browser=str(payload.get("browser", "")),
                platform=str(payload.get("platform", computer_use_settings.settings.platform)),
                model=str(payload.get("model", computer_use_settings.settings.model)),
            )
        except (RuntimeError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 409
        return jsonify(
            {
                "settings": asdict(settings),
                "runtime": computer_use_settings.snapshot(),
                "agent": build_agent_snapshot(),
            }
        )

    @app.post("/api/agent/terminal-authorization")
    def open_agent_terminal_authorization():
        """Open the host-native authorization surface for Terminal or PowerShell."""
        require_local_agent_request()
        payload = request.get_json(silent=True) or {}
        try:
            result = launch_terminal_authorization(
                str(payload.get("operating_system", ""))
            )
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except RuntimeError as exc:
            return jsonify({"error": str(exc)}), 409
        return jsonify(result)

    @app.post("/api/agent/open-conversation")
    def open_agent_conversation():
        """Open the current Agent Web target in the browser selected for the task."""
        require_local_agent_request()
        snapshot = computer_use_agent_service.snapshot()
        try:
            platform = str(snapshot.get("platform", computer_use_settings.settings.platform))
            browser = str(snapshot.get("browser", computer_use_settings.settings.browser))
            target_url = str(snapshot.get("conversation_url", ""))
            result = open_agent_in_browser(
                platform,
                browser,
                target_url,
                background=False,
            )
        except (RuntimeError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 409
        return jsonify(result)

    @app.post("/api/agent/ask")
    def ask_agent():
        require_local_agent_request()
        payload = request.get_json(silent=True) or {}
        try:
            computer_use_agent_service.start(
                str(payload.get("prompt", "")),
                str(payload.get("workspace_path", "")),
                saved_config,
                operating_system=str(payload.get("operating_system", "")),
                platform=str(payload.get("platform", "")),
                browser=str(payload.get("browser", "")),
                model=str(payload.get("model", "")),
                session_mode=str(payload.get("session_mode", "new")),
                conversation_url=str(payload.get("conversation_url", "")),
                project_url=str(payload.get("project_url", "")),
                session_title=str(payload.get("session_title", "")),
                read_only=bool(payload.get("read_only", False)),
            )
        except (RuntimeError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 409
        return jsonify(
            {
                "runtime": computer_use_settings.snapshot(),
                "agent": build_agent_snapshot(),
            }
        ), 202

    @app.get("/api/agent/chatgpt-sources")
    def agent_chatgpt_sources():
        """Load recent ChatGPT sessions and projects for the selected browser."""
        require_local_agent_request()
        browser_name = request.args.get("browser", "").strip().lower()
        try:
            payload = load_agent_source_catalog(
                platform="chatgpt",
                browser=browser_name,
                source_kind="sources",
                collector=lambda: {
                    **list_chatgpt_agent_sources(browser_name, saved_config, silent=True),
                    "platform": "chatgpt",
                },
            )
        except (RuntimeError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 409
        return jsonify(payload)

    @app.get("/api/agent/sources")
    def agent_sources():
        """Load recent sessions for any selected Web Agent provider."""
        require_local_agent_request()
        platform = request.args.get("platform", computer_use_settings.settings.platform).strip().lower()
        browser_name = request.args.get("browser", "").strip().lower()
        try:
            payload = load_agent_source_catalog(
                platform=platform,
                browser=browser_name,
                source_kind="sources",
                collector=lambda: list_agent_sources(
                    platform,
                    browser_name,
                    saved_config,
                    silent=True,
                ),
            )
        except (RuntimeError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 409
        return jsonify(payload)

    @app.get("/api/agent/chatgpt-project-sessions")
    def agent_chatgpt_project_sessions():
        """Load recent sessions for one selected ChatGPT project."""
        require_local_agent_request()
        browser_name = request.args.get("browser", "").strip().lower()
        project_url = request.args.get("project_url", "").strip()
        try:
            normalized_project_url = normalize_agent_project_url("chatgpt", project_url)
            payload = load_agent_source_catalog(
                platform="chatgpt",
                browser=browser_name,
                source_kind="project-sessions",
                project_url=normalized_project_url or project_url,
                collector=lambda: {
                    **list_chatgpt_project_sessions(
                        browser_name,
                        project_url,
                        saved_config,
                        silent=True,
                    ),
                    "platform": "chatgpt",
                },
            )
        except (RuntimeError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 409
        return jsonify(payload)

    @app.get("/api/agent/project-sessions")
    def agent_project_sessions():
        """Load recent sessions inside one provider-neutral Agent Project."""
        require_local_agent_request()
        platform = request.args.get("platform", computer_use_settings.settings.platform).strip().lower()
        browser_name = request.args.get("browser", "").strip().lower()
        project_url = request.args.get("project_url", "").strip()
        try:
            normalized_project_url = normalize_agent_project_url(platform, project_url)
            payload = load_agent_source_catalog(
                platform=platform,
                browser=browser_name,
                source_kind="project-sessions",
                project_url=normalized_project_url or project_url,
                collector=lambda: list_agent_project_sessions(
                    platform,
                    browser_name,
                    project_url,
                    saved_config,
                    silent=True,
                ),
            )
        except (RuntimeError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 409
        return jsonify(payload)

    @app.get("/api/agent/chatgpt-session-history")
    def agent_chatgpt_session_history():
        """Load one selected ChatGPT conversation without persisting remote messages."""
        require_local_agent_request()
        browser_name = request.args.get("browser", "").strip().lower()
        conversation_url = normalize_chatgpt_conversation_url(
            request.args.get("conversation_url", "").strip()
        )
        if not conversation_url:
            return jsonify({"error": "Choose a valid ChatGPT conversation before loading its history."}), 400
        try:
            payload = fetch_chatgpt_conversation_history(
                browser_name,
                conversation_url,
                saved_config,
                silent=True,
            )
        except (RuntimeError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 409
        rendered_history: list[dict[str, Any]] = []
        for raw_item in payload.get("history", []):
            if not isinstance(raw_item, dict):
                continue
            item = dict(raw_item)
            item["response_html"] = str(render_prompt_markdown(str(item.get("response", ""))))
            rendered_history.append(item)
        return jsonify(
            {
                "conversation_url": conversation_url,
                "title": str(payload.get("title") or "Untitled session"),
                "history": rendered_history,
                "limit": int(payload.get("limit") or len(rendered_history)),
            }
        )

    @app.post("/api/agent/stop")
    def stop_agent():
        require_local_agent_request()
        return jsonify(
            {
                "stop_requested": computer_use_agent_service.request_stop(),
                "runtime": computer_use_settings.snapshot(),
                "agent": build_agent_snapshot(),
            }
        )

    @app.get("/browser")
    def browser():
        filters = normalize_browser_filters(
            source=request.args.get("source"),
            media_kind=request.args.get("kind"),
            query=request.args.get("q"),
            sort=request.args.get("sort"),
            page=request.args.get("page"),
            session=request.args.get("session"),
            session_view=request.args.get("session_view"),
            view=request.args.get("view"),
            media_id=request.args.get("media_id"),
            session_page=request.args.get("session_page"),
        )
        force_refresh = request.args.get("refresh") == "1"
        prompt_page = None
        saved_prompt_keys = prompt_store.saved_pointer_keys()
        if filters["view"] == "text":
            media_items = media_catalog.snapshot(force_refresh=force_refresh)
            text_page = query_chat_history(
                media_catalog.local_store_root,
                source=filters["source"],
                query=filters["q"],
                sort=filters["sort"],
                page=filters["page"],
                session_view=filters["session_view"],
                session=filters["session"],
            )
            text_page = attach_media_references(
                text_page,
                media_items,
                lambda stable_id: url_for(
                    "browser",
                    view="media",
                    media_id=stable_id,
                    source="all",
                    kind="all",
                    q="",
                    sort="newest",
                ),
            )
            all_items = ()
            media_page = None
            media_payload = []
        elif filters["view"] == "prompts":
            prompt_page = prompt_store.query(
                source=filters["source"],
                query=filters["q"],
                sort=filters["sort"],
                page=filters["page"],
            )
            all_items = ()
            media_page = None
            text_page = None
            media_payload = []
        else:
            all_items = media_catalog.snapshot(force_refresh=force_refresh)
            media_page = media_catalog.query(
                source=filters["source"],
                media_kind=filters["kind"],
                query=filters["q"],
                sort=filters["sort"],
                page=filters["page"],
                chatgpt_session_key=filters["session"],
                chatgpt_session_view=filters["session_view"],
                media_id=filters["media_id"],
            )
            text_page = None
            media_payload = [serialize_media_item(item) for item in media_page.items]
        browser_search_suggestions = build_browser_search_suggestions(
            view=filters["view"],
            media_items=media_page.items if media_page is not None else all_items,
            text_page=text_page,
            prompt_page=prompt_page,
        )
        return render_template(
            "browser.html",
            media_page=media_page,
            text_page=text_page,
            prompt_page=prompt_page,
            media_payload=media_payload,
            filters=filters,
            browser_search_suggestions=browser_search_suggestions,
            has_any_media=bool(all_items),
            has_any_text=bool(text_page and text_page.total_count),
            has_any_prompts=prompt_store.has_any(),
            saved_prompt_keys=saved_prompt_keys,
            prompt_pointer_key=prompt_pointer_key,
            format_captured_at_timestamp_label=format_captured_at_timestamp_label,
            format_chat_message_timestamp_label=format_chat_message_timestamp_label,
            format_media_size=format_media_size,
            render_prompt_markdown=render_prompt_markdown,
            render_cached_message=render_cached_message,
            file_manager_label=local_file_manager_label(),
            version=APP_VERSION,
        )

    @app.get("/browser/session/<session_id>/export")
    def browser_session_export(session_id: str):
        """Download one complete session or the currently displayed session page."""
        source = request.args.get("source", "all")
        sort = request.args.get("sort", "newest")
        page_only = request.args.get("scope") == "page"
        text_page = query_chat_history(
            media_catalog.local_store_root,
            source=source,
            sort=sort,
            page=request.args.get("page", "1") if page_only else 1,
            page_size=100 if page_only else 1_000_000,
            session_view=True,
            session=session_id,
        )
        markdown = build_chat_history_markdown(
            text_page,
            message_count=len(text_page.items) if page_only else None,
        )
        if not markdown:
            abort(404)
        title = text_page.current_session.conversation_title if text_page.current_session else "session"
        filename = "".join(
            character if character.isalnum() or character in {"-", "_", " "} else "_"
            for character in str(title)
        ).strip()
        filename = "_".join(filename.split()) or "session"
        if page_only:
            filename = f"{filename}_page_{text_page.current_page}"
        ascii_filename = "".join(
            character
            if character.isascii() and (character.isalnum() or character in {"-", "_", " "})
            else "_"
            for character in filename
        ).strip()
        ascii_filename = "_".join(ascii_filename.split()) or "session"
        download_filename = f"{filename}.md"
        return Response(
            markdown,
            mimetype="text/markdown",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="{ascii_filename}.md"; '
                    f"filename*=UTF-8''{quote(download_filename, safe='')}"
                )
            },
        )

    @app.get("/browser/media/<path:relative_path>")
    def browser_media(relative_path: str):
        resolved_path = resolve_browser_media_path(media_catalog.local_store_root, relative_path)
        if resolved_path is None:
            abort(404)
        return send_file(resolved_path, conditional=True, etag=True, max_age=0)

    @app.post("/api/browser/prompts")
    def add_browser_prompt():
        payload = request.get_json(silent=True) or {}
        try:
            item, created = prompt_store.add_pointer(
                source=str(payload.get("source") or ""),
                conversation_id=str(payload.get("conversation_id") or ""),
                message_key=str(payload.get("message_key") or ""),
            )
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except LookupError as exc:
            return jsonify({"error": str(exc)}), 404
        return jsonify({"created": created, "item": serialize_prompt_item(item)})

    @app.get("/browser/deleted-preview/<stable_id>")
    def browser_deleted_preview(stable_id: str):
        resolved_path = media_catalog.deleted_preview_path(stable_id)
        if resolved_path is None:
            abort(404)
        return send_file(resolved_path, conditional=True, etag=True, max_age=0)

    @app.post("/api/browser/media/<stable_id>/delete")
    def delete_browser_media(stable_id: str):
        try:
            item = media_catalog.delete(stable_id)
        except KeyError:
            return jsonify({"error": "Cached media was not found."}), 404
        except FileNotFoundError:
            return jsonify({"error": "Cached media is no longer available."}), 404
        except (OSError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 409
        return jsonify({"item": serialize_media_item(item)})

    @app.post("/api/browser/media/<stable_id>/restore")
    def restore_browser_media(stable_id: str):
        try:
            item = media_catalog.restore(stable_id)
        except KeyError:
            return jsonify({"error": "Removed media was not found."}), 404
        except FileNotFoundError:
            return jsonify({"error": "The retained preview is no longer available."}), 404
        except (OSError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 409
        return jsonify({"item": serialize_media_item(item)})

    @app.post("/api/browser/media/<stable_id>/reveal")
    def reveal_browser_media(stable_id: str):
        if not is_loopback_address(request.remote_addr):
            return jsonify({"error": "Local files can only be revealed from this computer."}), 403

        resolved_path = media_catalog.resolved_media_path(stable_id)
        if resolved_path is None:
            return jsonify({"error": "Cached media is no longer available."}), 404
        try:
            reveal_media_path(resolved_path)
        except OSError as exc:
            return jsonify({"error": f"Unable to open {local_file_manager_label()}: {exc}"}), 500
        return jsonify({"revealed": True, "file_manager": local_file_manager_label()})

    @app.post("/api/browser/chatgpt/session/refresh")
    def refresh_browser_chatgpt_session():
        """Start a targeted ChatGPT refresh for one valid conversation URL."""
        payload = request.get_json(silent=True) or {}
        conversation_url = str(payload.get("conversation_url") or "").strip()
        if not is_chatgpt_conversation_url(conversation_url):
            return jsonify({"error": "A valid ChatGPT session URL is required."}), 400

        resource_count = sum(
            item.source == "chatgpt"
            for item in media_catalog.snapshot(force_refresh=True)
        )
        session_config = replace(saved_config, chatgpt_project_url=conversation_url)
        try:
            chatgpt_service.start(session_config)
        except RuntimeError as exc:
            return jsonify({"error": str(exc)}), 409
        return (
            jsonify(
                {
                    "started": True,
                    "session_key": chatgpt_conversation_id(conversation_url),
                    "resource_count": resource_count,
                    "status_url": url_for("api_chatgpt_status"),
                }
            ),
            202,
        )

    def start_cache_source_runtime(source_key: str):
        """Persist shared form values and start one registered runtime."""
        nonlocal saved_config
        cache_source = get_cache_source_view(source_key)
        runtime = cache_runtimes.get(source_key)
        if cache_source is None or runtime is None:
            abort(404)
        config = parse_form_config(saved_config, preserve_missing_booleans=True)
        saved_config = config
        save_config(saved_config)
        runtime_config = config
        if cache_source.require_browser_ready:
            browser_name = getattr(runtime_config, cache_source.browser_config_field)
            descriptor = browser_descriptors(runtime_config).get(browser_name)
            if descriptor is None:
                runtime.state.finish_error(f"Unsupported {cache_source.label} browser: {browser_name}")
                return redirect(cache_source_url(source_key))
        try:
            if source_key == "chatgpt":
                content_mode = (
                    "media"
                    if request.form.get("chatgpt_content_mode") == "media"
                    else "text"
                )
                runtime.service.start(runtime_config, content_mode=content_mode)
            else:
                runtime.service.start(runtime_config)
        except RuntimeError as exc:
            if runtime.service.is_running():
                runtime.state.append_event(str(exc))
                runtime.state.update(last_error=str(exc))
            else:
                runtime.state.finish_error(str(exc))
        return redirect(cache_source_url(source_key))

    def stop_cache_source_runtime(source_key: str):
        """Request a safe stop for one registered runtime."""
        cache_source = get_cache_source_view(source_key)
        runtime = cache_runtimes.get(source_key)
        if cache_source is None or runtime is None:
            abort(404)
        runtime.service.request_stop()
        return redirect(cache_source_url(source_key))

    def start_grok_history_runtime():
        """Persist shared form values and start the Grok text-history runtime."""
        nonlocal saved_config
        config = parse_form_config(saved_config, preserve_missing_booleans=True)
        saved_config = config
        save_config(saved_config)
        browser_name = config.grok_browser
        descriptor = browser_descriptors(config).get(browser_name)
        if descriptor is None:
            grok_history_state.finish_error(f"Unsupported Grok browser: {browser_name}")
            return redirect(cache_source_url("grok"))
        try:
            grok_history_service.start(config)
        except RuntimeError as exc:
            if grok_history_service.is_running():
                grok_history_state.append_event(str(exc))
                grok_history_state.update(last_error=str(exc))
            else:
                grok_history_state.finish_error(str(exc))
        return redirect(cache_source_url("grok"))

    def stop_grok_history_runtime():
        """Request a safe stop for the Grok text-history runtime."""
        grok_history_service.request_stop()
        return redirect(cache_source_url("grok"))

    @app.post("/cache/<source_key>/start")
    def start_cache_source(source_key: str):
        return start_cache_source_runtime(source_key)

    @app.post("/cache/<source_key>/stop")
    def stop_cache_source(source_key: str):
        return stop_cache_source_runtime(source_key)

    @app.post("/start")
    def start():
        return start_cache_source_runtime("x")

    @app.post("/stop")
    def stop():
        return stop_cache_source_runtime("x")

    @app.post("/grok/start")
    def start_grok():
        return start_cache_source_runtime("grok")

    @app.post("/grok/stop")
    def stop_grok():
        return stop_cache_source_runtime("grok")

    @app.post("/cache/grok/text/start")
    def start_grok_text_history():
        return start_grok_history_runtime()

    @app.post("/cache/grok/text/stop")
    def stop_grok_text_history():
        return stop_grok_history_runtime()

    @app.post("/chatgpt/start")
    def start_chatgpt():
        return start_cache_source_runtime("chatgpt")

    @app.post("/chatgpt/stop")
    def stop_chatgpt():
        return stop_cache_source_runtime("chatgpt")

    @app.post("/gemini/start")
    def start_gemini():
        return start_cache_source_runtime("gemini")

    @app.post("/gemini/stop")
    def stop_gemini():
        return stop_cache_source_runtime("gemini")

    @app.post("/chatgpt/reset")
    def reset_chatgpt():
        if chatgpt_service.is_running():
            chatgpt_state.append_event("Reset skipped because a ChatGPT sync is still running.")
            chatgpt_state.update(last_error="Cannot reset ChatGPT state while a sync is running.")
            return redirect(cache_source_url("chatgpt"))

        result = reset_chatgpt_state(project_name=saved_config.chatgpt_project_name)
        snapshot = build_chatgpt_initial_snapshot(
            APP_VERSION,
            project_name=saved_config.chatgpt_project_name,
        )
        message = (
            f"Reset ChatGPT state. Removed {result.removed_media_files} image files, "
            f"{result.removed_state_files} state files, "
            f"{result.removed_partial_files} partial files."
        )
        snapshot.message = message
        snapshot.recent_events = [f"[{utc_now()}] {message}"]
        chatgpt_state.replace_snapshot(snapshot)
        return redirect(cache_source_url("chatgpt"))

    @app.post("/grok/reset")
    def reset_grok():
        if grok_service.is_running():
            grok_state.append_event("Reset skipped because a Grok sync is still running.")
            grok_state.update(last_error="Cannot reset Grok state while a sync is running.")
            return redirect(cache_source_url("grok"))

        result = reset_grok_state()
        snapshot = build_grok_initial_snapshot(APP_VERSION)
        message = (
            f"Reset Grok state. Removed {result.removed_media_files} media files, "
            f"{result.removed_state_files} state files, "
            f"{result.removed_partial_files} partial files."
        )
        snapshot.message = message
        snapshot.recent_events = [f"[{utc_now()}] {message}"]
        grok_state.replace_snapshot(snapshot)
        return redirect(cache_source_url("grok"))

    @app.post("/settings")
    def save_settings():
        nonlocal saved_config
        saved_config = parse_form_config(saved_config)
        save_config(saved_config)
        agent_field_names = {
            "agent_operating_system",
            "agent_context_limit_mib",
            "agent_max_turns",
            "agent_command_timeout_seconds",
            "agent_macos_system_prompt",
            "agent_windows_system_prompt",
        }
        if any(request.form.get(field_name) is not None for field_name in agent_field_names):
            candidate_payload = asdict(computer_use_settings.settings)
            candidate_payload.update(
                {
                    "operating_system": request.form.get(
                        "agent_operating_system",
                        computer_use_settings.settings.operating_system,
                    ),
                    "context_limit_mib": request.form.get(
                        "agent_context_limit_mib",
                        computer_use_settings.settings.context_limit_mib,
                    ),
                    "max_turns": request.form.get(
                        "agent_max_turns",
                        computer_use_settings.settings.max_turns,
                    ),
                    "command_timeout_seconds": request.form.get(
                        "agent_command_timeout_seconds",
                        computer_use_settings.settings.command_timeout_seconds,
                    ),
                    "macos_system_prompt": request.form.get(
                        "agent_macos_system_prompt",
                        computer_use_settings.settings.macos_system_prompt,
                    ),
                    "windows_system_prompt": request.form.get(
                        "agent_windows_system_prompt",
                        computer_use_settings.settings.windows_system_prompt,
                    ),
                }
            )
            try:
                computer_use_settings.update(validate_computer_use_settings(candidate_payload))
            except (RuntimeError, ValueError):
                pass
        return redirect(url_for("settings"))

    @app.post("/settings/shadow-backup/sync")
    def start_shadow_backup_sync():
        nonlocal saved_config
        saved_config = parse_form_config(saved_config)
        save_config(saved_config)
        try:
            shadow_backup_service.start(saved_config)
        except ShadowBackupError as exc:
            shadow_backup_service.record_start_error(exc)
        return redirect(url_for("settings", _anchor="settings-cloud"))

    @app.get("/api/settings/shadow-backup/status")
    def api_shadow_backup_status():
        return jsonify(shadow_backup_service.snapshot())

    @app.post("/api/settings/shadow-backup/destination")
    def choose_shadow_backup_destination_route():
        if not is_loopback_address(request.remote_addr):
            return jsonify({"error": "The folder picker is only available on the local host."}), 403

        payload = request.get_json(silent=True) or {}
        requested_initial_path = payload.get("initial_path")
        initial_value = (
            requested_initial_path.strip()
            if isinstance(requested_initial_path, str)
            else str(saved_config.shadow_backup_destination)
        )
        try:
            selected_path = choose_shadow_backup_destination(
                Path(initial_value or str(saved_config.shadow_backup_destination))
            )
        except ShadowBackupError as exc:
            return jsonify({"error": str(exc)}), 500

        if selected_path is None:
            return jsonify({"cancelled": True})
        return jsonify({"destination": str(selected_path)})

    @app.post("/api/settings/directory")
    def choose_settings_directory_route():
        if not is_loopback_address(request.remote_addr):
            return jsonify({"error": "The folder picker is only available on the local host."}), 403

        directory_options = {
            "chrome_user_data_dir": (
                saved_config.chrome_user_data_dir,
                "Select Chrome user data directory",
            ),
            "shadow_backup_destination": (
                saved_config.shadow_backup_destination,
                "Select shadow cloud backup destination",
            ),
            "agent_allowed_root": (
                Path(computer_use_settings.settings.workspace_path),
                "Select local Agent project folder",
            ),
        }
        payload = request.get_json(silent=True) or {}
        field_name = payload.get("field")
        if field_name not in directory_options:
            return jsonify({"error": "Unknown Settings directory field."}), 400

        default_path, picker_prompt = directory_options[field_name]
        requested_initial_path = payload.get("initial_path")
        initial_value = (
            requested_initial_path.strip()
            if isinstance(requested_initial_path, str)
            else str(default_path)
        )
        try:
            selected_path = choose_settings_directory(
                Path(initial_value or str(default_path)),
                picker_prompt,
            )
        except ShadowBackupError as exc:
            return jsonify({"error": str(exc)}), 500

        if selected_path is None:
            return jsonify({"cancelled": True})
        return jsonify({"directory": str(selected_path)})

    @app.get("/api/status")
    def api_status():
        return jsonify(build_reconciled_cache_snapshot("x"))

    @app.get("/api/grok/status")
    def api_grok_status():
        return jsonify(build_reconciled_cache_snapshot("grok"))

    @app.get("/api/cache/grok/text/status")
    def api_grok_text_status():
        return jsonify(build_reconciled_grok_history_snapshot())

    @app.get("/api/chatgpt/status")
    def api_chatgpt_status():
        return jsonify(build_reconciled_cache_snapshot("chatgpt"))

    @app.get("/api/gemini/status")
    def api_gemini_status():
        return jsonify(build_reconciled_cache_snapshot("gemini"))

    @app.get("/api/cache/<source_key>/status")
    def api_cache_status(source_key: str):
        if get_cache_source_view(source_key) is None or source_key not in cache_runtimes:
            abort(404)
        return jsonify(build_reconciled_cache_snapshot(source_key))

    @app.get("/api/browser-session")
    def api_browser_session():
        platform_name = request.args.get("platform", "").strip().lower()
        browser_name = request.args.get("browser", "").strip().lower()
        scope = request.args.get("scope", "").strip().lower()
        if scope == "agent" and platform_name == "chatgpt":
            try:
                payload, source_payload = probe_and_collect_chatgpt_sources(
                    browser_name,
                    saved_config,
                    silent=True,
                )
            except ValueError as exc:
                return jsonify({"error": str(exc)}), 400
            if source_payload is not None:
                agent_source_cache.store(
                    platform="chatgpt",
                    browser=browser_name,
                    source_kind="sources",
                    payload=source_payload,
                )
                payload["agent_sources"] = source_payload
            elif payload.get("can_download"):
                payload["agent_sources_error"] = (
                    "ChatGPT is signed in, but Recent sessions could not be loaded from this browser."
                )
            return jsonify(payload)
        try:
            payload = probe_browser_session(
                platform_name,
                browser_name,
                saved_config,
                silent=scope == "agent",
            )
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify(payload)

    return app


def format_media_size(content_bytes: int) -> str:
    """Render a byte count as a compact, readable English file size."""
    size = max(0, int(content_bytes))
    if size < 1_024:
        return f"{size:,} B"
    if size < 1_024**2:
        return f"{size / 1_024:.2f} KiB"
    if size < 1_024**3:
        return f"{size / 1_024**2:.2f} MiB"
    return f"{size / 1_024**3:.2f} GiB"
