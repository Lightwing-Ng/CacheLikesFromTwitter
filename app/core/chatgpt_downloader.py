"""ChatGPT project image cache helpers."""

# Code version: v1.12.0-codex.1

from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import time
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from queue import Empty, Queue
from threading import RLock, Thread
from typing import Iterator
from urllib.parse import parse_qs, urlencode, urlsplit

from .browser_sessions import browser_descriptors, launch_chromium_context
from .config import (
    DEFAULT_CHATGPT_SCAN_WAIT_SECONDS,
    DEFAULT_CHATGPT_PROJECT_NAME,
    DEFAULT_CHATGPT_PROJECT_URL,
    DEFAULT_CHATGPT_STARTUP_TIMEOUT_SECONDS,
    LOCAL_STORE_ROOT,
    MAX_CHATGPT_SCAN_WAIT_SECONDS,
    MAX_CHATGPT_STARTUP_TIMEOUT_SECONDS,
    MIN_CHATGPT_SCAN_WAIT_SECONDS,
    MIN_CHATGPT_STARTUP_TIMEOUT_SECONDS,
    CrawlConfig,
)
from .local_media_browser import BrowserDeletionCatalog
from .state import TaskSnapshot, TaskState, utc_now

try:  # pragma: no cover - depends on the local runtime
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - exercised in environments without Playwright
    PlaywrightError = RuntimeError
    sync_playwright = None


CHATGPT_TARGET_DIR = LOCAL_STORE_ROOT / "chatgpt" / DEFAULT_CHATGPT_PROJECT_NAME
CHATGPT_CATALOG_FILENAME = ".chatgpt_catalog.json"
CHATGPT_PARTIAL_DIRNAME = ".chatgpt-partial"
CHATGPT_PAGE_GOTO_TIMEOUT_MS = 120_000
CHATGPT_IMAGE_TIMEOUT_MS = 60_000
CHATGPT_PROJECT_LOAD_ROUNDS = 64
CHATGPT_PROJECT_LINK_WAIT_ROUNDS = 30
CHATGPT_SCROLL_ROUNDS = 80
CHATGPT_SCAN_WAIT_SECONDS = DEFAULT_CHATGPT_SCAN_WAIT_SECONDS
CHATGPT_PROJECT_SCAN_WAIT_SECONDS = 2.0
CHATGPT_SCROLL_STEP_RATIO = 0.8
CHATGPT_PAGE_RECYCLE_INTERVAL = 25
CHATGPT_MAX_CONVERSATION_WORKERS = 3
CHATGPT_CONVERSATION_RESPONSE_WAIT_MS = 5_000
CHATGPT_RENDERED_IMAGE_WAIT_MS = 5_500
CHATGPT_RENDERED_IMAGE_POLL_MS = 250
CHATGPT_RENDERED_IMAGE_STABLE_ROUNDS = 3
CHATGPT_PROJECT_API_PAGE_SIZE = 10
CHATGPT_RECENT_IMAGE_PAGE_SIZE = 25
CHATGPT_API_PAGE_LIMIT = 1_000
CHATGPT_API_RETRY_LIMIT = 3
CHATGPT_API_RETRY_DELAY_SECONDS = 1.0
CHATGPT_RECOVERABLE_PAGE_ERROR_MARKERS = (
    "Page crashed",
    "frame was detached",
    "ERR_ABORTED",
    "ERR_SSL_BAD_RECORD_MAC_ALERT",
    "ERR_SSL_VERSION_OR_CIPHER_MISMATCH",
    "ERR_CONNECTION_RESET",
    "ERR_CONNECTION_CLOSED",
    "chrome-error://chromewebdata",
    "is interrupted by another navigation",
    "startup timed out",
)
CHATGPT_IMAGE_SUFFIXES = {".avif", ".gif", ".heic", ".jpeg", ".jpg", ".png", ".webp"}
CHATGPT_CONVERSATION_API_PATH = "/backend-api/conversation/"
CHATGPT_FILE_DOWNLOAD_PATH = "/backend-api/files/download/"
CHATGPT_DOWNLOAD_AUTH_HEADER_NAMES = {
    "authorization",
    "oai-client-version",
    "oai-device-id",
    "oai-language",
}
CHATGPT_FILE_ID_PATTERN = re.compile(r"file_[A-Za-z0-9_-]+")
CHATGPT_GIZMO_PROJECT_ID_PATTERN = re.compile(r"^(g-p-[0-9a-f]{32})(?:-|$)", re.IGNORECASE)


@dataclass(slots=True)
class ChatGPTImageCandidate:
    """Describe one original-resolution image found in a ChatGPT conversation."""

    source_url: str
    file_id: str
    conversation_url: str
    alt_text: str = ""
    width: int = 0
    height: int = 0
    message_role: str = ""
    conversation_title: str = ""
    request_headers: dict[str, str] = field(default_factory=dict, repr=False)


@dataclass(slots=True)
class ChatGPTCatalogEntry:
    """Persist the local mapping for one ChatGPT image file."""

    file_id: str
    relative_path: str
    content_sha256: str
    content_bytes: int
    source_url: str
    conversation_url: str
    alt_text: str
    width: int
    height: int
    first_seen_at: str
    last_seen_at: str
    conversation_title: str = ""


@dataclass(slots=True)
class ChatGPTSyncResult:
    """Capture the outcome of one ChatGPT project sync."""

    discovered_conversations: int = 0
    discovered_images: int = 0
    downloaded_count: int = 0
    skipped_known: int = 0
    failed_count: int = 0
    cached_count: int = 0
    stopped: bool = False


@dataclass(slots=True)
class ChatGPTConversationWorkResult:
    """Capture one conversation result produced by a parallel worker."""

    conversation_index: int
    conversation_url: str
    candidate_file_ids: tuple[str, ...] = ()
    downloaded_count: int = 0
    skipped_known: int = 0
    failed_count: int = 0
    error: str = ""
    image_errors: tuple[str, ...] = ()


@dataclass(slots=True)
class ChatGPTImageDownloadWorkResult:
    """Capture one direct image-index download outcome."""

    candidate_file_id: str
    downloaded: bool = False
    skipped: bool = False
    error: str = ""


@dataclass(slots=True)
class ChatGPTResetResult:
    """Describe what a ChatGPT cache reset removed."""

    removed_media_files: int = 0
    removed_state_files: int = 0
    removed_partial_files: int = 0


def write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    """Persist one JSON document atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f"{path.name}.tmp")
    temporary_path.write_text(json.dumps(payload, indent=2, sort_keys=True))
    os.replace(temporary_path, path)


def compute_sha256(content: bytes) -> str:
    """Return the SHA-256 digest for one byte payload."""
    return hashlib.sha256(content).hexdigest()


def sanitize_filename_part(value: str) -> str:
    """Convert an untrusted value into a stable filename fragment."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", (value or "").strip())
    return cleaned.strip("._-") or "image"


def chatgpt_target_dir(project_name: str = DEFAULT_CHATGPT_PROJECT_NAME) -> Path:
    """Return the dedicated local directory for one ChatGPT project."""
    return LOCAL_STORE_ROOT / "chatgpt" / sanitize_filename_part(project_name)


def extract_chatgpt_file_id(source_url: str) -> str:
    """Extract the stable file ID from a ChatGPT content URL."""
    query = parse_qs(urlsplit(source_url).query)
    file_id = str((query.get("id") or [""])[0]).strip()
    if file_id:
        return file_id

    digest = hashlib.sha1(source_url.encode("utf-8")).hexdigest()
    return f"url-{digest}"


def image_signature_extension(content: bytes) -> str:
    """Return the suffix implied by an image signature, or an empty string."""
    if content.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if content.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if len(content) >= 12 and content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        return ".webp"
    if len(content) >= 12 and content[4:8] == b"ftyp" and content[8:12] in {b"avif", b"avis"}:
        return ".avif"
    if len(content) >= 12 and content[4:8] == b"ftyp" and content[8:12] in {b"heic", b"heix"}:
        return ".heic"
    return ""


def infer_image_extension(source_url: str, content_type: str, content: bytes = b"") -> str:
    """Choose a local suffix from the response type or source URL."""
    signature_extension = image_signature_extension(content)
    if signature_extension:
        return signature_extension

    normalized_type = (content_type or "").split(";", 1)[0].strip().lower()
    extension = mimetypes.guess_extension(normalized_type) if normalized_type else None
    if extension == ".jpe":
        extension = ".jpg"
    if extension and extension.lower() in CHATGPT_IMAGE_SUFFIXES:
        return extension.lower()

    suffix = Path(urlsplit(source_url).path).suffix.lower()
    return suffix if suffix in CHATGPT_IMAGE_SUFFIXES else ".png"


def looks_like_image(content: bytes) -> bool:
    """Validate common raster-image signatures without decoding the image."""
    return bool(image_signature_extension(content))


def should_cache_chatgpt_candidate(candidate: ChatGPTImageCandidate) -> bool:
    """Return whether a ChatGPT original-image candidate can be cached."""
    return bool(candidate.source_url.strip() and candidate.file_id.strip())


