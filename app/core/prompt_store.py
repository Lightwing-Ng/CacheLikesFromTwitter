"""Pointer-backed prompt bookmarks for the local resource browser."""

# Code version: v1.1.0-codex.1

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any, Iterable

from .chat_history_browser import (
    ChatHistoryMessage,
    find_chat_history_message,
    load_chat_history_messages,
    normalize_chat_history_source,
)
from .local_media_browser import LocalMediaPaginationItem, build_local_store_pagination
from .resource_persistence import (
    PROMPT_FILENAME,
    PROMPT_REMARKS_FILENAME,
    PROMPT_REMARKS_SCHEMA,
    PROMPT_REMARKS_SCHEMA_VERSION,
    PROMPT_SCHEMA,
    PROMPT_SCHEMA_VERSION,
    read_parquet_rows,
    write_parquet_rows_atomic,
)


PROMPT_STORE_DIRNAME = "prompt"
PROMPT_PAGE_SIZE = 24
PROMPT_REMARK_MAX_LENGTH = 48


@dataclass(frozen=True, slots=True)
class SavedPrompt:
    """Describe one prompt resolved from its cached message pointer."""

    stable_id: str
    source: str
    conversation_id: str
    message_key: str
    conversation_title: str
    conversation_url: str
    author_label: str
    content_text: str
    captured_at: str
    added_at: str
    remarks: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PromptPage:
    """Contain one filtered and paginated prompt-bookmark result."""

    items: tuple[SavedPrompt, ...]
    total_count: int
    current_page: int
    total_pages: int
    page_size: int = PROMPT_PAGE_SIZE

    @property
    def pagination_items(self) -> tuple[LocalMediaPaginationItem, ...]:
        """Reuse the local browser's compact pagination contract."""
        return build_local_store_pagination(self.total_pages, self.current_page)

    @property
    def pagination_active_index(self) -> int:
        """Return the zero-based index for the active pagination indicator."""
        for index, item in enumerate(self.pagination_items):
            if item.is_active:
                return index
        return 0


def prompt_pointer_key(source: str, conversation_id: str, message_key: str) -> str:
    """Return a deterministic, non-content key for one cached message pointer."""
    return "\x1f".join(
        (
            str(source or "").strip().lower(),
            str(conversation_id or "").strip(),
            str(message_key or "").strip(),
        )
    )


def _prompt_stable_id(pointer: str) -> str:
    """Return a stable browser identifier without persisting prompt content."""
    import hashlib

    digest = hashlib.sha256(pointer.encode("utf-8")).hexdigest()[:24]
    return f"prompt-{digest}"


def _timestamp_value(value: str) -> float:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return 0.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.timestamp()


