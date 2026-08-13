"""Read recent ChatGPT Web sessions and projects for the local Agent sidebar.

Code version: v1.0.0-codex.2
"""

from __future__ import annotations

from collections.abc import Iterable
import re
from typing import Any
from urllib.parse import urlencode, urlsplit

from .browser_sessions import (
    browser_descriptors,
    goto_with_retry,
    launch_chromium_context,
    sync_playwright_or_error,
)
from .chatgpt_downloader import (
    _chatgpt_api_request_headers,
    _chatgpt_project_id,
    _get_chatgpt_api_json,
    _load_chatgpt_session_request_headers,
    _project_conversation_prefix,
)
from .config import CrawlConfig
from .safari_automation import SafariContext


CHATGPT_HOME_URL = "https://chatgpt.com/"
CHATGPT_HOSTS = frozenset({"chatgpt.com", "www.chatgpt.com"})
AGENT_SOURCE_LIMIT = 20
CHATGPT_SOURCE_API_LIMIT = 100
CHATGPT_PROJECT_API_LIMIT = 20
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


def list_chatgpt_agent_sources(browser_name: str, config: CrawlConfig) -> dict[str, Any]:
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
        ) as context:
            page = context.pages[0] if context.pages else context.new_page()
            goto_with_retry(page, CHATGPT_HOME_URL, attempts=2, timeout_ms=90_000)
            page.wait_for_timeout(1_000)
            return _collect_sources(context, page, descriptor.label)


def list_chatgpt_project_sessions(
    browser_name: str,
    project_url: str,
    config: CrawlConfig,
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
            ) as context:
                page = context.pages[0] if context.pages else context.new_page()
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