class ChatGPTImageCatalog:
    """Durable catalog for the dedicated ChatGPT project cache directory."""

    def __init__(self, target_dir: Path, entries: dict[str, ChatGPTCatalogEntry] | None = None) -> None:
        self.target_dir = target_dir
        self.catalog_path = target_dir / CHATGPT_CATALOG_FILENAME
        self.entries_by_file_id = entries or {}
        self._lock = RLock()
        self._in_flight_file_ids: set[str] = set()
        self._unavailable_file_ids: set[str] = set()

    @classmethod
    def build(cls, target_dir: Path = CHATGPT_TARGET_DIR) -> "ChatGPTImageCatalog":
        """Load a catalog, tolerating a missing or partially written state file."""
        catalog_path = target_dir / CHATGPT_CATALOG_FILENAME
        entries: dict[str, ChatGPTCatalogEntry] = {}
        if catalog_path.exists():
            try:
                payload = json.loads(catalog_path.read_text())
            except (OSError, json.JSONDecodeError):
                payload = {}
            raw_entries = payload.get("entries", {}) if isinstance(payload, dict) else {}
            if isinstance(raw_entries, dict):
                for raw_file_id, raw_entry in raw_entries.items():
                    if not isinstance(raw_entry, dict):
                        continue
                    try:
                        entry = ChatGPTCatalogEntry(
                            file_id=str(raw_entry.get("file_id") or raw_file_id),
                            relative_path=str(raw_entry.get("relative_path") or ""),
                            content_sha256=str(raw_entry.get("content_sha256") or ""),
                            content_bytes=int(raw_entry.get("content_bytes") or 0),
                            source_url=str(raw_entry.get("source_url") or ""),
                            conversation_url=str(raw_entry.get("conversation_url") or ""),
                            alt_text=str(raw_entry.get("alt_text") or ""),
                            width=int(raw_entry.get("width") or 0),
                            height=int(raw_entry.get("height") or 0),
                            first_seen_at=str(raw_entry.get("first_seen_at") or ""),
                            last_seen_at=str(raw_entry.get("last_seen_at") or ""),
                            conversation_title=str(raw_entry.get("conversation_title") or ""),
                        )
                    except (TypeError, ValueError):
                        continue
                    if entry.file_id and entry.relative_path:
                        entries[entry.file_id] = entry
        catalog = cls(target_dir, entries)
        catalog._normalize_file_extensions()
        return catalog

    def _normalize_file_extensions(self) -> None:
        """Correct legacy filenames when a server reports the wrong media type."""
        changed = False
        for entry in self.entries_by_file_id.values():
            path = self.target_dir / entry.relative_path
            if not path.is_file():
                continue
            try:
                with path.open("rb") as handle:
                    signature = handle.read(64)
            except OSError:
                continue
            expected_suffix = image_signature_extension(signature)
            if not expected_suffix or path.suffix.lower() == expected_suffix:
                continue
            corrected_path = path.with_suffix(expected_suffix)
            if corrected_path.exists():
                continue
            try:
                path.rename(corrected_path)
            except OSError:
                continue
            entry.relative_path = corrected_path.relative_to(self.target_dir).as_posix()
            changed = True

        if changed:
            self.save()

    def save(self) -> None:
        """Write the current catalog to disk."""
        with self._lock:
            write_json_atomic(
                self.catalog_path,
                {
                    "version": 1,
                    "entries": {file_id: asdict(entry) for file_id, entry in self.entries_by_file_id.items()},
                },
            )

    def complete_entry(self, file_id: str) -> ChatGPTCatalogEntry | None:
        """Return a catalog entry only when its local file is still valid."""
        with self._lock:
            entry = self.entries_by_file_id.get(file_id)
            if entry is None:
                return None
            path = self.target_dir / entry.relative_path
            if not path.exists() or not path.is_file() or path.stat().st_size <= 0:
                return None
            if entry.content_bytes and path.stat().st_size != entry.content_bytes:
                return None
            try:
                with path.open("rb") as handle:
                    signature = handle.read(64)
                if not looks_like_image(signature):
                    return None
            except OSError:
                return None
            return entry

    def claim_download(self, file_id: str) -> bool:
        """Claim one file ID so parallel workers do not download it twice."""
        with self._lock:
            if (
                file_id in self._unavailable_file_ids
                or file_id in self._in_flight_file_ids
                or self.complete_entry(file_id) is not None
            ):
                return False
            self._in_flight_file_ids.add(file_id)
            return True

    def release_download(self, file_id: str) -> None:
        """Release a failed or interrupted parallel download claim."""
        with self._lock:
            self._in_flight_file_ids.discard(file_id)

    def mark_unavailable(self, file_id: str) -> None:
        """Remember a missing historical file only for the current sync run."""
        with self._lock:
            self._in_flight_file_ids.discard(file_id)
            self._unavailable_file_ids.add(file_id)

    def update_metadata(self, candidate: ChatGPTImageCandidate) -> None:
        """Refresh conversation metadata when a known image is seen again."""
        with self._lock:
            existing = self.entries_by_file_id.get(candidate.file_id)
            if existing is None or not candidate.conversation_title:
                return
            if candidate.conversation_title == existing.conversation_title:
                return
            existing.conversation_title = candidate.conversation_title
            existing.conversation_url = candidate.conversation_url
            self.save()

    def summarize(self) -> int:
        """Return the number of cataloged images whose files still exist."""
        with self._lock:
            return sum(1 for file_id in self.entries_by_file_id if self.complete_entry(file_id) is not None)

    def register_download(
        self,
        candidate: ChatGPTImageCandidate,
        relative_path: str,
        content_sha256: str,
        content_bytes: int,
        seen_at: str,
    ) -> None:
        """Register one successfully downloaded image and persist immediately."""
        with self._lock:
            existing = self.entries_by_file_id.get(candidate.file_id)
            self.entries_by_file_id[candidate.file_id] = ChatGPTCatalogEntry(
                file_id=candidate.file_id,
                relative_path=relative_path,
                content_sha256=content_sha256,
                content_bytes=content_bytes,
                source_url=candidate.source_url,
                conversation_url=candidate.conversation_url,
                alt_text=candidate.alt_text,
                width=candidate.width,
                height=candidate.height,
                first_seen_at=existing.first_seen_at if existing else seen_at,
                last_seen_at=seen_at,
                conversation_title=candidate.conversation_title
                or (existing.conversation_title if existing else ""),
            )
            self._in_flight_file_ids.discard(candidate.file_id)
            self.save()


def build_chatgpt_initial_snapshot(
    version: str,
    target_dir: Path | None = None,
    project_name: str = DEFAULT_CHATGPT_PROJECT_NAME,
) -> TaskSnapshot:
    """Hydrate the ChatGPT idle snapshot from the local image catalog."""
    resolved_target_dir = target_dir or chatgpt_target_dir(project_name)
    snapshot = TaskSnapshot(version=version)
    cached_count = ChatGPTImageCatalog.build(resolved_target_dir).summarize()
    snapshot.account_name = project_name
    snapshot.output_dir = str(resolved_target_dir)
    snapshot.discovered_images = cached_count
    snapshot.downloaded_posts = cached_count
    snapshot.downloaded_tweets = cached_count
    snapshot.downloaded_images = cached_count
    if cached_count:
        snapshot.message = f"Ready. Found existing ChatGPT cache: {cached_count:,} images."
    return snapshot


def reset_chatgpt_state(
    target_dir: Path | None = None,
    project_name: str = DEFAULT_CHATGPT_PROJECT_NAME,
) -> ChatGPTResetResult:
    """Remove only the dedicated ChatGPT cache and its resumable state."""
    resolved_target_dir = target_dir or chatgpt_target_dir(project_name)
    result = ChatGPTResetResult()
    catalog_path = resolved_target_dir / CHATGPT_CATALOG_FILENAME
    catalog = ChatGPTImageCatalog.build(resolved_target_dir)
    for entry in catalog.entries_by_file_id.values():
        media_path = resolved_target_dir / entry.relative_path
        if media_path.exists() and media_path.is_file():
            media_path.unlink()
            result.removed_media_files += 1

    partial_dir = resolved_target_dir / CHATGPT_PARTIAL_DIRNAME
    if partial_dir.exists():
        for partial_path in partial_dir.iterdir():
            if partial_path.is_file():
                partial_path.unlink()
                result.removed_partial_files += 1
        partial_dir.rmdir()

    if catalog_path.exists():
        catalog_path.unlink()
        result.removed_state_files += 1
    return result


def _project_conversation_prefix(project_url: str) -> str:
    """Build the URL prefix used by ChatGPT project conversation links."""
    parsed = urlsplit(project_url)
    project_path = parsed.path.rstrip("/")
    if project_path.endswith("/project"):
        project_path = project_path[: -len("/project")]
    return f"{parsed.scheme}://{parsed.netloc}{project_path}/c/"


def is_chatgpt_conversation_url(url: str) -> bool:
    """Return whether a ChatGPT URL points to one conversation session."""
    parsed = urlsplit(url)
    path_parts = [part for part in parsed.path.split("/") if part]
    return (
        parsed.scheme.lower() == "https"
        and parsed.netloc.lower() == "chatgpt.com"
        and len(path_parts) >= 2
        and path_parts[-2] == "c"
        and bool(path_parts[-1])
    )


def _chatgpt_conversation_id(conversation_url: str) -> str:
    """Return the stable conversation ID from one ChatGPT conversation URL."""
    parsed = urlsplit(conversation_url)
    path_parts = [part for part in parsed.path.split("/") if part]
    if len(path_parts) >= 2 and path_parts[-2] == "c":
        return path_parts[-1]
    return ""


