"""ChatGPT project image cache helpers."""

# Code version: v1.0.3-codex.1

from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .browser_sessions import browser_descriptors, launch_chromium_context
from .config import (
    DEFAULT_CHATGPT_PROJECT_NAME,
    DEFAULT_CHATGPT_PROJECT_URL,
    LOCAL_STORE_ROOT,
    CrawlConfig,
)
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
CHATGPT_IMAGE_WAIT_MS = 500
CHATGPT_IMAGE_SUFFIXES = {".avif", ".gif", ".heic", ".jpeg", ".jpg", ".png", ".webp"}


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
    """Return whether an image belongs to an assistant message and may be cached."""
    return candidate.message_role.strip().lower() != "user"


class ChatGPTImageCatalog:
    """Durable catalog for the dedicated ChatGPT project cache directory."""

    def __init__(self, target_dir: Path, entries: dict[str, ChatGPTCatalogEntry] | None = None) -> None:
        self.target_dir = target_dir
        self.catalog_path = target_dir / CHATGPT_CATALOG_FILENAME
        self.entries_by_file_id = entries or {}

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
        write_json_atomic(
            self.catalog_path,
            {
                "version": 1,
                "entries": {file_id: asdict(entry) for file_id, entry in self.entries_by_file_id.items()},
            },
        )

    def complete_entry(self, file_id: str) -> ChatGPTCatalogEntry | None:
        """Return a catalog entry only when its local file is still valid."""
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

    def summarize(self) -> int:
        """Return the number of cataloged images whose files still exist."""
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
        )
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


def _wait_for_project_conversation_links(page, project_url: str, should_stop) -> list[str]:
    """Wait for the project list to finish its initial asynchronous rendering."""
    previous_count = 0
    stable_rounds = 0
    current_links: list[str] = []
    for _ in range(CHATGPT_PROJECT_LINK_WAIT_ROUNDS):
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
        page.wait_for_timeout(1_000)
    if current_links:
        return current_links
    raise RuntimeError(
        "ChatGPT project loaded without any conversation links after 30 seconds. "
        "The authorized Edge session may need to finish loading the project first."
    )


def open_chatgpt_page(page, url: str, settle_ms: int = 2_500) -> None:
    """Open a ChatGPT page and tolerate its long-lived application requests."""
    page.goto(url, wait_until="domcontentloaded", timeout=CHATGPT_PAGE_GOTO_TIMEOUT_MS)
    for _ in range(30):
        title = page.title().lower()
        body_text = page.locator("body").inner_text(timeout=15_000)[:500].lower()
        if "just a moment" not in title and "checking your browser" not in body_text:
            break
        page.wait_for_timeout(1_000)
    else:
        raise RuntimeError("ChatGPT showed a security verification page instead of the authorized project.")
    if settle_ms > 0:
        page.wait_for_timeout(settle_ms)


def collect_project_conversation_urls(page, project_url: str, state: TaskState, should_stop) -> list[str]:
    """Load every conversation link exposed by the ChatGPT project list."""
    open_chatgpt_page(page, project_url)
    conversation_urls: list[str] = []
    seen_urls: set[str] = set()
    stagnant_rounds = 0
    current_links = _wait_for_project_conversation_links(page, project_url, should_stop)

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


def collect_conversation_images(page, conversation_url: str, should_stop) -> list[ChatGPTImageCandidate]:
    """Open one conversation, scroll through lazy content, and collect original images."""
    open_chatgpt_page(page, conversation_url, settle_ms=3_000)
    candidates_by_file_id: dict[str, ChatGPTImageCandidate] = {}
    stable_rounds = 0
    previous_height = -1

    for _ in range(CHATGPT_SCROLL_ROUNDS):
        if should_stop():
            break
        raw_candidates = _extract_original_image_payloads(page)
        for raw_candidate in raw_candidates:
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
            )
            if not should_cache_chatgpt_candidate(candidate):
                continue
            previous = candidates_by_file_id.get(file_id)
            if previous is None or candidate.width * candidate.height >= previous.width * previous.height:
                candidates_by_file_id[file_id] = candidate

        scroll_metrics = page.evaluate(
            """() => {
                const scrollingElement = document.scrollingElement || document.documentElement;
                window.scrollTo(0, scrollingElement.scrollHeight);
                return {
                    height: scrollingElement.scrollHeight,
                    top: window.scrollY,
                    viewport: window.innerHeight,
                };
            }"""
        )
        page.wait_for_timeout(CHATGPT_IMAGE_WAIT_MS)
        at_bottom = float(scroll_metrics.get("top") or 0) + float(scroll_metrics.get("viewport") or 0) >= float(
            scroll_metrics.get("height") or 0
        ) - 12
        if at_bottom and int(scroll_metrics.get("height") or 0) == previous_height:
            stable_rounds += 1
        else:
            stable_rounds = 0
        previous_height = int(scroll_metrics.get("height") or 0)
        if stable_rounds >= 3:
            break

    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(CHATGPT_IMAGE_WAIT_MS)
    for raw_candidate in _extract_original_image_payloads(page):
        source_url = str(raw_candidate.get("sourceUrl") or "").strip()
        if not source_url:
            continue
        file_id = str(raw_candidate.get("fileId") or extract_chatgpt_file_id(source_url)).strip()
        candidates_by_file_id[file_id] = ChatGPTImageCandidate(
            source_url=source_url,
            file_id=file_id,
            conversation_url=conversation_url,
            alt_text=str(raw_candidate.get("altText") or "").strip(),
            width=int(raw_candidate.get("width") or 0),
            height=int(raw_candidate.get("height") or 0),
            message_role=str(raw_candidate.get("messageRole") or "").strip(),
        )
        if not should_cache_chatgpt_candidate(candidates_by_file_id[file_id]):
            candidates_by_file_id.pop(file_id, None)
    return list(candidates_by_file_id.values())


