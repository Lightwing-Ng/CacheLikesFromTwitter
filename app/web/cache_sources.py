"""Presentation registry for cache source pages."""

# Code version: v1.0.0-codex.1

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True, slots=True)
class CacheSourceView:
    """Describe one cache source without coupling the shared page to its service."""

    key: str
    label: str
    view_endpoint: str
    template_name: str
    icon_filename: str
    document_title: str
    overview_title: str
    browser_panel_label: str
    browser_empty_message: str
    browser_config_field: str
    require_browser_ready: bool
    start_form_id: str
    start_button_label: str
    start_wait_title: str
    start_wait_copy: str
    stop_wait_title: str
    stop_wait_copy: str
    progress_strategy: str
    progress_aria_label: str
    banner_storage_key: str
    show_progress_audit: bool = False
    show_progress_value: bool = False
    show_progress_detail: bool = False

    @property
    def dock_label(self) -> str:
        """Return the source label used by the dock menu."""
        return f"{self.label} cache"

    @property
    def browser_input_id(self) -> str:
        """Return the hidden browser input identifier."""
        return f"{self.key}_browser_input"

    @property
    def browser_storage_key(self) -> str:
        """Return the session-scoped browser selection key."""
        return f"cachelikes:browser-selection:{self.key}"


_CACHE_SOURCE_VIEWS = (
    CacheSourceView(
        key="x",
        label="X",
        view_endpoint="index",
        template_name="index.html",
        icon_filename="images/x.svg",
        document_title="CacheLikesFromTwitter",
        overview_title="Execution overview",
        browser_panel_label="Browser",
        browser_empty_message="No signed-in account detected",
        browser_config_field="x_browser",
        require_browser_ready=False,
        start_form_id="start_form",
        start_button_label="Start caching",
        start_wait_title="Starting X cache",
        start_wait_copy="Preparing the signed-in X session and starting the local cache task.",
        stop_wait_title="Stopping X cache",
        stop_wait_copy="Requesting a safe stop for the active X cache task.",
        progress_strategy="discovery",
        progress_aria_label="Download progress",
        banner_storage_key="cachelikes:status-banner-dismissed",
    ),
    CacheSourceView(
        key="grok",
        label="Grok",
        view_endpoint="grok",
        template_name="grok.html",
        icon_filename="images/grok.svg",
        document_title="CacheLikesFromTwitter Grok",
        overview_title="Grok library overview",
        browser_panel_label="Browser",
        browser_empty_message="No signed-in account detected",
        browser_config_field="grok_browser",
        require_browser_ready=True,
        start_form_id="start_form_grok",
        start_button_label="Start sync",
        start_wait_title="Starting Grok sync",
        start_wait_copy="Preparing the selected browser session and starting the local Grok media sync.",
        stop_wait_title="Stopping Grok sync",
        stop_wait_copy="Requesting a safe stop for the active Grok sync.",
        progress_strategy="grok-audit",
        progress_aria_label="Grok sync progress",
        banner_storage_key="cachelikes:grok-status-banner-dismissed",
        show_progress_audit=True,
        show_progress_detail=True,
    ),
    CacheSourceView(
        key="chatgpt",
        label="ChatGPT",
        view_endpoint="chatgpt",
        template_name="chatgpt.html",
        icon_filename="images/ChatGPT-Logo.svg",
        document_title="CacheLikesFromTwitter ChatGPT",
        overview_title="ChatGPT cache overview",
        browser_panel_label="Authorized browser",
        browser_empty_message="No authorized project detected",
        browser_config_field="chatgpt_browser",
        require_browser_ready=True,
        start_form_id="start_form_chatgpt",
        start_button_label="Start sync",
        start_wait_title="Starting ChatGPT sync",
        start_wait_copy="Preparing the selected browser session and starting the original-resolution image sync.",
        stop_wait_title="Stopping ChatGPT sync",
        stop_wait_copy="Requesting a safe stop for the active ChatGPT sync.",
        progress_strategy="queue",
        progress_aria_label="ChatGPT sync progress",
        banner_storage_key="cachelikes:chatgpt-status-banner-dismissed",
        show_progress_audit=True,
        show_progress_value=True,
        show_progress_detail=True,
    ),
)


CACHE_SOURCE_VIEWS = tuple(sorted(_CACHE_SOURCE_VIEWS, key=lambda source: source.label.casefold()))
CACHE_SOURCE_BY_KEY = MappingProxyType({source.key: source for source in CACHE_SOURCE_VIEWS})


def get_cache_source_view(source_key: str) -> CacheSourceView | None:
    """Return one registered source using a normalized source key."""
    return CACHE_SOURCE_BY_KEY.get(str(source_key or "").strip().lower())


def get_cache_source_label(source_key: str) -> str:
    """Return a registered label with a safe title-cased fallback."""
    source = get_cache_source_view(source_key)
    return source.label if source is not None else str(source_key or "").title()