def _chatgpt_conversation_api_url(conversation_url: str) -> str:
    """Build the authenticated API endpoint for one ChatGPT conversation."""
    parsed = urlsplit(conversation_url)
    conversation_id = _chatgpt_conversation_id(conversation_url)
    if not conversation_id or parsed.scheme.lower() != "https" or parsed.netloc.lower() != "chatgpt.com":
        return ""
    return f"{parsed.scheme}://{parsed.netloc}{CHATGPT_CONVERSATION_API_PATH}{conversation_id}"


def _chatgpt_file_download_url(file_id: str, conversation_url: str = "") -> str:
    """Build the authenticated metadata endpoint for one ChatGPT file asset."""
    source_url = f"https://chatgpt.com{CHATGPT_FILE_DOWNLOAD_PATH}{file_id}"
    conversation_id = _chatgpt_conversation_id(conversation_url)
    if not conversation_id:
        return source_url
    return f"{source_url}?{urlencode({
        'conversation_id': conversation_id,
        'download_intent': 'false',
        'inline': 'false',
    })}"


def _is_chatgpt_file_download_url(source_url: str) -> bool:
    """Return whether a source URL needs authenticated download URL resolution."""
    parsed = urlsplit(source_url)
    return (
        parsed.scheme.lower() == "https"
        and parsed.netloc.lower() == "chatgpt.com"
        and parsed.path.startswith(CHATGPT_FILE_DOWNLOAD_PATH)
    )


def _extract_chatgpt_file_id_from_asset_pointer(value: object) -> str:
    """Extract a file ID from one ChatGPT file-service asset pointer."""
    match = CHATGPT_FILE_ID_PATTERN.search(str(value or ""))
    return match.group(0) if match else ""


def _chatgpt_candidate_request_headers(response) -> dict[str, str]:
    """Keep the page's transient ChatGPT authorization headers in memory only."""
    try:
        request_headers = response.request.headers
    except (AttributeError, PlaywrightError):
        return {}
    if not isinstance(request_headers, dict):
        return {}
    return {
        str(key): str(value)
        for key, value in request_headers.items()
        if str(key).lower() in CHATGPT_DOWNLOAD_AUTH_HEADER_NAMES and str(value)
    }


def _chatgpt_project_id(project_url: str) -> str:
    """Extract the GPT project identifier from one ChatGPT project URL."""
    path_parts = [part for part in urlsplit(project_url).path.split("/") if part]
    for index, part in enumerate(path_parts[:-1]):
        if part == "g":
            project_segment = path_parts[index + 1]
            match = CHATGPT_GIZMO_PROJECT_ID_PATTERN.match(project_segment)
            return match.group(1) if match else project_segment
    return ""


def _chatgpt_api_request_headers(request_headers: dict[str, str], referer: str) -> dict[str, str]:
    """Build one in-memory authenticated JSON request header set."""
    headers = {
        str(key): str(value)
        for key, value in request_headers.items()
        if str(key).lower() in CHATGPT_DOWNLOAD_AUTH_HEADER_NAMES and str(value)
    }
    headers.update({"Accept": "application/json", "Referer": referer})
    return headers


def _get_chatgpt_api_json(context, url: str, headers: dict[str, str]) -> dict[str, object]:
    """Fetch one authenticated ChatGPT JSON response with a small rate-limit retry budget."""
    last_status = 0
    for attempt_index in range(CHATGPT_API_RETRY_LIMIT):
        response = context.request.get(
            url,
            timeout=CHATGPT_IMAGE_TIMEOUT_MS,
            headers=headers,
        )
        last_status = int(response.status)
        if response.ok:
            try:
                payload = json.loads(response.text())
            except (AttributeError, TypeError, json.JSONDecodeError) as exc:
                raise RuntimeError("ChatGPT API returned invalid JSON.") from exc
            if isinstance(payload, dict):
                return payload
            raise RuntimeError("ChatGPT API returned an unexpected JSON payload.")
        if last_status != 429 or attempt_index + 1 >= CHATGPT_API_RETRY_LIMIT:
            break
        time.sleep(CHATGPT_API_RETRY_DELAY_SECONDS * (attempt_index + 1))
    raise RuntimeError(f"ChatGPT API request returned HTTP {last_status}.")


def _extract_chatgpt_conversation_image_payloads(payload: object) -> list[dict[str, object]]:
    """Extract every current-branch image asset from a complete ChatGPT conversation mapping."""
    if not isinstance(payload, dict):
        return []
    mapping = payload.get("mapping")
    if not isinstance(mapping, dict):
        return []

    current_node = str(payload.get("current_node") or "").strip()
    current_branch_node_ids: set[str] = set()
    node_id = current_node
    while node_id and node_id not in current_branch_node_ids:
        node = mapping.get(node_id)
        if not isinstance(node, dict):
            break
        current_branch_node_ids.add(node_id)
        node_id = str(node.get("parent") or "").strip()
    nodes_to_scan = (
        (mapping[node_id] for node_id in current_branch_node_ids)
        if current_branch_node_ids
        else mapping.values()
    )

    results_by_file_id: dict[str, dict[str, object]] = {}

    def as_integer(value: object) -> int:
        try:
            return max(0, int(value or 0))
        except (TypeError, ValueError):
            return 0

    def walk_asset(value: object, message_role: str) -> None:
        if isinstance(value, list):
            for child in value:
                walk_asset(child, message_role)
            return
        if not isinstance(value, dict):
            return

        pointer = value.get("asset_pointer") or value.get("image_asset_pointer")
        pointer_text = str(pointer or "").strip()
        file_id = _extract_chatgpt_file_id_from_asset_pointer(pointer_text)
        content_type = str(
            value.get("content_type")
            or value.get("contentType")
            or value.get("mime_type")
            or value.get("mimeType")
            or ""
        ).strip().lower()
        file_name = str(value.get("file_name") or value.get("filename") or value.get("name") or "")
        is_image = (
            content_type.startswith("image/")
            or content_type == "image_asset_pointer"
            or bool(value.get("image_asset_pointer"))
            or Path(file_name).suffix.lower() in CHATGPT_IMAGE_SUFFIXES
        )
        if file_id and is_image and not pointer_text.lower().startswith("sediment://"):
            candidate = {
                "fileId": file_id,
                "altText": str(value.get("alt_text") or value.get("alt") or file_name).strip(),
                "width": as_integer(value.get("width")),
                "height": as_integer(value.get("height")),
                "messageRole": message_role,
            }
            previous = results_by_file_id.get(file_id)
            if previous is None or (
                int(candidate["width"]) * int(candidate["height"])
                >= int(previous.get("width") or 0) * int(previous.get("height") or 0)
            ):
                results_by_file_id[file_id] = candidate

        for child in value.values():
            walk_asset(child, message_role)

    for node in nodes_to_scan:
        if not isinstance(node, dict):
            continue
        message = node.get("message")
        if not isinstance(message, dict):
            continue
        author = message.get("author")
        message_role = str(author.get("role") or "") if isinstance(author, dict) else ""
        walk_asset(message.get("content"), message_role)

    return list(results_by_file_id.values())


def _extract_project_links(page, project_url: str) -> list[str]:
    """Read currently rendered conversation links from the project page."""
    prefix = _project_conversation_prefix(project_url)
    return page.evaluate(
        """(prefix) => [...new Set([...document.querySelectorAll('a[href]')]
            .map((anchor) => anchor.href)
            .filter((href) => href.startsWith(prefix)))]""",
        prefix,
    )


def _click_load_more_conversations(page) -> bool:
    """Ask ChatGPT's project list to render the next conversation page."""
    return bool(
        page.evaluate(
            """() => {
                const button = [...document.querySelectorAll('button')].find((candidate) =>
                    (candidate.innerText || '').replace(/\\s+/g, ' ').trim() === 'Load more conversations'
                );
                if (!button) {
                    return false;
                }
                button.scrollIntoView({ block: 'center' });
                button.click();
                return true;
            }"""
        )
    )


def _has_load_more_conversations(page) -> bool:
    """Return whether ChatGPT currently exposes project pagination."""
    return bool(
        page.evaluate(
            """() => [...document.querySelectorAll('button')].some((candidate) =>
                (candidate.innerText || '').replace(/\\s+/g, ' ').trim() === 'Load more conversations'
            )"""
        )
    )


def _wait_for_project_conversation_links(
    page,
    project_url: str,
    should_stop,
    startup_timeout_seconds: float = DEFAULT_CHATGPT_STARTUP_TIMEOUT_SECONDS,
    scan_wait_seconds: float = CHATGPT_SCAN_WAIT_SECONDS,
) -> list[str]:
    """Wait for the project list to finish its initial asynchronous rendering."""
    previous_count = 0
    stable_rounds = 0
    current_links: list[str] = []
    timeout_seconds = min(
        max(float(startup_timeout_seconds), MIN_CHATGPT_STARTUP_TIMEOUT_SECONDS),
        MAX_CHATGPT_STARTUP_TIMEOUT_SECONDS,
    )
    poll_seconds = min(max(float(scan_wait_seconds), MIN_CHATGPT_SCAN_WAIT_SECONDS), timeout_seconds)
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if should_stop():
            return []
        current_links = _extract_project_links(page, project_url)
        if current_links and _has_load_more_conversations(page):
            return current_links
        if current_links and len(current_links) == previous_count:
            stable_rounds += 1
        else:
            stable_rounds = 0
        if current_links and stable_rounds >= 3:
            return current_links
        previous_count = len(current_links)
        remaining_seconds = max(0.05, deadline - time.monotonic())
        page.wait_for_timeout(int(min(poll_seconds, remaining_seconds) * 1_000))
    if current_links:
        return current_links
    raise RuntimeError(
        f"ChatGPT project loaded without any conversation links after {timeout_seconds:g} seconds. "
        "The authorized Edge session may need to finish loading the project first."
    )


