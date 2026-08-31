"""Read ChatGPT Web sessions, projects, and conversation history for the local Agent.

Code version: v1.5.2-codex.1
"""

from __future__ import annotations

from collections.abc import Iterable
import re
from typing import Any
from urllib.parse import urlencode, urlsplit

from .browser_sessions import (
    CHATGPT_AUTH_SESSION_URL,
    _chatgpt_status_payload,
    _parse_chatgpt_auth_response,
    _read_chatgpt_auth_payload,
    browser_descriptors,
    goto_with_retry,
    launch_chromium_context,
    select_provider_tab,
    sync_playwright_or_error,
)
from .chatgpt_downloader import (
    _chatgpt_conversation_api_url,
    _chatgpt_api_request_headers,
    _chatgpt_project_id,
    _extract_chatgpt_conversation_messages,
    _get_chatgpt_api_json,
    _load_chatgpt_session_request_headers,
    _project_conversation_prefix,
)
from .config import CrawlConfig
from .safari_automation import SafariContext
from .state import utc_now


CHATGPT_HOME_URL = "https://chatgpt.com/"
CHATGPT_HOSTS = frozenset({"chatgpt.com", "www.chatgpt.com"})
AGENT_SOURCE_LIMIT = 20
CHATGPT_SOURCE_API_LIMIT = 100
CHATGPT_PROJECT_API_LIMIT = 20
CHATGPT_HISTORY_TURN_LIMIT = 100
CHATGPT_PROJECT_API_ENDPOINTS = (
    "/backend-api/gizmos/snorlax/sidebar?owned_only=true&conversations_per_gizmo=5&limit=20",
    "/backend-api/gizmos/bootstrap?limit=20",
    "/backend-api/gizmos?cursor=0&limit=100",
    "/backend-api/gizmos?cursor=&limit=100",
    "/backend-api/projects?offset=0&limit=100&order=updated",
)
CHATGPT_PROJECT_PATH_PATTERN = re.compile(r"^/g/[^/]+/project/?$", re.IGNORECASE)
CHATGPT_CONVERSATION_PATH_PATTERN = re.compile(
    r"^/(?:g/[^/]+/)?c/[^/]+/?$",
    re.IGNORECASE,
)


def _discover_chatgpt_agent_efforts(page: Any) -> dict[str, Any]:
    """Return a bounded live Sol effort catalog without sending a message."""
    from .computer_use_agent import (
        CHATGPT_EFFORT_POLICY_HIGHEST,
        DEFAULT_CHATGPT_MODEL,
        _select_chatgpt_model,
    )

    observation: dict[str, Any] = {}
    try:
        model_verified = _select_chatgpt_model(
            page,
            "chromium",
            DEFAULT_CHATGPT_MODEL,
            observation,
            thinking_effort=CHATGPT_EFFORT_POLICY_HIGHEST,
        )
    except Exception:  # pragma: no cover - provider DOM failures are runtime-specific
        model_verified = False
        observation = {"reason": "effort-probe-failed"}
    available_efforts = [
        str(label).strip()
        for label in observation.get("available_efforts") or []
        if str(label).strip()
    ][:64]
    effort_catalog_complete = bool(
        model_verified and observation.get("effort_catalog_complete")
    )
    payload: dict[str, Any] = {
        "model_verified": bool(model_verified),
        "actual_model": str(observation.get("observed") or "").strip(),
        "thinking_effort": str(observation.get("thinking_effort") or "").strip(),
        "available_efforts": available_efforts,
        "effort_catalog_complete": effort_catalog_complete,
    }
    if not effort_catalog_complete:
        payload["effort_catalog_error"] = str(
            observation.get("reason") or "effort-catalog-unavailable"
        )[:160]
    return payload