class PromptStore:
    """Persist only message pointers and resolve prompt text from typed history."""

    def __init__(self, local_store_root: Path | str) -> None:
        self.local_store_root = Path(local_store_root).expanduser().resolve(strict=False)
        self.store_root = self.local_store_root / PROMPT_STORE_DIRNAME
        self.catalog_path = self.store_root / PROMPT_FILENAME
        self.remarks_path = self.store_root / PROMPT_REMARKS_FILENAME
        self._lock = RLock()
        self._entries = self._load_entries()
        self._remarks = self._load_remarks()

    def _load_entries(self) -> dict[str, dict[str, Any]]:
        entries: dict[str, dict[str, Any]] = {}
        for row in read_parquet_rows(self.catalog_path) or []:
            source = normalize_chat_history_source(str(row.get("source") or ""))
            conversation_id = str(row.get("conversation_id") or "").strip()[:160]
            message_key = str(row.get("message_key") or "").strip()[:240]
            if source == "all" or not conversation_id or not message_key:
                continue
            pointer = prompt_pointer_key(source, conversation_id, message_key)
            entries[pointer] = {
                "source": source,
                "conversation_id": conversation_id,
                "message_key": message_key,
                "added_at": str(row.get("added_at") or ""),
            }
        return entries

    def _load_remarks(self) -> dict[str, list[str]]:
        remarks: dict[str, list[str]] = {}
        for row in read_parquet_rows(self.remarks_path) or []:
            prompt_id = str(row.get("prompt_id") or "").strip()
            remark = self._normalize_remark(row.get("remark"))
            if not prompt_id or not remark:
                continue
            values = remarks.setdefault(prompt_id, [])
            if remark.casefold() not in {value.casefold() for value in values}:
                values.append(remark)
        return remarks

    @staticmethod
    def _normalize_remark(value: object) -> str:
        return " ".join(str(value or "").split())[:PROMPT_REMARK_MAX_LENGTH]

    def remark_options(self) -> tuple[str, ...]:
        """Return stored remarks for the shared prompt selector."""
        with self._lock:
            values = {
                remark
                for prompt_remarks in self._remarks.values()
                for remark in prompt_remarks
                if remark
            }
        return tuple(sorted(values, key=lambda value: (value.casefold(), value)))

    def _find_entry_for_stable_id(self, stable_id: str) -> tuple[str, dict[str, Any]]:
        normalized_id = str(stable_id or "").strip()
        for pointer, entry in self._entries.items():
            if _prompt_stable_id(pointer) == normalized_id:
                return pointer, entry
        raise LookupError("The saved prompt was not found.")

    def _resolve_stable_id(self, stable_id: str) -> tuple[str, dict[str, Any], ChatHistoryMessage]:
        pointer, entry = self._find_entry_for_stable_id(stable_id)
        message = find_chat_history_message(
            self.local_store_root,
            source=str(entry["source"]),
            conversation_id=str(entry["conversation_id"]),
            message_key=str(entry["message_key"]),
        )
        if message is None or message.role != "user":
            raise LookupError("The saved prompt is no longer available.")
        return pointer, entry, message

    def has_any(self) -> bool:
        """Return whether at least one pointer is saved, even if history is unavailable."""
        with self._lock:
            return bool(self._entries)

    def saved_pointer_keys(self) -> frozenset[str]:
        """Return the saved pointer keys for current-row action state."""
        with self._lock:
            return frozenset(self._entries)

    def add_pointer(
        self,
        *,
        source: str,
        conversation_id: str,
        message_key: str,
    ) -> tuple[SavedPrompt, bool]:
        """Save one message pointer once and return its current resolved content."""
        normalized_source = normalize_chat_history_source(source)
        normalized_conversation_id = str(conversation_id or "").strip()[:160]
        normalized_message_key = str(message_key or "").strip()[:240]
        if (
            normalized_source == "all"
            or not normalized_conversation_id
            or not normalized_message_key
        ):
            raise ValueError("A valid cached message pointer is required.")

        message = find_chat_history_message(
            self.local_store_root,
            source=normalized_source,
            conversation_id=normalized_conversation_id,
            message_key=normalized_message_key,
        )
        if message is None:
            raise LookupError("The cached message is no longer available.")
        if message.role != "user":
            raise ValueError("Only user messages can be saved as prompts.")

        pointer = prompt_pointer_key(
            normalized_source,
            normalized_conversation_id,
            normalized_message_key,
        )
        with self._lock:
            entry = self._entries.get(pointer)
            created = entry is None
            if entry is None:
                entry = {
                    "source": normalized_source,
                    "conversation_id": normalized_conversation_id,
                    "message_key": normalized_message_key,
                    "added_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                }
                self._entries[pointer] = entry
                self._save_entries()
            return self._build_item(entry, message), created

    def add_remark(self, stable_id: str, remark: object) -> tuple[SavedPrompt, bool]:
        """Add one normalized remark to a saved prompt."""
        normalized_remark = self._normalize_remark(remark)
        if not normalized_remark:
            raise ValueError("A remark is required.")
        with self._lock:
            pointer, entry, message = self._resolve_stable_id(stable_id)
            prompt_id = _prompt_stable_id(pointer)
            values = self._remarks.setdefault(prompt_id, [])
            created = not any(value.casefold() == normalized_remark.casefold() for value in values)
            if created:
                values.append(normalized_remark)
                self._save_remarks()
            return self._build_item(entry, message), created

    def remove_remark(self, stable_id: str, remark: object) -> SavedPrompt:
        """Remove one remark from a saved prompt."""
        normalized_remark = self._normalize_remark(remark)
        if not normalized_remark:
            raise ValueError("A remark is required.")
        with self._lock:
            pointer, entry, message = self._resolve_stable_id(stable_id)
            prompt_id = _prompt_stable_id(pointer)
            values = self._remarks.get(prompt_id, [])
            self._remarks[prompt_id] = [
                value for value in values if value.casefold() != normalized_remark.casefold()
            ]
            if self._remarks[prompt_id]:
                self._remarks = {key: value for key, value in self._remarks.items() if value}
            else:
                self._remarks.pop(prompt_id, None)
            self._save_remarks()
            return self._build_item(entry, message)

    def query(
        self,
        *,
        source: str = "all",
        query: str = "",
        sort: str = "newest",
        page: object = 1,
    ) -> PromptPage:
        """Resolve saved pointers against current history and return one page."""
        normalized_source = normalize_chat_history_source(source)
        query_terms = tuple(str(query or "").strip()[:120].casefold().split())
        with self._lock:
            entries = tuple(self._entries.items())
        messages = {
            prompt_pointer_key(message.source, message.conversation_id, message.message_key): message
            for message in load_chat_history_messages(self.local_store_root, normalized_source)
        }
        items: list[SavedPrompt] = []
        for pointer, entry in entries:
            if normalized_source != "all" and entry["source"] != normalized_source:
                continue
            message = messages.get(pointer)
            if message is None or message.role != "user":
                continue
            searchable = " ".join(
                (
                    message.conversation_title,
                    message.author_label,
                    message.content_text,
                    message.content_html,
                )
            ).casefold()
            if query_terms and not all(term in searchable for term in query_terms):
                continue
            items.append(self._build_item(entry, message))

        normalized_sort = str(sort or "").strip().lower()
        if normalized_sort == "name":
            items.sort(key=lambda item: (item.conversation_title.casefold(), item.content_text.casefold(), item.stable_id))
        else:
            direction = -1 if normalized_sort != "oldest" else 1
            items.sort(key=lambda item: (direction * _timestamp_value(item.added_at), item.stable_id))

        total_count = len(items)
        try:
            requested_page = max(1, int(page))
        except (TypeError, ValueError):
            requested_page = 1
        total_pages = max(1, (total_count + PROMPT_PAGE_SIZE - 1) // PROMPT_PAGE_SIZE)
        current_page = min(total_pages, requested_page)
        start = (current_page - 1) * PROMPT_PAGE_SIZE
        return PromptPage(
            items=tuple(items[start : start + PROMPT_PAGE_SIZE]),
            total_count=total_count,
            current_page=current_page,
            total_pages=total_pages,
        )

    def _build_item(self, entry: dict[str, Any], message: ChatHistoryMessage) -> SavedPrompt:
        pointer = prompt_pointer_key(
            str(entry["source"]),
            str(entry["conversation_id"]),
            str(entry["message_key"]),
        )
        return SavedPrompt(
            stable_id=_prompt_stable_id(pointer),
            source=message.source,
            conversation_id=message.conversation_id,
            message_key=message.message_key,
            conversation_title=message.conversation_title,
            conversation_url=message.conversation_url,
            author_label=message.author_label,
            content_text=message.content_text,
            captured_at=message.last_seen_at,
            added_at=str(entry.get("added_at") or ""),
            remarks=tuple(self._remarks.get(_prompt_stable_id(pointer), ())),
        )

    def _save_entries(self) -> None:
        rows: Iterable[dict[str, Any]] = (
            {
                "schema_version": PROMPT_SCHEMA_VERSION,
                "source": entry["source"],
                "conversation_id": entry["conversation_id"],
                "message_key": entry["message_key"],
                "added_at": entry["added_at"],
            }
            for _, entry in sorted(self._entries.items())
        )
        write_parquet_rows_atomic(self.catalog_path, rows, PROMPT_SCHEMA)

    def _save_remarks(self) -> None:
        rows: Iterable[dict[str, Any]] = (
            {
                "schema_version": PROMPT_REMARKS_SCHEMA_VERSION,
                "prompt_id": prompt_id,
                "remark": remark,
            }
            for prompt_id, values in sorted(self._remarks.items())
            for remark in sorted(values, key=lambda value: (value.casefold(), value))
        )
        write_parquet_rows_atomic(self.remarks_path, rows, PROMPT_REMARKS_SCHEMA)