def open_chatgpt_page(
    page,
    url: str,
    settle_ms: int = 2_500,
    startup_timeout_seconds: float | None = None,
) -> None:
    """Open a ChatGPT page and tolerate its long-lived application requests."""
    timeout_seconds = startup_timeout_seconds or CHATGPT_PAGE_GOTO_TIMEOUT_MS / 1_000
    timeout_seconds = min(
        max(float(timeout_seconds), MIN_CHATGPT_STARTUP_TIMEOUT_SECONDS),
        MAX_CHATGPT_STARTUP_TIMEOUT_SECONDS,
    )
    deadline = time.monotonic() + timeout_seconds
    navigation_timeout_ms = min(CHATGPT_PAGE_GOTO_TIMEOUT_MS, int(timeout_seconds * 1_000))
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=navigation_timeout_ms)
    except PlaywrightError as exc:
        if time.monotonic() >= deadline:
            raise RuntimeError(
                f"ChatGPT startup timed out after {timeout_seconds:g} seconds while opening the page."
            ) from exc
        raise
    for _ in range(30):
        if time.monotonic() >= deadline:
            raise RuntimeError(
                f"ChatGPT startup timed out after {timeout_seconds:g} seconds while waiting for the page."
            )
        title = page.title().lower()
        remaining_ms = max(100, int((deadline - time.monotonic()) * 1_000))
        body_text = page.locator("body").inner_text(timeout=min(15_000, remaining_ms))[:500].lower()
        if "just a moment" not in title and "checking your browser" not in body_text:
            break
        page.wait_for_timeout(min(1_000, remaining_ms))
    else:
        raise RuntimeError(
            f"ChatGPT startup timed out after {timeout_seconds:g} seconds on a security verification page."
        )
    if settle_ms > 0:
        remaining_ms = max(0, int((deadline - time.monotonic()) * 1_000))
        if remaining_ms:
            page.wait_for_timeout(min(settle_ms, remaining_ms))


def _listen_for_chatgpt_request_headers(page, request_headers: dict[str, str]):
    """Capture the active browser authorization headers without persisting them."""
    add_listener = getattr(page, "on", None)
    if not callable(add_listener):
        return None

    def capture(response) -> None:
        captured_headers = _chatgpt_candidate_request_headers(response)
        if captured_headers:
            request_headers.update(captured_headers)

    add_listener("response", capture)
    return capture


def _stop_listening_for_chatgpt_response(page, listener) -> None:
    """Detach one temporary ChatGPT response listener."""
    if listener is None:
        return
    remove_listener = getattr(page, "remove_listener", None)
    if not callable(remove_listener):
        return
    try:
        remove_listener("response", listener)
    except PlaywrightError:
        pass


def _wait_for_chatgpt_request_headers(page, request_headers: dict[str, str]) -> None:
    """Wait briefly for the authenticated ChatGPT page to issue one API request."""
    deadline = time.monotonic() + CHATGPT_CONVERSATION_RESPONSE_WAIT_MS / 1_000
    while not request_headers and time.monotonic() < deadline:
        page.wait_for_timeout(200)


def _collect_project_conversation_urls_via_api(
    context,
    project_url: str,
    request_headers: dict[str, str],
    state: TaskState,
    should_stop,
) -> list[str]:
    """Load every project conversation through ChatGPT's paginated project API."""
    project_id = _chatgpt_project_id(project_url)
    if not project_id or not request_headers:
        return []

    api_headers = _chatgpt_api_request_headers(request_headers, project_url)
    conversation_prefix = _project_conversation_prefix(project_url)
    conversation_urls: list[str] = []
    seen_ids: set[str] = set()
    seen_cursors: set[str] = set()
    cursor = "0"
    for page_index in range(CHATGPT_API_PAGE_LIMIT):
        if should_stop() or not cursor or cursor in seen_cursors:
            break
        seen_cursors.add(cursor)
        query = urlencode({"cursor": cursor, "limit": CHATGPT_PROJECT_API_PAGE_SIZE})
        payload = _get_chatgpt_api_json(
            context,
            f"https://chatgpt.com/backend-api/gizmos/{project_id}/conversations?{query}",
            api_headers,
        )
        raw_items = payload.get("items")
        if not isinstance(raw_items, list):
            break
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                continue
            conversation_id = str(raw_item.get("id") or raw_item.get("conversation_id") or "").strip()
            if conversation_id and conversation_id not in seen_ids:
                seen_ids.add(conversation_id)
                conversation_urls.append(f"{conversation_prefix}{conversation_id}")
        state.append_event(
            f"ChatGPT project API loaded {len(conversation_urls):,} conversations after page {page_index + 1}."
        )
        cursor = str(payload.get("cursor") or "").strip()
        if not raw_items:
            break
    return conversation_urls


def collect_project_conversation_urls(
    page,
    project_url: str,
    state: TaskState,
    should_stop,
    startup_timeout_seconds: float = DEFAULT_CHATGPT_STARTUP_TIMEOUT_SECONDS,
    scan_wait_seconds: float = CHATGPT_SCAN_WAIT_SECONDS,
    request_headers: dict[str, str] | None = None,
) -> list[str]:
    """Load every project conversation, or use one supplied chat session URL."""
    if is_chatgpt_conversation_url(project_url):
        state.append_event("Using the supplied ChatGPT chat session URL.")
        return [project_url]

    observed_headers = request_headers if request_headers is not None else {}
    header_listener = _listen_for_chatgpt_request_headers(page, observed_headers)
    try:
        open_chatgpt_page(page, project_url, startup_timeout_seconds=startup_timeout_seconds)
        _wait_for_chatgpt_request_headers(page, observed_headers)
        context = getattr(page, "context", None)
        if context is not None and observed_headers:
            try:
                api_urls = _collect_project_conversation_urls_via_api(
                    context,
                    project_url,
                    observed_headers,
                    state,
                    should_stop,
                )
            except RuntimeError as exc:
                state.append_event(f"ChatGPT project API fallback: {exc}")
            else:
                if api_urls:
                    return api_urls
    finally:
        _stop_listening_for_chatgpt_response(page, header_listener)

    open_chatgpt_page(page, project_url, startup_timeout_seconds=startup_timeout_seconds)
    conversation_urls: list[str] = []
    seen_urls: set[str] = set()
    stagnant_rounds = 0
    current_links = _wait_for_project_conversation_links(
        page,
        project_url,
        should_stop,
        startup_timeout_seconds=startup_timeout_seconds,
        scan_wait_seconds=max(float(scan_wait_seconds), CHATGPT_PROJECT_SCAN_WAIT_SECONDS),
    )

    for round_index in range(CHATGPT_PROJECT_LOAD_ROUNDS):
        if should_stop():
            break
        for url in current_links:
            if url not in seen_urls:
                seen_urls.add(url)
                conversation_urls.append(url)
        state.append_event(
            f"ChatGPT project scan loaded {len(conversation_urls):,} conversations after page {round_index + 1}."
        )
        if not _has_load_more_conversations(page):
            break
        previous_rendered_count = len(current_links)
        if not _click_load_more_conversations(page):
            break
        for _ in range(CHATGPT_PROJECT_LINK_WAIT_ROUNDS):
            page.wait_for_timeout(1_000)
            current_links = _extract_project_links(page, project_url)
            if len(current_links) > previous_rendered_count:
                break
        after_count = len(current_links)
        stagnant_rounds = stagnant_rounds + 1 if after_count <= previous_rendered_count else 0
        if stagnant_rounds >= 3:
            state.append_event("ChatGPT project pagination stopped making progress.")
            break

    return conversation_urls


def _recent_chatgpt_image_candidate(
    raw_item: dict[str, object],
    project_url: str,
    project_conversation_ids: set[str],
) -> ChatGPTImageCandidate | None:
    """Build one original-image candidate from ChatGPT's recent image index."""
    conversation_id = str(raw_item.get("conversation_id") or "").strip()
    source_url = str(raw_item.get("url") or "").strip()
    if not conversation_id or conversation_id not in project_conversation_ids or not source_url:
        return None
    if urlsplit(source_url).scheme.lower() != "https":
        return None

    pointer_file_id = _extract_chatgpt_file_id_from_asset_pointer(raw_item.get("asset_pointer"))
    file_id = pointer_file_id or extract_chatgpt_file_id(source_url)
    if not file_id:
        return None
    try:
        width = max(0, int(raw_item.get("width") or 0))
        height = max(0, int(raw_item.get("height") or 0))
    except (TypeError, ValueError):
        width = 0
        height = 0
    return ChatGPTImageCandidate(
        source_url=source_url,
        file_id=file_id,
        conversation_url=f"{_project_conversation_prefix(project_url)}{conversation_id}",
        alt_text=str(raw_item.get("title") or "").strip(),
        width=width,
        height=height,
        message_role="assistant",
        conversation_title=str(raw_item.get("title") or "").strip(),
    )


