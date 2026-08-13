"""Flask application for the local web console."""

# Code version: v1.24.4-codex.1

from __future__ import annotations

import atexit
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from flask import Flask, Response, abort, jsonify, redirect, render_template, request, send_file, url_for
from markdown_it import MarkdownIt
from markupsafe import Markup

from app.core.browser_sessions import browser_descriptors, build_browser_options, probe_browser_session
from app.core.chatgpt_downloader import (
    build_chatgpt_initial_snapshot,
    chatgpt_conversation_id,
    is_chatgpt_conversation_url,
    reset_chatgpt_state,
)
from app.core.chatgpt_service import ChatGPTDownloadService
from app.core.chat_history_browser import (
    attach_media_references,
    build_chat_history_markdown,
    format_chat_message_timestamp_label,
    query_chat_history,
)
from app.core.config import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    MAX_MAX_MEDIA_FILE_SIZE_MIB,
    MIN_MAX_MEDIA_FILE_SIZE_MIB,
    CrawlConfig,
    LOCAL_STORE_ROOT,
    MAX_CHATGPT_SCAN_WAIT_SECONDS,
    MAX_CHATGPT_STARTUP_TIMEOUT_SECONDS,
    MIN_CHATGPT_SCAN_WAIT_SECONDS,
    MIN_CHATGPT_STARTUP_TIMEOUT_SECONDS,
    load_saved_config,
    save_config,
)
from app.core.devspace_agent import (
    AGENT_PLATFORM_CONFIG,
    AGENT_PLATFORM_OPTIONS,
    ChatGPTWebAgentService,
    DevSpaceRuntimeManager,
    is_loopback_address,
    validate_devspace_settings,
)
from app.core.gemini_downloader import build_gemini_initial_snapshot
from app.core.gemini_service import GeminiHistoryService
from app.core.grok_downloader import build_grok_initial_snapshot, reset_grok_state
from app.core.grok_service import GrokDownloadService
from app.core.logging_setup import configure_logging, get_log_file_path
from app.core.local_media_browser import (
    LocalMediaCatalog,
    format_captured_at_timestamp_label,
    local_file_manager_label,
    normalize_browser_filters,
    reveal_media_path,
    resolve_local_media_path,
)
from app.core.service import CacheLikesService
from app.core.shadow_backup import (
    ShadowBackupError,
    ShadowBackupService,
    choose_settings_directory,
    choose_shadow_backup_destination,
)
from app.core.state import TaskState, build_initial_snapshot, utc_now
from app.core.version import APP_VERSION
from app.web.cache_sources import (
    LLM_CACHE_SOURCE_VIEWS,
    LLM_SWITCHER_SOURCE_VIEWS,
    MEDIA_CACHE_SOURCE_VIEWS,
    cache_source_views_for_group,
    get_cache_source_label,
    get_cache_source_view,
)


CACHE_RECONCILE_PHASES = {"idle", "finished", "completed", "success", "stopped"}
PROMPT_MARKDOWN_RENDERER = MarkdownIt(
    "commonmark",
    {"html": False, "linkify": False, "typographer": False},
)