def download_chatgpt_image(
    context,
    catalog: ChatGPTImageCatalog,
    target_dir: Path,
    candidate: ChatGPTImageCandidate,
) -> bool:
    """Download one original image through the authenticated browser context."""
    if not should_cache_chatgpt_candidate(candidate):
        return False
    if catalog.complete_entry(candidate.file_id) is not None:
        return False

    response = context.request.get(
        candidate.source_url,
        timeout=CHATGPT_IMAGE_TIMEOUT_MS,
        headers={
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            "Referer": candidate.conversation_url,
        },
    )
    if not response.ok:
        raise RuntimeError(f"ChatGPT image request returned HTTP {response.status}.")

    content = response.body()
    content_type = str(response.headers.get("content-type") or "")
    if not content or content_type.lower().startswith(("text/", "application/json")) or not looks_like_image(content):
        raise RuntimeError("ChatGPT returned a non-image or incomplete image payload.")

    extension = infer_image_extension(candidate.source_url, content_type, content)
    filename = f"img_{sanitize_filename_part(candidate.file_id)}{extension}"
    target_path = target_dir / filename
    partial_dir = target_dir / CHATGPT_PARTIAL_DIRNAME
    partial_dir.mkdir(parents=True, exist_ok=True)
    partial_path = partial_dir / f"{sanitize_filename_part(candidate.file_id)}.part"
    partial_path.write_bytes(content)
    os.replace(partial_path, target_path)
    catalog.register_download(
        candidate=candidate,
        relative_path=target_path.relative_to(target_dir).as_posix(),
        content_sha256=compute_sha256(content),
        content_bytes=len(content),
        seen_at=utc_now(),
    )
    return True


def sync_chatgpt_images(
    state: TaskState,
    config: CrawlConfig | None = None,
    target_dir: Path | None = None,
    should_stop=lambda: False,
) -> ChatGPTSyncResult:
    """Cache assistant images while excluding user-uploaded message attachments."""
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
    if should_stop():
        return ChatGPTSyncResult(cached_count=cached_count, stopped=True)

    context = None
    try:
        state.update(phase="collecting")
        with sync_playwright() as playwright:
            state.append_event("Opening the authorized Edge window for ChatGPT sync.")
            with launch_chromium_context(
                playwright,
                descriptor,
                headless=False,
                clone_profile_first=True,
            ) as context:
                page = context.new_page()
                conversation_urls = collect_project_conversation_urls(page, project_url, state, should_stop)
                state.update(
                    discovered_tweets=len(conversation_urls),
                    discovered_images=0,
                    queued_tweets=len(conversation_urls),
                    processed_tweets=0,
                )
                state.append_event(f"Found {len(conversation_urls):,} Studio208cm conversations to inspect.")

                discovered_images: set[str] = set()
                downloaded_count = 0
                skipped_known = 0
                failed_count = 0
                processed_conversations = 0
                for conversation_index, conversation_url in enumerate(conversation_urls, start=1):
                    if should_stop():
                        break
                    try:
                        candidates = collect_conversation_images(page, conversation_url, should_stop)
                    except Exception as exc:  # pragma: no cover - depends on live ChatGPT rendering
                        failed_count += 1
                        state.append_event(
                            f"Failed to inspect ChatGPT conversation {conversation_index:,}/{len(conversation_urls):,}: {exc}"
                        )
                        processed_conversations = conversation_index
                        state.update(
                            processed_tweets=processed_conversations,
                            failed_tweets=failed_count,
                        )
                        continue

                    for candidate in candidates:
                        discovered_images.add(candidate.file_id)
                        try:
                            downloaded = download_chatgpt_image(context, catalog, resolved_target_dir, candidate)
                        except Exception as exc:  # pragma: no cover - depends on live ChatGPT responses
                            failed_count += 1
                            state.append_event(f"Failed ChatGPT image {candidate.file_id}: {exc}")
                            continue
                        if downloaded:
                            downloaded_count += 1
                        else:
                            skipped_known += 1

                    processed_conversations = conversation_index
                    cached_count = catalog.summarize()
                    state.update(
                        phase="downloading" if downloaded_count else "collecting",
                        discovered_tweets=len(conversation_urls),
                        discovered_images=len(discovered_images),
                        queued_tweets=len(conversation_urls),
                        processed_tweets=processed_conversations,
                        downloaded_posts=cached_count,
                        downloaded_tweets=cached_count,
                        downloaded_images=cached_count,
                        downloaded_videos=0,
                        skipped_tweets=skipped_known,
                        failed_tweets=failed_count,
                    )
                    state.append_event(
                        f"Scanned ChatGPT conversation {conversation_index:,}/{len(conversation_urls):,}; "
                        f"found {len(candidates):,} original images."
                    )

                cached_count = catalog.summarize()
                stopped = should_stop()
                state.update(
                    discovered_tweets=len(conversation_urls),
                    discovered_images=len(discovered_images),
                    queued_tweets=len(conversation_urls),
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
    finally:
        if context is not None:
            try:
                context.close()
            except Exception:
                pass