def collect_chatgpt_project_index_images(
    context,
    project_url: str,
    conversation_urls: list[str],
    request_headers: dict[str, str],
    state: TaskState,
    should_stop,
) -> list[ChatGPTImageCandidate]:
    """Collect every current project image exposed by ChatGPT's recent-image index."""
    project_conversation_ids = {
        conversation_id
        for conversation_url in conversation_urls
        if (conversation_id := _chatgpt_conversation_id(conversation_url))
    }
    if not project_conversation_ids or not request_headers:
        return []

    api_headers = _chatgpt_api_request_headers(request_headers, project_url)
    candidates_by_file_id: dict[str, ChatGPTImageCandidate] = {}
    seen_cursors: set[str] = set()
    cursor = ""
    for page_index in range(CHATGPT_API_PAGE_LIMIT):
        if should_stop() or cursor in seen_cursors:
            break
        seen_cursors.add(cursor)
        query_values = {"limit": CHATGPT_RECENT_IMAGE_PAGE_SIZE}
        if cursor:
            query_values["after"] = cursor
        try:
            payload = _get_chatgpt_api_json(
                context,
                f"https://chatgpt.com/backend-api/my/recent/image_gen?{urlencode(query_values)}",
                api_headers,
            )
        except RuntimeError as exc:
            state.append_event(f"ChatGPT recent-image index paused: {exc}")
            break
        raw_items = payload.get("items")
        if not isinstance(raw_items, list):
            break
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                continue
            candidate = _recent_chatgpt_image_candidate(
                raw_item,
                project_url,
                project_conversation_ids,
            )
            if candidate is None:
                continue
            candidate = replace(candidate, request_headers=dict(request_headers))
            previous = candidates_by_file_id.get(candidate.file_id)
            if previous is None or candidate.width * candidate.height >= previous.width * previous.height:
                candidates_by_file_id[candidate.file_id] = candidate
        if page_index == 0 or (page_index + 1) % 10 == 0:
            state.append_event(
                f"ChatGPT recent-image index found {len(candidates_by_file_id):,} project images "
                f"after page {page_index + 1}."
            )
        cursor = str(payload.get("cursor") or "").strip()
        if not raw_items or not cursor:
            break
    return list(candidates_by_file_id.values())


def _extract_original_image_payloads(page) -> list[dict[str, object]]:
    """Extract original ChatGPT image URLs currently materialized in the DOM."""
    return page.evaluate(
        """() => {
            const results = new Map();
            const isOriginalImageUrl = (value) => {
                if (!value) return false;
                try {
                    const url = new URL(value, location.href);
                    const path = url.pathname.toLowerCase();
                    if (url.hostname === 'chatgpt.com' && path.includes('/backend-api/estuary/content')) {
                        return Boolean(url.searchParams.get('id'));
                    }
                    return url.hostname.endsWith('oaiusercontent.com') ||
                        url.hostname.endsWith('blob.core.windows.net');
                } catch (_error) {
                    return false;
                }
            };

            for (const image of document.images) {
                const candidateUrls = [
                    image.currentSrc,
                    image.src,
                    image.getAttribute('data-src'),
                    image.getAttribute('data-original'),
                ].filter(Boolean);
                const sourceUrl = candidateUrls.find(isOriginalImageUrl);
                if (!sourceUrl) continue;

                const parsed = new URL(sourceUrl, location.href);
                const fileId = parsed.searchParams.get('id') || sourceUrl;
                const message = image.closest('[data-message-author-role]');
                const candidate = {
                    sourceUrl: parsed.href,
                    fileId,
                    altText: image.alt || '',
                    width: image.naturalWidth || 0,
                    height: image.naturalHeight || 0,
                    messageRole: message?.getAttribute('data-message-author-role') || '',
                };
                const previous = results.get(fileId);
                if (!previous || (candidate.width * candidate.height) >= (previous.width * previous.height)) {
                    results.set(fileId, candidate);
                }
            }
            return [...results.values()];
        }"""
    )


def _listen_for_chatgpt_conversation_response(page, conversation_url: str):
    """Capture the complete conversation JSON response emitted during page startup."""
    expected_url = _chatgpt_conversation_api_url(conversation_url)
    add_listener = getattr(page, "on", None)
    if not expected_url or not callable(add_listener):
        return [], None

    responses: list[object] = []

    def capture(response) -> None:
        response_url = str(getattr(response, "url", "")).split("?", 1)[0].rstrip("/")
        if response_url == expected_url.rstrip("/"):
            responses.append(response)

    add_listener("response", capture)
    return responses, capture


def _stop_listening_for_chatgpt_conversation_response(page, listener) -> None:
    """Detach one temporary ChatGPT conversation response listener."""
    if listener is None:
        return
    remove_listener = getattr(page, "remove_listener", None)
    if not callable(remove_listener):
        return
    try:
        remove_listener("response", listener)
    except PlaywrightError:
        pass


def _wait_for_chatgpt_conversation_response(page, responses: list[object], listener) -> object | None:
    """Wait briefly for the full conversation response without delaying DOM fallback scans."""
    if listener is None:
        return None
    deadline = time.monotonic() + CHATGPT_CONVERSATION_RESPONSE_WAIT_MS / 1_000
    while time.monotonic() < deadline:
        for response in reversed(responses):
            try:
                payload = json.loads(response.text())
            except (AttributeError, PlaywrightError, TypeError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict) and isinstance(payload.get("mapping"), dict):
                return response
        page.wait_for_timeout(200)
    return responses[-1] if responses else None


def _wait_for_chatgpt_rendered_images(
    page,
    expected_image_count: int,
    should_stop,
) -> None:
    """Allow active ChatGPT image elements to materialize before the DOM fallback scan."""
    if expected_image_count <= 0:
        return
    deadline = time.monotonic() + CHATGPT_RENDERED_IMAGE_WAIT_MS / 1_000
    previous_count = 0
    stable_rounds = 0
    while not should_stop() and time.monotonic() < deadline:
        current_count = len(_extract_original_image_payloads(page))
        if current_count >= expected_image_count:
            return
        if current_count and current_count == previous_count:
            stable_rounds += 1
            if stable_rounds >= CHATGPT_RENDERED_IMAGE_STABLE_ROUNDS:
                return
        else:
            stable_rounds = 0
        previous_count = current_count
        page.wait_for_timeout(CHATGPT_RENDERED_IMAGE_POLL_MS)


def _merge_chatgpt_conversation_response_images(
    response,
    conversation_url: str,
    candidates_by_file_id: dict[str, ChatGPTImageCandidate],
    conversation_title: str,
) -> None:
    """Merge every image asset from ChatGPT's complete conversation API mapping."""
    try:
        payload = json.loads(response.text())
    except (AttributeError, PlaywrightError, TypeError, json.JSONDecodeError):
        return
    request_headers = _chatgpt_candidate_request_headers(response)
    for raw_candidate in _extract_chatgpt_conversation_image_payloads(payload):
        file_id = str(raw_candidate.get("fileId") or "").strip()
        if not file_id:
            continue
        candidate = ChatGPTImageCandidate(
            source_url=_chatgpt_file_download_url(file_id, conversation_url),
            file_id=file_id,
            conversation_url=conversation_url,
            alt_text=str(raw_candidate.get("altText") or "").strip(),
            width=int(raw_candidate.get("width") or 0),
            height=int(raw_candidate.get("height") or 0),
            message_role=str(raw_candidate.get("messageRole") or "").strip(),
            conversation_title=conversation_title,
            request_headers=dict(request_headers),
        )
        if not should_cache_chatgpt_candidate(candidate):
            continue
        previous = candidates_by_file_id.get(file_id)
        if previous is None or candidate.width * candidate.height >= previous.width * previous.height:
            candidates_by_file_id[file_id] = candidate


def _scroll_chatgpt_message_view(page, direction: str) -> dict[str, object]:
    """Move the conversation's own scroll container one viewport step."""
    return page.evaluate(
        """({ direction, stepRatio }) => {
            const messageSelector = '[data-message-author-role]';
            const scrollRoots = new Set();
            for (const message of document.querySelectorAll(messageSelector)) {
                for (let parent = message.parentElement; parent; parent = parent.parentElement) {
                    const overflowY = getComputedStyle(parent).overflowY;
                    if (
                        parent.scrollHeight > parent.clientHeight &&
                        (overflowY === 'auto' || overflowY === 'scroll')
                    ) {
                        scrollRoots.add(parent);
                    }
                }
            }

            const root = [...scrollRoots]
                .sort((left, right) => right.scrollHeight - left.scrollHeight)[0] ||
                document.scrollingElement ||
                document.documentElement;
            const previousTop = root.scrollTop;
            const step = Math.max(1, Math.floor(root.clientHeight * stepRatio));
            const maximumTop = Math.max(0, root.scrollHeight - root.clientHeight);
            root.scrollTop = direction === 'top'
                ? Math.max(0, previousTop - step)
                : Math.min(maximumTop, previousTop + step);
            const currentTop = root.scrollTop;
            const atBoundary = direction === 'top'
                ? currentTop <= 12
                : currentTop >= maximumTop - 12;
            return {
                height: root.scrollHeight,
                top: currentTop,
                viewport: root.clientHeight,
                atBoundary,
                moved: Math.abs(currentTop - previousTop) > 0,
            };
        }""",
        {"direction": direction, "stepRatio": CHATGPT_SCROLL_STEP_RATIO},
    )


