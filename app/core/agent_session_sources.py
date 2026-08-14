"""Provider-neutral Web Agent Project and session discovery.

Code version: v1.1.0-codex.1
"""

from __future__ import annotations

from dataclasses import replace
import re
from typing import Any, Callable
from urllib.parse import urlsplit

from .browser_sessions import (
    browser_descriptors,
    goto_with_retry,
    launch_chromium_context,
    sync_playwright_or_error,
)
from .chatgpt_agent_sources import (
    list_chatgpt_agent_sources,
    list_chatgpt_project_sessions,
    normalize_chatgpt_conversation_url,
    normalize_chatgpt_project_url,
)
from .config import CrawlConfig
from .gemini_downloader import (
    GEMINI_HOME_URL,
    collect_gemini_conversation_links,
    normalize_gemini_conversation_url,
)
from .grok_history import GROK_HOME_URL, list_grok_conversations


AGENT_SOURCE_LIMIT = 20
SUPPORTED_AGENT_SOURCE_PLATFORMS = frozenset({"chatgpt", "gemini", "grok"})
AGENT_SOURCE_PLATFORM_LABELS = {
    "chatgpt": "ChatGPT",
    "gemini": "Gemini",
    "grok": "Grok",
}
GEMINI_HOSTS = frozenset({"gemini.google.com"})
GEMINI_PROJECT_PATH_PATTERN = re.compile(r"^/(?:app|notebook|notebooks)/[A-Za-z0-9_-]+/?$")
GROK_HOSTS = frozenset({"grok.com", "www.grok.com"})
GROK_CONVERSATION_PATH_PATTERN = re.compile(r"^/c/[A-Za-z0-9_-]+/?$")
GROK_PROJECT_PATH_PATTERN = re.compile(r"^/project/[A-Za-z0-9_-]+/?$")


def normalize_agent_conversation_url(platform: str, value: str) -> str:
    """Return one canonical conversation URL for a supported provider."""
    platform_key = str(platform or "").strip().lower()
    if platform_key == "chatgpt":
        return normalize_chatgpt_conversation_url(value)
    if platform_key == "gemini":
        return normalize_gemini_conversation_url(value)
    if platform_key == "grok":
        return normalize_grok_conversation_url(value)
    return ""


def normalize_agent_project_url(platform: str, value: str) -> str:
    """Return one canonical provider Project URL without exposing native names."""
    platform_key = str(platform or "").strip().lower()
    if platform_key == "chatgpt":
        return normalize_chatgpt_project_url(value)
    if platform_key == "gemini":
        # Gemini Notebooks open inside the same /app/<id> surface as a chat.
        return normalize_gemini_project_url(value)
    if platform_key == "grok":
        return normalize_grok_project_url(value)
    return ""


def normalize_gemini_project_url(value: str) -> str:
    """Return a canonical Gemini Notebook URL from the shared Project contract."""
    try:
        parsed = urlsplit(str(value or "").strip())
    except ValueError:
        return ""
    if (
        parsed.scheme.lower() != "https"
        or (parsed.hostname or "").lower() not in GEMINI_HOSTS
        or parsed.username
        or parsed.password
        or not GEMINI_PROJECT_PATH_PATTERN.fullmatch(parsed.path)
    ):
        return ""
    return f"https://gemini.google.com{parsed.path.rstrip('/')}"


def normalize_grok_conversation_url(value: str) -> str:
    """Return one canonical Grok conversation URL, or an empty string."""
    try:
        parsed = urlsplit(str(value or "").strip())
    except ValueError:
        return ""
    if (
        parsed.scheme.lower() != "https"
        or (parsed.hostname or "").lower() not in GROK_HOSTS
        or parsed.username
        or parsed.password
        or not GROK_CONVERSATION_PATH_PATTERN.fullmatch(parsed.path)
    ):
        return ""
    return f"https://grok.com{parsed.path.rstrip('/')}"


