"""Provider-neutral X page identity and readiness helpers."""

# Code version: v1.0.0-codex.1

from __future__ import annotations

import re
from urllib.parse import urlparse


X_RESERVED_PATH_SEGMENTS = {
    "compose",
    "explore",
    "grok",
    "hashtag",
    "home",
    "i",
    "messages",
    "notifications",
    "search",
    "settings",
}
X_READY_SELECTORS = [
    "article",
    '[data-testid="emptyState"]',
    '[data-testid="primaryColumn"]',
    '[data-testid="cellInnerDiv"]',
    'a[href="/home"]',
    'a[data-testid="AppTabBar_Home_Link"]',
    'a[href$="/likes"]',
    'main[role="main"] [role="progressbar"]',
]


def extract_account_handle_from_urlish(value: str) -> str:
    """Extract an X account handle from an absolute URL or a path-like href."""
    candidate = (value or "").strip()
    if not candidate:
        return ""

    if candidate.startswith("/"):
        parsed = urlparse(f"https://x.com{candidate}")
    elif "://" in candidate:
        parsed = urlparse(candidate)
    else:
        parsed = urlparse(f"https://x.com/{candidate.lstrip('/')}")

    netloc = parsed.netloc.lower()
    if netloc and netloc not in {
        "x.com",
        "www.x.com",
        "twitter.com",
        "www.twitter.com",
        "mobile.x.com",
        "mobile.twitter.com",
    }:
        return ""

    path_parts = [part.strip() for part in parsed.path.split("/") if part.strip()]
    if not path_parts:
        return ""

    handle = path_parts[0].lstrip("@")
    if not handle or not re.fullmatch(r"[A-Za-z0-9_]{1,15}", handle):
        return ""
    if handle.lower() in X_RESERVED_PATH_SEGMENTS:
        return ""

    if len(path_parts) == 1:
        return handle
    if len(path_parts) >= 2 and path_parts[1].lower() in {"likes", "media", "with_replies"}:
        return handle
    return ""


def detect_account_handle(page) -> str:
    """Extract the current account handle from the profile tab link."""
    handle = extract_account_handle_from_urlish(page.url)
    if handle:
        return handle

    href_candidates = page.evaluate(
        """() => {
            const selectors = [
                'a[data-testid="AppTabBar_Profile_Link"]',
                'a[aria-label*="Profile"]',
                'a[href$="/likes"]',
                'a[href*="/likes"]',
                'a[href^="/"]',
                'link[rel="canonical"]',
                'meta[property="og:url"]',
            ];
            const values = [
                window.location.href,
                window.location.pathname,
            ];
            selectors.forEach((selector) => {
                document.querySelectorAll(selector).forEach((element) => {
                    if (element instanceof HTMLLinkElement) {
                        values.push(element.href || '');
                        return;
                    }
                    if (element instanceof HTMLMetaElement) {
                        values.push(element.content || '');
                        return;
                    }
                    values.push(element.getAttribute('href') || '');
                });
            });
            return Array.from(new Set(values.filter(Boolean)));
        }"""
    )
    for href in href_candidates:
        handle = extract_account_handle_from_urlish(str(href))
        if handle:
            return handle

    raise RuntimeError("Could not detect the current X account handle from Chrome.")


__all__ = ["X_READY_SELECTORS", "detect_account_handle", "extract_account_handle_from_urlish"]