def _merge_current_conversation_images(
    page,
    conversation_url: str,
    candidates_by_file_id: dict[str, ChatGPTImageCandidate],
    conversation_title: str,
) -> None:
    """Merge original images currently visible in one ChatGPT conversation."""
    for raw_candidate in _extract_original_image_payloads(page):
        source_url = str(raw_candidate.get("sourceUrl") or "").strip()
        if not source_url:
            continue
        file_id = str(raw_candidate.get("fileId") or extract_chatgpt_file_id(source_url)).strip()
        candidate = ChatGPTImageCandidate(
            source_url=source_url,
            file_id=file_id,
            conversation_url=conversation_url,
            alt_text=str(raw_candidate.get("altText") or "").strip(),
            width=int(raw_candidate.get("width") or 0),
            height=int(raw_candidate.get("height") or 0),
            message_role=str(raw_candidate.get("messageRole") or "").strip(),
            conversation_title=conversation_title,
        )
        if not should_cache_chatgpt_candidate(candidate):
            continue
        previous = candidates_by_file_id.get(file_id)
        candidate_has_direct_url = not _is_chatgpt_file_download_url(candidate.source_url)
        previous_has_direct_url = previous is not None and not _is_chatgpt_file_download_url(previous.source_url)
        if (
            previous is None
            or (candidate_has_direct_url and not previous_has_direct_url)
            or (
                candidate_has_direct_url == previous_has_direct_url
                and candidate.width * candidate.height >= previous.width * previous.height
            )
        ):
            candidates_by_file_id[file_id] = candidate


def collect_conversation_images(
    page,
    conversation_url: str,
    should_stop,
    startup_timeout_seconds: float = DEFAULT_CHATGPT_STARTUP_TIMEOUT_SECONDS,
    scan_wait_seconds: float = CHATGPT_SCAN_WAIT_SECONDS,
) -> list[ChatGPTImageCandidate]:
    """Open one conversation, scan its lazy message view, and collect original images."""
    candidates_by_file_id: dict[str, ChatGPTImageCandidate] = {}
    responses, response_listener = _listen_for_chatgpt_conversation_response(page, conversation_url)
    try:
        open_chatgpt_page(
            page,
            conversation_url,
            settle_ms=1_000,
            startup_timeout_seconds=startup_timeout_seconds,
        )
        try:
            conversation_title = _chatgpt_conversation_title(page.title())
        except (AttributeError, TypeError):
            conversation_title = ""
        _wait_for_chatgpt_conversation_response(page, responses, response_listener)
        for response in reversed(responses):
            _merge_chatgpt_conversation_response_images(
                response,
                conversation_url,
                candidates_by_file_id,
                conversation_title,
            )
    finally:
        _stop_listening_for_chatgpt_conversation_response(page, response_listener)

    _wait_for_chatgpt_rendered_images(page, len(candidates_by_file_id), should_stop)

    for direction in ("top", "bottom"):
        stable_rounds = 0
        previous_height = -1
        for _ in range(CHATGPT_SCROLL_ROUNDS):
            if should_stop():
                break
            _merge_current_conversation_images(page, conversation_url, candidates_by_file_id, conversation_title)
            scroll_metrics = _scroll_chatgpt_message_view(page, direction)
            wait_seconds = min(
                max(float(scan_wait_seconds), MIN_CHATGPT_SCAN_WAIT_SECONDS),
                MAX_CHATGPT_SCAN_WAIT_SECONDS,
            )
            page.wait_for_timeout(int(wait_seconds * 1_000))
            current_height = int(scroll_metrics.get("height") or 0)
            at_boundary = bool(scroll_metrics.get("atBoundary"))
            if at_boundary and not bool(scroll_metrics.get("moved")):
                break
            if at_boundary and current_height == previous_height:
                stable_rounds += 1
            else:
                stable_rounds = 0
            previous_height = current_height
            if stable_rounds >= 3:
                break
        if should_stop():
            break

    _merge_current_conversation_images(page, conversation_url, candidates_by_file_id, conversation_title)
    return list(candidates_by_file_id.values())


def _chatgpt_conversation_title(value: str) -> str:
    """Remove the ChatGPT product suffix from one browser tab title."""
    title = re.sub(r"\s*(?:[-|–—]\s*)?ChatGPT\s*$", "", str(value or "").strip(), flags=re.IGNORECASE)
    return "" if title.casefold() == "chatgpt" else title.strip()


def _is_recoverable_chatgpt_page_error(error: Exception) -> bool:
    """Return whether a failed page can be recovered by recycling the tab."""
    error_text = str(error or "")
    return any(marker in error_text for marker in CHATGPT_RECOVERABLE_PAGE_ERROR_MARKERS)


def _close_chatgpt_page(page) -> None:
    """Close a worker page without masking the original browser error."""
    if page is None:
        return
    try:
        page.close()
    except Exception:
        pass


def _collect_chatgpt_conversation_with_recovery(
    context,
    page,
    conversation_url: str,
    should_stop,
    startup_timeout_seconds: float,
    scan_wait_seconds: float,
) -> tuple[object, list[ChatGPTImageCandidate], Exception | None]:
    """Scan one conversation and recycle the worker page after recoverable failures."""
    try:
        return (
            page,
            collect_conversation_images(
                page,
                conversation_url,
                should_stop,
                startup_timeout_seconds=startup_timeout_seconds,
                scan_wait_seconds=scan_wait_seconds,
            ),
            None,
        )
    except Exception as exc:  # pragma: no cover - depends on live ChatGPT rendering
        if not _is_recoverable_chatgpt_page_error(exc):
            return page, [], exc
        _close_chatgpt_page(page)
        try:
            retry_page = context.new_page()
            return (
                retry_page,
                collect_conversation_images(
                    retry_page,
                    conversation_url,
                    should_stop,
                    startup_timeout_seconds=startup_timeout_seconds,
                    scan_wait_seconds=scan_wait_seconds,
                ),
                None,
            )
        except Exception as retry_error:  # pragma: no cover - depends on live ChatGPT rendering
            return retry_page if "retry_page" in locals() else page, [], retry_error


def _is_unavailable_chatgpt_image_error(candidate: ChatGPTImageCandidate, error: Exception) -> bool:
    """Return whether ChatGPT no longer serves an indexed historical image asset."""
    if "HTTP 404." not in str(error):
        return False
    return _is_chatgpt_file_download_url(candidate.source_url) or (
        urlsplit(candidate.source_url).path == "/backend-api/estuary/content"
    )


def _chatgpt_conversation_worker(
    assignments: list[tuple[int, str]],
    descriptor,
    catalog: ChatGPTImageCatalog,
    target_dir: Path,
    startup_timeout_seconds: float,
    scan_wait_seconds: float,
    should_stop,
    result_queue: Queue[ChatGPTConversationWorkResult],
) -> None:
    """Scan and download one partition of conversations in an isolated browser context."""
    next_assignment = 0
    page = None
    try:
        with sync_playwright() as playwright:
            with launch_chromium_context(
                playwright,
                descriptor,
                headless=False,
                clone_profile_first=True,
                background_window=True,
            ) as context:
                page = context.new_page()
                for assignment_position, (conversation_index, conversation_url) in enumerate(assignments):
                    if should_stop():
                        break
                    next_assignment = assignment_position
                    if assignment_position and assignment_position % CHATGPT_PAGE_RECYCLE_INTERVAL == 0:
                        _close_chatgpt_page(page)
                        page = context.new_page()

                    page, candidates, conversation_error = _collect_chatgpt_conversation_with_recovery(
                        context,
                        page,
                        conversation_url,
                        should_stop,
                        startup_timeout_seconds,
                        scan_wait_seconds,
                    )
                    if conversation_error is not None:
                        result_queue.put(
                            ChatGPTConversationWorkResult(
                                conversation_index=conversation_index,
                                conversation_url=conversation_url,
                                failed_count=1,
                                error=str(conversation_error),
                            )
                        )
                        next_assignment = assignment_position + 1
                        continue

                    downloaded_count = 0
                    skipped_known = 0
                    image_errors: list[str] = []
                    for candidate in candidates:
                        if should_stop():
                            break
                        try:
                            downloaded = download_chatgpt_image(context, catalog, target_dir, candidate)
                        except Exception as exc:  # pragma: no cover - depends on live ChatGPT responses
                            if _is_unavailable_chatgpt_image_error(candidate, exc):
                                catalog.mark_unavailable(candidate.file_id)
                                skipped_known += 1
                                continue
                            image_errors.append(f"{candidate.file_id}: {exc}")
                            continue
                        if downloaded:
                            downloaded_count += 1
                        else:
                            skipped_known += 1

                    result_queue.put(
                        ChatGPTConversationWorkResult(
                            conversation_index=conversation_index,
                            conversation_url=conversation_url,
                            candidate_file_ids=tuple(candidate.file_id for candidate in candidates),
                            downloaded_count=downloaded_count,
                            skipped_known=skipped_known,
                            failed_count=len(image_errors),
                            image_errors=tuple(image_errors),
                        )
                    )
                    next_assignment = assignment_position + 1
    except Exception as exc:  # pragma: no cover - depends on live browser startup
        for conversation_index, conversation_url in assignments[next_assignment:]:
            result_queue.put(
                ChatGPTConversationWorkResult(
                    conversation_index=conversation_index,
                    conversation_url=conversation_url,
                    failed_count=1,
                    error=str(exc),
                )
            )
    finally:
        _close_chatgpt_page(page)