def normalize_grok_project_url(value: str) -> str:
    """Return a canonical Grok Project URL from the shared Project contract."""
    try:
        parsed = urlsplit(str(value or "").strip())
    except ValueError:
        return ""
    if (
        parsed.scheme.lower() != "https"
        or (parsed.hostname or "").lower() not in GROK_HOSTS
        or parsed.username
        or parsed.password
        or not GROK_PROJECT_PATH_PATTERN.fullmatch(parsed.path)
    ):
        return ""
    return f"https://grok.com{parsed.path.rstrip('/')}?tab=conversations"


def list_agent_sources(
    platform: str,
    browser_name: str,
    config: CrawlConfig,
) -> dict[str, Any]:
    """Return a shared recent-session payload for one provider and browser."""
    platform_key = str(platform or "").strip().lower()
    if platform_key not in SUPPORTED_AGENT_SOURCE_PLATFORMS:
        raise ValueError("Choose ChatGPT, Gemini, or Grok for the Web Agent.")

    if platform_key == "chatgpt":
        payload = dict(list_chatgpt_agent_sources(browser_name, config))
        payload["platform"] = platform_key
        return payload
    if platform_key == "gemini":
        return _list_gemini_agent_sources(browser_name, config)
    return _list_grok_agent_sources(browser_name, config)


def list_agent_project_sessions(
    platform: str,
    browser_name: str,
    project_url: str,
    config: CrawlConfig,
) -> dict[str, Any]:
    """Return sessions inside one provider Project through one shared contract."""
    platform_key = str(platform or "").strip().lower()
    if platform_key not in SUPPORTED_AGENT_SOURCE_PLATFORMS:
        raise ValueError("Choose ChatGPT, Gemini, or Grok for the Web Agent.")
    normalized_project_url = normalize_agent_project_url(platform_key, project_url)
    if not normalized_project_url:
        platform_label = AGENT_SOURCE_PLATFORM_LABELS[platform_key]
        raise ValueError(f"Choose a valid {platform_label} Project before loading its sessions.")
    if platform_key == "chatgpt":
        payload = dict(list_chatgpt_project_sessions(browser_name, normalized_project_url, config))
        payload["platform"] = platform_key
        return payload
    if platform_key == "gemini":
        return _list_gemini_project_sessions(browser_name, normalized_project_url, config)
    return _list_grok_project_sessions(browser_name, normalized_project_url, config)


def _list_gemini_agent_sources(browser_name: str, config: CrawlConfig) -> dict[str, Any]:
    """Collect Gemini's rendered recent-session links through the shared crawler."""
    capped_config = replace(
        config,
        gemini_max_conversations=min(
            AGENT_SOURCE_LIMIT,
            max(1, int(config.gemini_max_conversations)),
        ),
    )
    snapshot = _run_chromium_source_collection(
        browser_name,
        capped_config,
        GEMINI_HOME_URL,
        lambda page: _collect_gemini_sources(page, capped_config),
    )
    sessions = _normalize_session_rows("gemini", _snapshot_rows(snapshot, "recent_sessions"))
    projects = _snapshot_rows(snapshot, "projects")
    return {
        "platform": "gemini",
        "browser_label": _browser_label(browser_name, config),
        "recent_sessions": sessions,
        "projects": projects[:AGENT_SOURCE_LIMIT],
        "limit": AGENT_SOURCE_LIMIT,
    }


def _list_grok_agent_sources(browser_name: str, config: CrawlConfig) -> dict[str, Any]:
    """Collect Grok's recent root-level conversations from its authenticated API."""
    snapshot = _run_chromium_source_collection(
        browser_name,
        config,
        GROK_HOME_URL,
        _collect_grok_sources,
    )
    sessions = _normalize_session_rows("grok", _snapshot_rows(snapshot, "recent_sessions"))
    projects = _snapshot_rows(snapshot, "projects")
    return {
        "platform": "grok",
        "browser_label": _browser_label(browser_name, config),
        "recent_sessions": sessions,
        "projects": projects[:AGENT_SOURCE_LIMIT],
        "limit": AGENT_SOURCE_LIMIT,
    }


