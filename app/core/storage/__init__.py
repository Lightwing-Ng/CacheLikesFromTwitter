"""Durable local-resource boundary for catalogs, history, and backups."""

# Code version: v1.1.0-codex.1

from ..chat_history_browser import (
    attach_media_references,
    build_chat_history_markdown,
    format_chat_message_timestamp_label,
    query_chat_history,
)
from ..local_media_browser import (
    LocalMediaCatalog,
    format_captured_at_timestamp_label,
    local_file_manager_label,
    media_route_relative_path,
    normalize_browser_filters,
    reveal_media_path,
    resolve_browser_media_path,
    resolve_local_media_path,
)
from ..shadow_backup import (
    ShadowBackupError,
    ShadowBackupService,
    choose_settings_directory,
    choose_shadow_backup_destination,
)

__all__ = [
    "LocalMediaCatalog",
    "ShadowBackupError",
    "ShadowBackupService",
    "attach_media_references",
    "build_chat_history_markdown",
    "choose_settings_directory",
    "choose_shadow_backup_destination",
    "format_captured_at_timestamp_label",
    "format_chat_message_timestamp_label",
    "local_file_manager_label",
    "media_route_relative_path",
    "normalize_browser_filters",
    "query_chat_history",
    "resolve_browser_media_path",
    "resolve_local_media_path",
    "reveal_media_path",
]