def _iter_chatgpt_conversation_results(
    conversation_urls: list[str],
    descriptor,
    catalog: ChatGPTImageCatalog,
    target_dir: Path,
    startup_timeout_seconds: float,
    scan_wait_seconds: float,
    should_stop,
    worker_count: int,
) -> Iterator[ChatGPTConversationWorkResult]:
    """Yield conversation results while bounded Edge workers scan and download in parallel."""
    if not conversation_urls:
        return

    worker_count = max(1, min(worker_count, len(conversation_urls)))
    assignments = [
        list(enumerate(conversation_urls, start=1))[worker_index::worker_count]
        for worker_index in range(worker_count)
    ]
    result_queue: Queue[ChatGPTConversationWorkResult] = Queue()
    workers = [
        Thread(
            target=_chatgpt_conversation_worker,
            args=(
                worker_assignments,
                descriptor,
                catalog,
                target_dir,
                startup_timeout_seconds,
                scan_wait_seconds,
                should_stop,
                result_queue,
            ),
            daemon=True,
            name=f"chatgpt-worker-{worker_index + 1}",
        )
        for worker_index, worker_assignments in enumerate(assignments)
        if worker_assignments
    ]
    for worker in workers:
        worker.start()

    try:
        while any(worker.is_alive() for worker in workers) or not result_queue.empty():
            try:
                yield result_queue.get(timeout=0.2)
            except Empty:
                continue
    finally:
        for worker in workers:
            worker.join()

    while not result_queue.empty():
        yield result_queue.get_nowait()


def _chatgpt_index_image_worker(
    candidates: list[ChatGPTImageCandidate],
    descriptor,
    catalog: ChatGPTImageCatalog,
    target_dir: Path,
    should_stop,
    result_queue: Queue[ChatGPTImageDownloadWorkResult],
) -> None:
    """Download one partition of signed project-index originals in an isolated Edge context."""
    next_candidate_index = 0
    try:
        with sync_playwright() as playwright:
            with launch_chromium_context(
                playwright,
                descriptor,
                headless=False,
                clone_profile_first=True,
                background_window=True,
            ) as context:
                for candidate_index, candidate in enumerate(candidates):
                    if should_stop():
                        break
                    next_candidate_index = candidate_index
                    try:
                        downloaded = download_chatgpt_image(context, catalog, target_dir, candidate)
                    except Exception as exc:  # pragma: no cover - depends on live ChatGPT responses
                        if _is_unavailable_chatgpt_image_error(candidate, exc):
                            catalog.mark_unavailable(candidate.file_id)
                            result_queue.put(
                                ChatGPTImageDownloadWorkResult(
                                    candidate_file_id=candidate.file_id,
                                    skipped=True,
                                )
                            )
                            next_candidate_index = candidate_index + 1
                            continue
                        result_queue.put(
                            ChatGPTImageDownloadWorkResult(
                                candidate_file_id=candidate.file_id,
                                error=str(exc),
                            )
                        )
                    else:
                        result_queue.put(
                            ChatGPTImageDownloadWorkResult(
                                candidate_file_id=candidate.file_id,
                                downloaded=downloaded,
                                skipped=not downloaded,
                            )
                        )
                    next_candidate_index = candidate_index + 1
    except Exception as exc:  # pragma: no cover - depends on live browser startup
        for candidate in candidates[next_candidate_index:]:
            result_queue.put(
                ChatGPTImageDownloadWorkResult(
                    candidate_file_id=candidate.file_id,
                    error=str(exc),
                )
            )


def _iter_chatgpt_index_image_results(
    candidates: list[ChatGPTImageCandidate],
    descriptor,
    catalog: ChatGPTImageCatalog,
    target_dir: Path,
    should_stop,
    worker_count: int,
) -> Iterator[ChatGPTImageDownloadWorkResult]:
    """Yield bounded parallel downloads for ChatGPT's project-level image index."""
    if not candidates:
        return

    worker_count = max(1, min(worker_count, len(candidates)))
    assignments = [candidates[worker_index::worker_count] for worker_index in range(worker_count)]
    result_queue: Queue[ChatGPTImageDownloadWorkResult] = Queue()
    workers = [
        Thread(
            target=_chatgpt_index_image_worker,
            args=(worker_candidates, descriptor, catalog, target_dir, should_stop, result_queue),
            daemon=True,
            name=f"chatgpt-index-worker-{worker_index + 1}",
        )
        for worker_index, worker_candidates in enumerate(assignments)
        if worker_candidates
    ]
    for worker in workers:
        worker.start()

    try:
        while any(worker.is_alive() for worker in workers) or not result_queue.empty():
            try:
                yield result_queue.get(timeout=0.2)
            except Empty:
                continue
    finally:
        for worker in workers:
            worker.join()

    while not result_queue.empty():
        yield result_queue.get_nowait()


def _chatgpt_image_request_headers(candidate: ChatGPTImageCandidate) -> dict[str, str]:
    """Build transient browser-authenticated headers for one ChatGPT image request."""
    headers = {
        str(key): str(value)
        for key, value in candidate.request_headers.items()
        if str(key).lower() in CHATGPT_DOWNLOAD_AUTH_HEADER_NAMES and str(value)
    }
    headers.update(
        {
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            "Referer": candidate.conversation_url,
        }
    )
    return headers