def _list_gemini_project_sessions(
    browser_name: str,
    project_url: str,
    config: CrawlConfig,
) -> dict[str, Any]:
    sessions = _run_chromium_source_collection(
        browser_name,
        config,
        project_url,
        lambda page: _read_gemini_project_session_links(page, project_url),
    )
    return {
        "platform": "gemini",
        "project_url": project_url,
        "sessions": sessions[:AGENT_SOURCE_LIMIT],
        "limit": AGENT_SOURCE_LIMIT,
    }


def _list_grok_project_sessions(
    browser_name: str,
    project_url: str,
    config: CrawlConfig,
) -> dict[str, Any]:
    sessions = _run_chromium_source_collection(
        browser_name,
        config,
        project_url,
        lambda page: _read_grok_project_session_links(page, project_url),
    )
    return {
        "platform": "grok",
        "project_url": project_url,
        "sessions": sessions[:AGENT_SOURCE_LIMIT],
        "limit": AGENT_SOURCE_LIMIT,
    }


def _collect_gemini_sources(page: Any, config: CrawlConfig) -> dict[str, Any]:
    """Reuse Gemini's history collector, then read Notebook links from its sidebar."""
    links = collect_gemini_conversation_links(page, config, lambda: False)
    return {
        "recent_sessions": links,
        "projects": _read_gemini_project_links(page),
    }


def _collect_grok_sources(page: Any) -> dict[str, Any]:
    """Reuse Grok's authenticated conversation API and read Project links from the page."""
    return {
        "recent_sessions": list_grok_conversations(page),
        "projects": _read_grok_project_links(page),
    }


def _read_gemini_project_links(page: Any) -> list[dict[str, str]]:
    """Read Notebook links without exposing Notebook as an Agent concept."""
    try:
        rows = page.evaluate(
            r"""() => {
                const textOf = (element) => [
                    element?.innerText,
                    element?.textContent,
                    element?.getAttribute?.('aria-label'),
                    element?.getAttribute?.('title'),
                ].filter(Boolean).join(' ').replace(/\s+/g, ' ').trim();
                const rows = [];
                for (const element of document.querySelectorAll('a[href], [role="link"]')) {
                    const rawHref = element.href || element.getAttribute('href') || '';
                    let url;
                    try { url = new URL(rawHref, location.href); } catch (_) { continue; }
                    if (url.protocol !== 'https:' || url.hostname !== 'gemini.google.com') continue;
                    const path = url.pathname.replace(/\/+$/, '');
                    const notebookPath = /^\/(?:notebook|notebooks)\/[A-Za-z0-9_-]+$/.test(path);
                    const appPath = /^\/app\/[A-Za-z0-9_-]+$/.test(path);
                    let parent = element;
                    const context = [];
                    for (let depth = 0; parent && depth < 8; depth += 1, parent = parent.parentElement) {
                        context.push(textOf(parent));
                        if (parent.tagName === 'NAV') break;
                    }
                    if (!notebookPath && !(appPath && /notebook/i.test(context.join(' ')))) continue;
                    rows.push({href: url.href, title: textOf(element)});
                }
                return rows;
            }"""
        )
    except Exception:
        return []
    return _normalize_project_rows("gemini", rows)


def _read_grok_project_links(page: Any) -> list[dict[str, str]]:
    """Read the Projects sidebar links from the authenticated Grok page."""
    try:
        rows = page.evaluate(
            r"""() => [...document.querySelectorAll('a[href], [role="link"]')].map((element) => ({
                href: element.href || element.getAttribute('href') || '',
                title: (element.innerText || element.textContent || element.getAttribute('aria-label') || '').trim(),
            }))"""
        )
    except Exception:
        return []
    return _normalize_project_rows("grok", rows)


def _read_gemini_project_session_links(page: Any, project_url: str) -> list[dict[str, str]]:
    return _read_project_session_links(page, "gemini", project_url)


def _read_grok_project_session_links(page: Any, project_url: str) -> list[dict[str, str]]:
    return _read_project_session_links(page, "grok", project_url)