def probe_and_collect_chatgpt_sources(
    browser_name: str,
    config: CrawlConfig,
    *,
    silent: bool = False,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Verify ChatGPT and collect Agent sources through one browser launch.

    The Agent page needs both browser readiness and recent-session discovery.
    Keeping those operations inside one context prevents the status request and
    the following source request from launching separate Chromium processes.
    """
    descriptor = browser_descriptors(config).get(str(browser_name or "").strip().lower())
    if descriptor is None:
        raise ValueError(f"Unsupported browser: {browser_name}")

    status = {
        "platform": "chatgpt",
        "browser": descriptor.browser_id,
        "browser_label": descriptor.label,
        "icon_filename": descriptor.icon_filename,
        "logged_in": False,
        "can_download": False,
        "account_name": "ChatGPT account",
        "message": "",
    }
    try:
        if descriptor.engine == "safari":
            with SafariContext(CHATGPT_HOME_URL) as context:
                page = context.primary_page
                page.goto(CHATGPT_HOME_URL, wait_until="domcontentloaded", timeout=90_000)
                page.wait_for_load_state("domcontentloaded", 90_000)
                response = context.request.get(
                    CHATGPT_AUTH_SESSION_URL,
                    timeout=60_000,
                    headers={"Accept": "application/json", "Referer": CHATGPT_HOME_URL},
                )
                payload = _parse_chatgpt_auth_response(response.ok, response.text())
                status.update(_chatgpt_status_payload(descriptor.label, payload))
                if not status["can_download"]:
                    return status, None
                page.wait_for_timeout(1_000)
                sources = {
                    **_collect_sources(context, page, descriptor.label),
                    "platform": "chatgpt",
                }
                return status, sources

        if descriptor.engine != "chromium":
            raise ValueError(f"ChatGPT Agent sources do not support {descriptor.label}.")

        with sync_playwright_or_error() as playwright:
            with launch_chromium_context(
                playwright,
                descriptor,
                # ChatGPT's Cloudflare challenge rejects the headless clone
                # with HTTP 403. Keep this probe non-headless but backgrounded
                # and offscreen so it can use the real browser fingerprint
                # without surfacing a window to the user.
                headless=False,
                clone_profile_first=True,
                background_window=True,
                silent=silent,
            ) as context:
                page = select_provider_tab(
                    context,
                    home_url=CHATGPT_HOME_URL,
                    hosts=CHATGPT_HOSTS,
                    title="ChatGPT",
                )
                current_url = str(getattr(page, "url", "") or "").strip().rstrip("/")
                if current_url != CHATGPT_HOME_URL.rstrip("/"):
                    goto_with_retry(page, CHATGPT_HOME_URL, attempts=2, timeout_ms=90_000)
                payload = _read_chatgpt_auth_payload(page, descriptor.label)
                status.update(_chatgpt_status_payload(descriptor.label, payload))
                if not status["can_download"]:
                    return status, None
                page.wait_for_timeout(1_000)
                sources = {
                    **_collect_sources(context, page, descriptor.label),
                    "platform": "chatgpt",
                }
                status.update(_discover_chatgpt_agent_efforts(page))
                return status, sources
    except Exception as exc:  # pragma: no cover - depends on local browser state
        status["message"] = str(exc)
        return status, None


def list_chatgpt_agent_sources(
    browser_name: str,
    config: CrawlConfig,
    *,
    silent: bool = False,
) -> dict[str, Any]:
    """Return the recent root sessions and projects from one signed-in browser."""
    descriptor = browser_descriptors(config).get(str(browser_name or "").strip().lower())
    if descriptor is None:
        raise ValueError(f"Unsupported browser: {browser_name}")

    if descriptor.engine == "safari":
        with SafariContext(CHATGPT_HOME_URL) as context:
            page = context.primary_page
            page.goto(CHATGPT_HOME_URL, wait_until="domcontentloaded", timeout=90_000)
            page.wait_for_timeout(1_000)
            return _collect_sources(context, page, descriptor.label)

    if descriptor.engine != "chromium":
        raise ValueError(f"ChatGPT Agent sources do not support {descriptor.label}.")

    with sync_playwright_or_error() as playwright:
        with launch_chromium_context(
            playwright,
            descriptor,
            headless=False,
            clone_profile_first=True,
            background_window=True,
            silent=silent,
        ) as context:
            page = select_provider_tab(
                context,
                home_url=CHATGPT_HOME_URL,
                hosts=CHATGPT_HOSTS,
                title="ChatGPT",
            )
            current_url = str(getattr(page, "url", "") or "").strip().rstrip("/")
            if current_url != CHATGPT_HOME_URL.rstrip("/"):
                goto_with_retry(page, CHATGPT_HOME_URL, attempts=2, timeout_ms=90_000)
            page.wait_for_timeout(1_000)
            return _collect_sources(context, page, descriptor.label)


def list_chatgpt_project_sessions(
    browser_name: str,
    project_url: str,
    config: CrawlConfig,
    *,
    silent: bool = False,
) -> dict[str, Any]:
    """Return recent sessions for one ChatGPT project in the selected browser."""
    normalized_project_url = normalize_chatgpt_project_url(project_url)
    if not normalized_project_url:
        raise ValueError("Choose a valid ChatGPT project before loading its sessions.")

    descriptor = browser_descriptors(config).get(str(browser_name or "").strip().lower())
    if descriptor is None:
        raise ValueError(f"Unsupported browser: {browser_name}")

    if descriptor.engine == "safari":
        with SafariContext(CHATGPT_HOME_URL) as context:
            page = context.primary_page
            page.goto(CHATGPT_HOME_URL, wait_until="domcontentloaded", timeout=90_000)
            page.wait_for_timeout(500)
            sessions = _collect_project_sessions(context, normalized_project_url)
    elif descriptor.engine == "chromium":
        with sync_playwright_or_error() as playwright:
            with launch_chromium_context(
                playwright,
                descriptor,
                headless=False,
                clone_profile_first=True,
                background_window=True,
                silent=silent,
            ) as context:
                page = select_provider_tab(
                    context,
                    home_url=CHATGPT_HOME_URL,
                    hosts=CHATGPT_HOSTS,
                    title="ChatGPT",
                )
                current_url = str(getattr(page, "url", "") or "").strip().rstrip("/")
                if current_url != CHATGPT_HOME_URL.rstrip("/"):
                    goto_with_retry(page, CHATGPT_HOME_URL, attempts=2, timeout_ms=90_000)
                page.wait_for_timeout(500)
                sessions = _collect_project_sessions(context, normalized_project_url)
    else:
        raise ValueError(f"ChatGPT Agent sources do not support {descriptor.label}.")

    return {
        "project_url": normalized_project_url,
        "sessions": sessions[:AGENT_SOURCE_LIMIT],
        "limit": AGENT_SOURCE_LIMIT,
    }


def fetch_chatgpt_conversation_history(
    browser_name: str,
    conversation_url: str,
    config: CrawlConfig,
    *,
    silent: bool = False,
) -> dict[str, Any]:
    """Fetch one selected ChatGPT conversation as read-only Agent history."""
    normalized_conversation_url = normalize_chatgpt_conversation_url(conversation_url)
    if not normalized_conversation_url:
        raise ValueError("Choose a valid ChatGPT conversation before loading its history.")

    descriptor = browser_descriptors(config).get(str(browser_name or "").strip().lower())
    if descriptor is None:
        raise ValueError(f"Unsupported browser: {browser_name}")

    if descriptor.engine == "safari":
        with SafariContext(normalized_conversation_url) as context:
            page = context.primary_page
            page.goto(normalized_conversation_url, wait_until="domcontentloaded", timeout=90_000)
            page.wait_for_timeout(500)
            return _fetch_conversation_history(context, normalized_conversation_url)

    if descriptor.engine != "chromium":
        raise ValueError(f"ChatGPT Agent history does not support {descriptor.label}.")

    with sync_playwright_or_error() as playwright:
        with launch_chromium_context(
            playwright,
            descriptor,
            headless=False,
            clone_profile_first=True,
            background_window=True,
            silent=silent,
        ) as context:
            page = select_provider_tab(
                context,
                home_url=normalized_conversation_url,
                hosts=CHATGPT_HOSTS,
            )
            current_url = str(getattr(page, "url", "") or "").strip().rstrip("/")
            if current_url != normalized_conversation_url.rstrip("/"):
                goto_with_retry(page, normalized_conversation_url, attempts=2, timeout_ms=90_000)
            page.wait_for_timeout(500)
            return _fetch_conversation_history(context, normalized_conversation_url)


def _fetch_conversation_history(context: Any, conversation_url: str) -> dict[str, Any]:
    """Fetch and pair the selected conversation's user and assistant messages."""
    request_headers = _load_chatgpt_session_request_headers(context, conversation_url)
    api_headers = _chatgpt_api_request_headers(request_headers, conversation_url)
    api_url = _chatgpt_conversation_api_url(conversation_url)
    if not api_url:
        raise ValueError("The selected ChatGPT conversation URL is not valid.")
    payload = _get_chatgpt_api_json(context, api_url, api_headers)
    messages = _extract_chatgpt_conversation_messages(payload, conversation_url, utc_now())
    active_node_ids = _active_conversation_node_ids(payload)
    if active_node_ids:
        messages = [
            message
            for message in messages
            if str(message.get("message_key") or "").rsplit(":", 1)[-1] in active_node_ids
        ]
    history = _conversation_history_items(messages)
    return {
        "conversation_url": conversation_url,
        "title": str(payload.get("title") or "Untitled session").strip() or "Untitled session",
        "history": history[-CHATGPT_HISTORY_TURN_LIMIT:],
        "limit": CHATGPT_HISTORY_TURN_LIMIT,
    }


def _conversation_history_items(messages: Iterable[dict[str, Any]]) -> list[dict[str, str]]:
    """Pair ordered user and assistant messages into one-page-per-turn records."""
    history: list[dict[str, str]] = []
    pending_prompt: dict[str, Any] | None = None
    ordered_messages = sorted(
        (message for message in messages if isinstance(message, dict)),
        key=lambda message: int(message.get("message_index") or 0),
    )
    for message in ordered_messages:
        role = str(message.get("role") or "").strip().lower()
        content = str(message.get("content_text") or "").strip()
        if not content:
            continue
        if role == "user":
            pending_prompt = message
            continue
        if role != "assistant" or pending_prompt is None:
            continue
        history.append(
            {
                "prompt": str(pending_prompt.get("content_text") or "").strip(),
                "response": content,
                "started_at": str(pending_prompt.get("last_seen_at") or pending_prompt.get("first_seen_at") or ""),
                "finished_at": str(message.get("last_seen_at") or message.get("first_seen_at") or ""),
            }
        )
        pending_prompt = None
    return history


def _active_conversation_node_ids(payload: dict[str, object]) -> set[str]:
    """Return the current ChatGPT mapping branch when the API exposes one."""
    mapping = payload.get("mapping")
    current_node_id = str(payload.get("current_node") or "").strip()
    if not isinstance(mapping, dict) or not current_node_id:
        return set()
    active_node_ids: set[str] = set()
    visited: set[str] = set()
    while current_node_id and current_node_id not in visited:
        visited.add(current_node_id)
        node = mapping.get(current_node_id)
        if not isinstance(node, dict):
            break
        active_node_ids.add(current_node_id)
        current_node_id = str(node.get("parent") or "").strip()
    return active_node_ids


def normalize_chatgpt_project_url(value: str) -> str:
    """Return one canonical project URL, or an empty string for another ChatGPT URL."""
    return _normalize_chatgpt_url(value, CHATGPT_PROJECT_PATH_PATTERN)


def normalize_chatgpt_conversation_url(value: str) -> str:
    """Return one canonical root or project conversation URL."""
    return _normalize_chatgpt_url(value, CHATGPT_CONVERSATION_PATH_PATTERN)


def _normalize_chatgpt_url(value: str, path_pattern: re.Pattern[str]) -> str:
    candidate = str(value or "").strip()
    try:
        parsed = urlsplit(candidate)
    except ValueError:
        return ""
    if (
        parsed.scheme.lower() != "https"
        or (parsed.hostname or "").lower() not in CHATGPT_HOSTS
        or not path_pattern.fullmatch(parsed.path)
        or parsed.username
        or parsed.password
    ):
        return ""
    path = parsed.path.rstrip("/")
    return f"https://chatgpt.com{path}"


def _collect_sources(context: Any, page: Any, browser_label: str) -> dict[str, Any]:
    request_headers = _load_chatgpt_session_request_headers(context, CHATGPT_HOME_URL)
    api_headers = _chatgpt_api_request_headers(request_headers, CHATGPT_HOME_URL)
    return {
        "browser_label": browser_label,
        "recent_sessions": _collect_root_sessions(context, api_headers),
        "projects": _collect_projects(context, page, api_headers),
        "limit": AGENT_SOURCE_LIMIT,
    }


def _collect_root_sessions(context: Any, api_headers: dict[str, str]) -> list[dict[str, str]]:
    query = urlencode(
        {
            "offset": 0,
            "limit": CHATGPT_SOURCE_API_LIMIT,
            "order": "updated",
        }
    )
    payload = _get_chatgpt_api_json(
        context,
        f"https://chatgpt.com/backend-api/conversations?{query}",
        api_headers,
    )
    sessions: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for raw_item in _mapping_items(payload):
        if _has_project_marker(raw_item):
            continue
        session = _conversation_item(raw_item)
        session_id = session.get("id", "")
        if session_id and session_id not in seen_ids:
            seen_ids.add(session_id)
            sessions.append(session)
        if len(sessions) >= AGENT_SOURCE_LIMIT:
            break
    return sessions


def _collect_projects(
    context: Any,
    page: Any,
    api_headers: dict[str, str],
) -> list[dict[str, str]]:
    projects = _collect_projects_from_api(context, api_headers)
    if not projects:
        projects.extend(_collect_projects_from_page(page))
    deduplicated: dict[str, dict[str, str]] = {}
    for project in projects:
        project_url = project.get("url", "")
        if not project_url:
            continue
        existing = deduplicated.get(project_url)
        if existing is None or (not existing.get("title") and project.get("title")):
            deduplicated[project_url] = project
    ordered = list(deduplicated.values())
    if any(project.get("updated_at") for project in ordered):
        ordered.sort(key=lambda project: project.get("updated_at", ""), reverse=True)
    return ordered[:AGENT_SOURCE_LIMIT]


def _collect_projects_from_api(context: Any, api_headers: dict[str, str]) -> list[dict[str, str]]:
    for endpoint in CHATGPT_PROJECT_API_ENDPOINTS:
        try:
            payload = _get_chatgpt_api_json(
                context,
                f"https://chatgpt.com{endpoint}",
                api_headers,
            )
        except RuntimeError:
            continue
        projects = [project for item in _mapping_items(payload) if (project := _project_item(item))]
        if projects:
            return projects
    return []


def _collect_projects_from_page(page: Any) -> list[dict[str, str]]:
    try:
        rows = page.evaluate(
            """() => {
                const rows = Array.from(document.querySelectorAll('a[href], button[aria-label], [role="button"]'))
                    .map((element) => ({
                        href: element.href || element.getAttribute('href') || '',
                        title: (element.innerText || element.textContent || '').trim(),
                        aria: element.getAttribute('aria-label') || '',
                    }));
                for (const button of document.querySelectorAll('button[aria-label="Open project home"]')) {
                    const row = button.closest('li') || button.parentElement?.parentElement?.parentElement;
                    const label = row?.querySelector('[role="button"][data-sidebar-item="true"]');
                    const title = (label?.innerText || label?.textContent || '').trim();
                    if (title) rows.push({href: '', title, aria: 'Open project home'});
                }
                return rows;
            }"""
        )
    except Exception:
        return []
    if not isinstance(rows, list):
        return []
    projects: list[dict[str, str]] = []
    project_labels: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        project_url = normalize_chatgpt_project_url(str(row.get("href") or ""))
        if project_url:
            projects.append(
                {
                    "id": _chatgpt_project_id(project_url),
                    "title": str(row.get("title") or "").strip() or "Untitled project",
                    "url": project_url,
                    "updated_at": "",
                }
            )
            continue
        aria = str(row.get("aria") or "")
        project_match = re.fullmatch(r"Open project options for (.+)", aria, flags=re.IGNORECASE)
        if project_match:
            label = project_match.group(1).strip()
            if label and label not in project_labels:
                project_labels.append(label)

    for label in project_labels[:AGENT_SOURCE_LIMIT]:
        project_url = _open_project_from_sidebar(page, label)
        if project_url:
            projects.append(
                {
                    "id": _chatgpt_project_id(project_url),
                    "title": label,
                    "url": project_url,
                    "updated_at": "",
                }
            )
    return projects


def _open_project_from_sidebar(page: Any, label: str) -> str:
    """Resolve a project row to its canonical URL through the visible sidebar."""
    project_url = ""
    try:
        clicked = page.evaluate(
            """(projectLabel) => {
                const candidate = Array.from(document.querySelectorAll(
                    '[role="button"][data-sidebar-item="true"]'
                )).find((element) =>
                    (element.innerText || element.textContent || '').trim() === projectLabel
                );
                const row = candidate?.closest('li') || candidate?.parentElement?.parentElement?.parentElement;
                const homeButton = row?.querySelector('button[aria-label="Open project home"]');
                if (!homeButton) return false;
                homeButton.click();
                return true;
            }""",
            label,
        )
        if not clicked:
            return ""
        for _ in range(10):
            project_url = normalize_chatgpt_project_url(str(page.url or ""))
            if project_url:
                break
            page.wait_for_timeout(500)
    except Exception:
        project_url = ""
    finally:
        try:
            if project_url:
                page.goto(CHATGPT_HOME_URL, wait_until="domcontentloaded", timeout=90_000)
                page.wait_for_timeout(500)
        except Exception:
            pass
    return project_url


def _collect_project_sessions(context: Any, project_url: str) -> list[dict[str, str]]:
    project_id = _chatgpt_project_id(project_url)
    if not project_id:
        return []
    request_headers = _load_chatgpt_session_request_headers(context, project_url)
    api_headers = _chatgpt_api_request_headers(request_headers, project_url)
    query = urlencode({"cursor": 0, "limit": CHATGPT_PROJECT_API_LIMIT})
    payload = _get_chatgpt_api_json(
        context,
        f"https://chatgpt.com/backend-api/gizmos/{project_id}/conversations?{query}",
        api_headers,
    )
    prefix = _project_conversation_prefix(project_url)
    sessions: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for raw_item in _mapping_items(payload):
        session = _conversation_item(raw_item, url_prefix=prefix)
        session_id = session.get("id", "")
        if session_id and session_id not in seen_ids:
            seen_ids.add(session_id)
            sessions.append(session)
        if len(sessions) >= AGENT_SOURCE_LIMIT:
            break
    return sessions


def _mapping_items(payload: dict[str, Any]) -> Iterable[dict[str, Any]]:
    for key in ("items", "projects", "gizmos", "data"):
        value = payload.get(key)
        if isinstance(value, list):
            return (item for item in value if isinstance(item, dict))
    return ()


def _project_item(raw_item: dict[str, Any]) -> dict[str, str]:
    raw_item = _project_metadata(raw_item)
    display = raw_item.get("display") if isinstance(raw_item.get("display"), dict) else {}
    possible_urls = (
        raw_item.get("url"),
        raw_item.get("project_url"),
        raw_item.get("href"),
        raw_item.get("short_url"),
    )
    project_url = next(
        (
            normalized
            for value in possible_urls
            if (normalized := normalize_chatgpt_project_url(str(value or "")))
        ),
        "",
    )
    project_id = str(raw_item.get("id") or raw_item.get("project_id") or "").strip()
    if not project_url and project_id.startswith("g-p-"):
        short_url = str(raw_item.get("short_url") or "").strip().strip("/")
        slug = str(raw_item.get("slug") or "").strip().strip("/")
        project_segment = short_url if short_url.startswith("g-p-") else project_id
        if slug and slug != project_id and not slug.startswith("g-p-"):
            project_segment = f"{project_id}-{slug}"
        project_url = normalize_chatgpt_project_url(f"https://chatgpt.com/g/{project_segment}/project")
    if not project_url:
        return {}
    return {
        "id": _chatgpt_project_id(project_url) or project_id,
        "title": (
            _first_text(raw_item, "name", "title", "project_name")
            or _first_text(display, "name", "title")
            or "Untitled project"
        ),
        "url": project_url,
        "updated_at": _first_text(
            raw_item,
            "last_interacted_at",
            "updated_at",
            "update_time",
            "last_updated_at",
            "created_at",
        ),
    }


def _project_metadata(raw_item: dict[str, Any]) -> dict[str, Any]:
    """Unwrap the project record shapes returned by ChatGPT's sidebar APIs."""
    candidates = [raw_item]
    visited: set[int] = set()
    fallback = raw_item
    while candidates:
        candidate = candidates.pop(0)
        if id(candidate) in visited:
            continue
        visited.add(id(candidate))
        project_id = str(candidate.get("id") or candidate.get("project_id") or "").strip()
        if project_id.startswith("g-p-"):
            return candidate
        for key in ("gizmo", "resource", "project", "data"):
            nested = candidate.get(key)
            if isinstance(nested, dict):
                candidates.append(nested)
                fallback = nested
    return fallback


def _conversation_item(raw_item: dict[str, Any], url_prefix: str = "https://chatgpt.com/c/") -> dict[str, str]:
    conversation_id = str(
        raw_item.get("id") or raw_item.get("conversation_id") or raw_item.get("uuid") or ""
    ).strip()
    possible_urls = (raw_item.get("url"), raw_item.get("conversation_url"), raw_item.get("href"))
    conversation_url = next(
        (
            normalized
            for value in possible_urls
            if (normalized := normalize_chatgpt_conversation_url(str(value or "")))
        ),
        "",
    )
    if not conversation_url and conversation_id:
        conversation_url = f"{url_prefix}{conversation_id}"
    return {
        "id": conversation_id,
        "title": _first_text(raw_item, "title", "name") or "Untitled session",
        "url": conversation_url,
        "updated_at": _first_text(raw_item, "update_time", "updated_at", "last_updated_at", "create_time"),
    }


def _has_project_marker(raw_item: dict[str, Any]) -> bool:
    for key in ("project_id", "project_url", "gizmo_id", "gizmo_type"):
        value = raw_item.get(key)
        if value not in (None, "", False):
            return True
    return False


def _first_text(raw_item: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = raw_item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""