def _resolve_chatgpt_image_source_url(context, candidate: ChatGPTImageCandidate) -> str:
    """Resolve a file-service asset to its short-lived original image URL."""
    if not _is_chatgpt_file_download_url(candidate.source_url):
        return candidate.source_url
    if not candidate.request_headers:
        raise RuntimeError("ChatGPT image authorization was not captured from the conversation response.")

    response = context.request.get(
        candidate.source_url,
        timeout=CHATGPT_IMAGE_TIMEOUT_MS,
        headers=_chatgpt_image_request_headers(candidate),
    )
    if not response.ok:
        raise RuntimeError(f"ChatGPT file metadata request returned HTTP {response.status}.")
    try:
        payload = json.loads(response.text())
    except (AttributeError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("ChatGPT file metadata response was not valid JSON.") from exc

    source_url = str(payload.get("download_url") or "").strip() if isinstance(payload, dict) else ""
    parsed = urlsplit(source_url)
    if parsed.scheme.lower() != "https" or not parsed.netloc:
        raise RuntimeError("ChatGPT file metadata did not include a valid original image URL.")
    return source_url


def _request_chatgpt_image_with_refresh(context, candidate: ChatGPTImageCandidate):
    """Request an original image and refresh an expired direct URL through file metadata."""
    source_url = _resolve_chatgpt_image_source_url(context, candidate)
    resolved_candidate = (
        candidate
        if source_url == candidate.source_url
        else replace(candidate, source_url=source_url, request_headers={})
    )
    response = context.request.get(
        source_url,
        timeout=CHATGPT_IMAGE_TIMEOUT_MS,
        headers=_chatgpt_image_request_headers(candidate),
    )
    if (
        response.ok
        or _is_chatgpt_file_download_url(candidate.source_url)
        or not candidate.file_id.startswith("file_")
        or int(response.status) not in {401, 403, 404}
    ):
        return response, source_url, resolved_candidate

    refresh_candidate = replace(
        candidate,
        source_url=_chatgpt_file_download_url(candidate.file_id, candidate.conversation_url),
    )
    try:
        refreshed_source_url = _resolve_chatgpt_image_source_url(context, refresh_candidate)
    except RuntimeError:
        return response, source_url, resolved_candidate

    refreshed_response = context.request.get(
        refreshed_source_url,
        timeout=CHATGPT_IMAGE_TIMEOUT_MS,
        headers=_chatgpt_image_request_headers(refresh_candidate),
    )
    if not refreshed_response.ok:
        return response, source_url, resolved_candidate
    return (
        refreshed_response,
        refreshed_source_url,
        replace(candidate, source_url=refreshed_source_url, request_headers={}),
    )


def download_chatgpt_image(
    context,
    catalog: ChatGPTImageCatalog,
    target_dir: Path,
    candidate: ChatGPTImageCandidate,
) -> bool:
    """Download one original image through the authenticated browser context."""
    if not should_cache_chatgpt_candidate(candidate):
        return False
    if BrowserDeletionCatalog(target_dir.parent.parent).is_excluded("chatgpt", candidate.file_id):
        return False
    if not catalog.claim_download(candidate.file_id):
        catalog.update_metadata(candidate)
        return False

    try:
        response, source_url, resolved_candidate = _request_chatgpt_image_with_refresh(context, candidate)
        if not response.ok:
            raise RuntimeError(f"ChatGPT image request returned HTTP {response.status}.")

        content = response.body()
        content_type = str(response.headers.get("content-type") or "")
        if (
            not content
            or content_type.lower().startswith(("text/", "application/json"))
            or not looks_like_image(content)
        ):
            raise RuntimeError("ChatGPT returned a non-image or incomplete image payload.")

        extension = infer_image_extension(source_url, content_type, content)
        filename = f"img_{sanitize_filename_part(candidate.file_id)}{extension}"
        target_path = target_dir / filename
        partial_dir = target_dir / CHATGPT_PARTIAL_DIRNAME
        partial_dir.mkdir(parents=True, exist_ok=True)
        partial_path = partial_dir / f"{sanitize_filename_part(candidate.file_id)}.part"
        partial_path.write_bytes(content)
        os.replace(partial_path, target_path)
        catalog.register_download(
            candidate=resolved_candidate,
            relative_path=target_path.relative_to(target_dir).as_posix(),
            content_sha256=compute_sha256(content),
            content_bytes=len(content),
            seen_at=utc_now(),
        )
        return True
    except Exception:
        catalog.release_download(candidate.file_id)
        raise


def sync_chatgpt_images(
    state: TaskState,
    config: CrawlConfig | None = None,
    target_dir: Path | None = None,
    should_stop=lambda: False,
) -> ChatGPTSyncResult:
    """Cache all original images from the selected ChatGPT source."""
    runtime_config = config or CrawlConfig()
    descriptor = browser_descriptors(runtime_config).get(runtime_config.chatgpt_browser)
    if descriptor is None:
        raise RuntimeError(f"Unsupported ChatGPT browser: {runtime_config.chatgpt_browser}")
    if descriptor.engine != "chromium":
        raise RuntimeError(f"ChatGPT sync requires a Chromium browser, not {descriptor.label}.")
    if sync_playwright is None:
        raise RuntimeError(
            "Playwright is not installed. Run `python3 -m pip install -r requirements.txt` "
            "and `python3 -m playwright install chromium`."
        )

    project_name = runtime_config.chatgpt_project_name or DEFAULT_CHATGPT_PROJECT_NAME
    project_url = runtime_config.chatgpt_project_url or DEFAULT_CHATGPT_PROJECT_URL
    startup_timeout_seconds = min(
        max(
            float(runtime_config.chatgpt_startup_timeout_seconds),
            MIN_CHATGPT_STARTUP_TIMEOUT_SECONDS,
        ),
        MAX_CHATGPT_STARTUP_TIMEOUT_SECONDS,
    )
    scan_wait_seconds = min(
        max(float(runtime_config.chatgpt_scan_wait_seconds), MIN_CHATGPT_SCAN_WAIT_SECONDS),
        MAX_CHATGPT_SCAN_WAIT_SECONDS,
    )
    resolved_target_dir = target_dir or chatgpt_target_dir(project_name)
    catalog = ChatGPTImageCatalog.build(resolved_target_dir)
    cached_count = catalog.summarize()
    state.update(
        account_name=project_name,
        output_dir=str(resolved_target_dir),
        downloaded_posts=cached_count,
        downloaded_tweets=cached_count,
        discovered_images=cached_count,
        downloaded_images=cached_count,
        downloaded_videos=0,
        queued_tweets=0,
        processed_tweets=0,
        discovery_complete=False,
    )
    state.append_event(f"Prepared ChatGPT cache with {cached_count:,} existing original images.")
    state.append_event(
        f"ChatGPT startup timeout: {startup_timeout_seconds:g} s; "
        f"scan wait: {scan_wait_seconds:g} s."
    )
    if should_stop():
        return ChatGPTSyncResult(cached_count=cached_count, stopped=True)

    try:
        state.update(phase="collecting")
        project_request_headers: dict[str, str] = {}
        project_index_candidates: list[ChatGPTImageCandidate] = []
        with sync_playwright() as playwright:
            state.append_event(
                f"Starting an offscreen {descriptor.label} session for the authorized ChatGPT sync."
            )
            with launch_chromium_context(
                playwright,
                descriptor,
                headless=False,
                clone_profile_first=True,
                background_window=True,
            ) as discovery_context:
                page = discovery_context.new_page()
                conversation_urls = collect_project_conversation_urls(
                    page,
                    project_url,
                    state,
                    should_stop,
                    startup_timeout_seconds=startup_timeout_seconds,
                    scan_wait_seconds=scan_wait_seconds,
                    request_headers=project_request_headers,
                )
                if not should_stop():
                    project_index_candidates = collect_chatgpt_project_index_images(
                        discovery_context,
                        project_url,
                        conversation_urls,
                        project_request_headers,
                        state,
                        should_stop,
                    )
                state.update(
                    discovered_tweets=len(conversation_urls),
                    discovered_images=len(project_index_candidates),
                    queued_tweets=0 if project_index_candidates else len(conversation_urls),
                    processed_tweets=0,
                )
                state.append_event(f"Found {len(conversation_urls):,} ChatGPT conversations in the project.")
                if project_index_candidates:
                    state.append_event(
                        f"Found {len(project_index_candidates):,} current original images in "
                        "ChatGPT's project image index."
                    )

        discovered_images = {candidate.file_id for candidate in project_index_candidates}
        downloaded_count = 0
        skipped_known = 0
        failed_count = 0
        processed_conversations = 0
        worker_count = max(1, min(int(runtime_config.download_workers), CHATGPT_MAX_CONVERSATION_WORKERS))
        state.append_event(
            f"Starting {worker_count} parallel ChatGPT worker{'' if worker_count == 1 else 's'} "
            "with one isolated Edge context per worker. Direct project-index downloads run first."
        )
        indexed_images_processed = 0
        for result in _iter_chatgpt_index_image_results(
            project_index_candidates,
            descriptor,
            catalog,
            resolved_target_dir,
            should_stop,
            worker_count,
        ):
            indexed_images_processed += 1
            downloaded_count += int(result.downloaded)
            skipped_known += int(result.skipped)
            if result.error:
                failed_count += 1
                state.append_event(
                    f"Failed ChatGPT project-index image {result.candidate_file_id}: {result.error}"
                )

            cached_count = catalog.summarize()
            state.update(
                phase="downloading" if downloaded_count else "collecting",
                discovered_tweets=len(conversation_urls),
                discovered_images=len(discovered_images),
                queued_tweets=0 if project_index_candidates else len(conversation_urls),
                processed_tweets=processed_conversations,
                downloaded_posts=cached_count,
                downloaded_tweets=cached_count,
                downloaded_images=cached_count,
                downloaded_videos=0,
                skipped_tweets=skipped_known,
                failed_tweets=failed_count,
            )
            if (
                indexed_images_processed == len(project_index_candidates)
                or indexed_images_processed % CHATGPT_RECENT_IMAGE_PAGE_SIZE == 0
            ):
                state.append_event(
                    f"Cached {indexed_images_processed:,}/{len(project_index_candidates):,} "
                    "direct ChatGPT project-index images."
                )

        if project_index_candidates:
            state.append_event(
                "ChatGPT's project image index is available; skipping legacy conversation scans "
                "that only surface unavailable historical assets."
            )
            conversation_results = ()
        elif should_stop():
            conversation_results = ()
        else:
            state.append_event("Starting ChatGPT conversation scans because no project image index was available.")
            conversation_results = _iter_chatgpt_conversation_results(
                conversation_urls,
                descriptor,
                catalog,
                resolved_target_dir,
                startup_timeout_seconds,
                scan_wait_seconds,
                should_stop,
                worker_count,
            )
        for result in conversation_results:
            processed_conversations += 1
            discovered_images.update(result.candidate_file_ids)
            downloaded_count += result.downloaded_count
            skipped_known += result.skipped_known
            failed_count += result.failed_count
            if result.error:
                state.append_event(
                    f"Failed to inspect ChatGPT conversation {result.conversation_index:,}/{len(conversation_urls):,}: "
                    f"{result.error}"
                )
            for image_error in result.image_errors:
                state.append_event(f"Failed ChatGPT image {image_error}")

            cached_count = catalog.summarize()
            state.update(
                phase="downloading" if downloaded_count else "collecting",
                discovered_tweets=len(conversation_urls),
                discovered_images=len(discovered_images),
                queued_tweets=0 if project_index_candidates else len(conversation_urls),
                processed_tweets=processed_conversations,
                downloaded_posts=cached_count,
                downloaded_tweets=cached_count,
                downloaded_images=cached_count,
                downloaded_videos=0,
                skipped_tweets=skipped_known,
                failed_tweets=failed_count,
            )
            state.append_event(
                f"Scanned ChatGPT conversation {result.conversation_index:,}/{len(conversation_urls):,}; "
                f"found {len(result.candidate_file_ids):,} original images."
            )

        cached_count = catalog.summarize()
        stopped = should_stop()
        state.update(
            discovered_tweets=len(conversation_urls),
            discovered_images=len(discovered_images),
            queued_tweets=0 if project_index_candidates else len(conversation_urls),
            processed_tweets=processed_conversations,
            discovery_complete=True,
            downloaded_posts=cached_count,
            downloaded_tweets=cached_count,
            downloaded_images=cached_count,
            downloaded_videos=0,
            skipped_tweets=skipped_known,
            failed_tweets=failed_count,
        )
        return ChatGPTSyncResult(
            discovered_conversations=len(conversation_urls),
            discovered_images=len(discovered_images),
            downloaded_count=downloaded_count,
            skipped_known=skipped_known,
            failed_count=failed_count,
            cached_count=cached_count,
            stopped=stopped,
        )
    except PlaywrightError as exc:
        raise RuntimeError(f"ChatGPT browser automation failed: {exc}") from exc