def _read_project_session_links(page: Any, platform: str, project_url: str) -> list[dict[str, str]]:
    try:
        rows = page.evaluate(
            r"""() => [...document.querySelectorAll('a[href], [role="link"]')].map((element) => ({
                href: element.href || element.getAttribute('href') || '',
                title: (element.innerText || element.textContent || element.getAttribute('aria-label') || '').trim(),
            }))"""
        )
    except Exception:
        return []
    normalized_project = normalize_agent_project_url(platform, project_url) if project_url else ""
    sessions: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        raw_url = str(row.get("href") or "")
        normalized_url = normalize_agent_conversation_url(platform, raw_url)
        if not normalized_url or normalized_url == normalized_project or normalized_url in seen_urls:
            continue
        seen_urls.add(normalized_url)
        sessions.append(
            {
                "id": normalized_url.rsplit("/", 1)[-1],
                "title": str(row.get("title") or "").strip() or "Untitled session",
                "url": normalized_url,
                "updated_at": "",
            }
        )
    return sessions


def _normalize_project_rows(platform: str, rows: Any) -> list[dict[str, str]]:
    projects: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        normalized_url = normalize_agent_project_url(
            platform,
            str(row.get("href") or row.get("url") or ""),
        )
        if not normalized_url or normalized_url in seen_urls:
            continue
        seen_urls.add(normalized_url)
        projects.append(
            {
                "id": normalized_url.rstrip("/").split("/")[-1].split("?", 1)[0],
                "title": str(row.get("title") or "").strip() or "Untitled project",
                "url": normalized_url,
                "updated_at": str(row.get("updated_at") or "").strip(),
            }
        )
    return projects


def _snapshot_rows(snapshot: Any, key: str) -> list[Any]:
    """Read one adapter snapshot field while keeping old list-only collectors compatible."""
    if isinstance(snapshot, list):
        return snapshot if key == "recent_sessions" else []
    if not isinstance(snapshot, dict):
        return []
    rows = snapshot.get(key, [])
    return rows if isinstance(rows, list) else []


def _normalize_session_rows(platform: str, rows: list[Any]) -> list[dict[str, str]]:
    sessions: list[dict[str, str]] = []
    for row in rows:
        normalized_url = normalize_agent_conversation_url(platform, _item_value(row, "url"))
        if not normalized_url:
            continue
        sessions.append(
            {
                "id": _item_value(row, "conversation_id")
                or _item_value(row, "id")
                or normalized_url.rsplit("/", 1)[-1],
                "title": _item_value(row, "title") or "Untitled session",
                "url": normalized_url,
                "updated_at": _item_value(row, "updated_at"),
            }
        )
        if len(sessions) >= AGENT_SOURCE_LIMIT:
            break
    return sessions


def _item_value(item: Any, key: str) -> str:
    """Read dataclass and dictionary source rows through one small contract."""
    value = item.get(key) if isinstance(item, dict) else getattr(item, key, "")
    return str(value or "").strip()


def _browser_label(browser_name: str, config: CrawlConfig) -> str:
    """Resolve the selected browser label using the single browser registry."""
    descriptor = browser_descriptors(config).get(str(browser_name or "").strip().lower())
    if descriptor is None:
        raise ValueError(f"Unsupported browser: {browser_name}")
    return descriptor.label


def _run_chromium_source_collection(
    browser_name: str,
    config: CrawlConfig,
    home_url: str,
    collector: Callable[[Any], Any],
) -> Any:
    """Run one authenticated source collector in the selected Chromium profile."""
    descriptor = browser_descriptors(config).get(str(browser_name or "").strip().lower())
    if descriptor is None:
        raise ValueError(f"Unsupported browser: {browser_name}")
    if descriptor.engine != "chromium":
        raise ValueError(f"Gemini and Grok Agent sources require Edge or Chrome, not {descriptor.label}.")

    with sync_playwright_or_error() as playwright:
        with launch_chromium_context(
            playwright,
            descriptor,
            headless=False,
            clone_profile_first=True,
            background_window=True,
        ) as context:
            page = context.pages[0] if context.pages else context.new_page()
            goto_with_retry(page, home_url, attempts=2, timeout_ms=90_000)
            page.wait_for_timeout(500)
            return collector(page)