def render_prompt_markdown(value: str) -> Markup:
    """Render stored ChatGPT prompt Markdown while escaping embedded HTML."""
    prompt = str(value or "").replace("\x00", "").strip()
    return Markup(PROMPT_MARKDOWN_RENDERER.render(prompt)) if prompt else Markup("")


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

    media_catalog = LocalMediaCatalog(local_store_root or LOCAL_STORE_ROOT)
    app.extensions["local_media_catalog"] = media_catalog
    shadow_backup_service = ShadowBackupService(media_catalog.local_store_root)
    app.extensions["shadow_backup_service"] = shadow_backup_service
    state = TaskState(version=APP_VERSION)
    service = CacheLikesService(state, shadow_backup_service=shadow_backup_service)
    grok_state = TaskState(version=APP_VERSION, snapshot_factory=build_grok_initial_snapshot)
    grok_service = GrokDownloadService(grok_state, shadow_backup_service=shadow_backup_service)
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
    devspace_runtime = DevSpaceRuntimeManager(Path(get_log_file_path()).with_name("devspace-agent.log"))
    devspace_agent_service = ChatGPTWebAgentService(devspace_runtime)
    app.extensions["devspace_runtime"] = devspace_runtime
    app.extensions["devspace_agent_service"] = devspace_agent_service
    atexit.register(devspace_runtime.stop_managed_process_at_exit)
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
            else url_for("browser_media", relative_path=item.relative_path)
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
            "background browser",
        )
        return render_template(
            cache_source.template_name,
            cache_source=cache_source,
            cache_source_options=cache_source_views_for_group(cache_source.group_key),
            snapshot=build_reconciled_cache_snapshot(source_key),
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
        if source_key == "chatgpt":
            remembered_platform = request.args.get("agent_platform", "").strip().lower()
            if remembered_platform in AGENT_PLATFORM_CONFIG:
                response = redirect(cache_source_url("chatgpt"))
                response.set_cookie(
                    "cachelikes_agent_platform",
                    remembered_platform,
                    path="/",
                    samesite="Lax",
                )
                return response
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
            agent_settings=devspace_runtime.settings,
            agent_runtime_snapshot=devspace_runtime.snapshot(),
        )

    def require_local_agent_request() -> None:
        """Keep the DevSpace owner control plane on the host loopback interface."""
        host_name = urlsplit(f"//{request.host}").hostname
        if not is_loopback_address(request.remote_addr) or not is_loopback_address(host_name):
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

    @app.get("/agent")
    def agent():
        require_local_agent_request()
        agent_settings = devspace_runtime.settings
        runtime_snapshot = devspace_runtime.snapshot()
        remembered_platform = request.cookies.get("cachelikes_agent_platform", "").strip().lower()
        if remembered_platform in AGENT_PLATFORM_CONFIG:
            agent_settings = replace(
                agent_settings,
                platform=remembered_platform,
                target_url=AGENT_PLATFORM_CONFIG[remembered_platform]["url"],
            )
        return render_template(
            "agent.html",
            version=APP_VERSION,
            runtime_snapshot=runtime_snapshot,
            agent_snapshot=devspace_agent_service.snapshot(),
            settings=agent_settings,
            agent_project_name=Path(agent_settings.allowed_root).name or agent_settings.allowed_root,
            platform_options=AGENT_PLATFORM_OPTIONS,
            platform_labels={key: value["label"] for key, value in AGENT_PLATFORM_CONFIG.items()},
        )

    @app.get("/api/agent/status")
    def agent_status():
        require_local_agent_request()
        return jsonify(
            {
                "runtime": devspace_runtime.snapshot(),
                "agent": devspace_agent_service.snapshot(),
            }
        )

    @app.post("/api/agent/runtime/start")
    def start_agent_runtime():
        require_local_agent_request()
        try:
            settings = validate_devspace_settings(request.get_json(silent=True) or {})
            runtime_snapshot = devspace_runtime.start(settings)
        except (RuntimeError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 409
        return jsonify({"runtime": runtime_snapshot, "agent": devspace_agent_service.snapshot()})

    @app.post("/api/agent/runtime/stop")
    def stop_agent_runtime():
        require_local_agent_request()
        if devspace_agent_service.snapshot()["running"]:
            return jsonify({"error": "Stop the active Agent request before stopping DevSpace."}), 409
        return jsonify(
            {
                "runtime": devspace_runtime.stop(),
                "agent": devspace_agent_service.snapshot(),
            }
        )

    @app.post("/api/agent/ask")
    def ask_agent():
        require_local_agent_request()
        payload = request.get_json(silent=True) or {}
        try:
            devspace_agent_service.start(
                str(payload.get("prompt", "")),
                str(payload.get("workspace_path", "")),
                saved_config,
            )
        except (RuntimeError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 409
        return jsonify(
            {
                "runtime": devspace_runtime.snapshot(),
                "agent": devspace_agent_service.snapshot(),
            }
        ), 202

    @app.post("/api/agent/stop")
    def stop_agent():
        require_local_agent_request()
        return jsonify(
            {
                "stop_requested": devspace_agent_service.request_stop(),
                "runtime": devspace_runtime.snapshot(),
                "agent": devspace_agent_service.snapshot(),
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
        return render_template(
            "browser.html",
            media_page=media_page,
            text_page=text_page,
            media_payload=media_payload,
            filters=filters,
            has_any_media=bool(all_items),
            has_any_text=bool(text_page and text_page.total_count),
            format_captured_at_timestamp_label=format_captured_at_timestamp_label,
            format_chat_message_timestamp_label=format_chat_message_timestamp_label,
            format_media_size=format_media_size,
            render_prompt_markdown=render_prompt_markdown,
            file_manager_label=local_file_manager_label(),
            version=APP_VERSION,
        )

    @app.get("/browser/session/<session_id>/export")
    def browser_session_export(session_id: str):
        """Download one complete cached text session in the selected format."""
        source = request.args.get("source", "all")
        sort = request.args.get("sort", "newest")
        text_page = query_chat_history(
            media_catalog.local_store_root,
            source=source,
            sort=sort,
            page=1,
            page_size=1_000_000,
            session_view=True,
            session=session_id,
        )
        markdown = build_chat_history_markdown(text_page)
        if not markdown:
            abort(404)
        title = text_page.current_session.conversation_title if text_page.current_session else "session"
        filename = "".join(
            character if character.isalnum() or character in {"-", "_", " "} else "_"
            for character in str(title)
        ).strip()
        filename = "_".join(filename.split()) or "session"
        return Response(
            markdown,
            mimetype="text/markdown",
            headers={"Content-Disposition": f'attachment; filename="{filename}.md"'},
        )

    @app.get("/browser/media/<path:relative_path>")
    def browser_media(relative_path: str):
        resolved_path = resolve_local_media_path(media_catalog.local_store_root, relative_path)
        if resolved_path is None:
            abort(404)
        return send_file(resolved_path, conditional=True, etag=True, max_age=0)

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
        if request.remote_addr not in {"127.0.0.1", "::1"}:
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
        if cache_source.require_browser_ready:
            browser_name = getattr(config, cache_source.browser_config_field)
            descriptor = browser_descriptors(config).get(browser_name)
            if descriptor is None:
                runtime.state.finish_error(f"Unsupported {cache_source.label} browser: {browser_name}")
                return redirect(cache_source_url(source_key))
        try:
            runtime.service.start(config)
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
        if request.form.get("agent_port") is not None:
            agent_port = parse_int_field(
                "agent_port",
                devspace_runtime.settings.port,
                minimum=1_024,
                maximum=65_535,
            )
            if agent_port != devspace_runtime.settings.port:
                try:
                    devspace_runtime.update_settings(
                        replace(devspace_runtime.settings, port=agent_port)
                    )
                except RuntimeError:
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
        return redirect(url_for("settings"))

    @app.get("/api/settings/shadow-backup/status")
    def api_shadow_backup_status():
        return jsonify(shadow_backup_service.snapshot())

    @app.post("/api/settings/shadow-backup/destination")
    def choose_shadow_backup_destination_route():
        if request.remote_addr not in {"127.0.0.1", "::1"}:
            return jsonify({"error": "The folder picker is only available from this Mac."}), 403

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
        if request.remote_addr not in {"127.0.0.1", "::1"}:
            return jsonify({"error": "The folder picker is only available from this Mac."}), 403

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
                Path(devspace_runtime.settings.allowed_root),
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
        try:
            payload = probe_browser_session(platform_name, browser_name, saved_config)
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
