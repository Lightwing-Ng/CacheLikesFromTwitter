/* Code version: v1.8.1-codex.2 */

(function initializeLocalMediaBrowser() {
    "use strict";

    const dataNode = document.getElementById("browser_media_data");
    const dialog = document.getElementById("browser_detail_dialog");
    if (!dataNode || !dialog) return;

    const filterForm = document.querySelector(".browser-filter-form");
    if (filterForm) {
        let filterSubmitTimer = 0;
        const submitFilters = () => {
            if (filterSubmitTimer) window.clearTimeout(filterSubmitTimer);
            filterSubmitTimer = window.setTimeout(() => {
                filterSubmitTimer = 0;
                filterForm.requestSubmit();
            }, 180);
        };
        filterForm.addEventListener("change", (event) => {
            if (event.target.matches("select")) submitFilters();
        });
        filterForm.addEventListener("input", (event) => {
            if (event.target.matches("input[name='q']")) submitFilters();
        });
    }

    let mediaItems = [];
    try {
        const parsed = JSON.parse(dataNode.textContent || "[]");
        mediaItems = Array.isArray(parsed) ? parsed : [];
    } catch (_error) {
        mediaItems = [];
    }

    const mediaById = new Map(
        mediaItems
            .filter((item) => item && typeof item.id === "string")
            .map((item) => [item.id, item]),
    );
    const previewElements = Array.from(document.querySelectorAll("[data-preview]"));
    const mediaCards = Array.from(document.querySelectorAll("[data-media-id]"));
    const previewObserver = "IntersectionObserver" in window
        ? new IntersectionObserver((entries, observer) => {
            entries.forEach((entry) => {
                if (!entry.isIntersecting) return;
                loadPreview(entry.target);
                observer.unobserve(entry.target);
            });
        }, { rootMargin: "240px 0px", threshold: 0.01 })
        : null;

    function previewShell(element) {
        return element.closest("[data-preview-shell]");
    }

    function setPreviewStatus(element, message, failed = false) {
        const shell = previewShell(element);
        const status = shell?.querySelector("[data-preview-status]");
        if (!status) return;
        status.textContent = message;
        status.hidden = !message;
        shell.classList.toggle("is-load-failed", failed);
        shell.classList.toggle("is-ready", !failed && !message);
    }

    function loadPreview(element) {
        if (!element || element.dataset.previewLoaded === "1") return;
        const source = element.dataset.mediaSrc;
        if (!source) {
            setPreviewStatus(element, "Preview unavailable", true);
            return;
        }

        element.dataset.previewLoaded = "1";
        const onReady = () => setPreviewStatus(element, "");
        const onError = () => {
            element.hidden = true;
            setPreviewStatus(element, "Preview unavailable", true);
        };
        element.addEventListener("load", onReady, { once: true });
        element.addEventListener("loadeddata", onReady, { once: true });
        element.addEventListener("error", onError, { once: true });
        element.src = source;
        if (element.tagName === "VIDEO") element.load();
    }

    previewElements.forEach((element) => {
        if (previewObserver) {
            previewObserver.observe(element);
        } else if (element.tagName === "IMG") {
            loadPreview(element);
        }
    });

    const pagination = document.querySelector(".browser-pagination");

    function positionPaginationIndicator() {
        if (!pagination) return;
        const indicator = pagination.querySelector(".local-store-pagination-indicator");
        const target = pagination.querySelector(".local-store-page-button.is-active");
        if (!indicator || !target) return;

        const paginationRect = pagination.getBoundingClientRect();
        const targetRect = target.getBoundingClientRect();
        const x = targetRect.left - paginationRect.left - pagination.clientLeft;
        const y = targetRect.top - paginationRect.top - pagination.clientTop;
        indicator.style.width = `${targetRect.width}px`;
        indicator.style.height = `${targetRect.height}px`;
        indicator.style.transform = `translate3d(${x}px, ${y}px, 0)`;
        pagination.classList.add("is-animated");
    }

    if (pagination) {
        window.requestAnimationFrame(positionPaginationIndicator);
        window.addEventListener("resize", positionPaginationIndicator, { passive: true });
    }

    const viewerMedia = dialog.querySelector("[data-viewer-media]");
    const viewerTitle = dialog.querySelector("[data-viewer-title]");
    const viewerSource = dialog.querySelector("[data-viewer-source]");
    const viewerCreator = dialog.querySelector("[data-viewer-creator]");
    const viewerDate = dialog.querySelector("[data-viewer-date]");
    const viewerFilename = dialog.querySelector("[data-viewer-filename]");
    const viewerSize = dialog.querySelector("[data-viewer-size]");
    const viewerDescription = dialog.querySelector("[data-viewer-description]");
    const viewerSourceLink = dialog.querySelector("[data-viewer-source-link]");
    const viewerSourceLinkLabel = dialog.querySelector("[data-viewer-source-link-label]");
    const viewerSourceUrl = dialog.querySelector("[data-viewer-source-url]");
    const closeButtons = Array.from(dialog.querySelectorAll("[data-dialog-close]"));
    const mediaOpenButtons = Array.from(document.querySelectorAll("[data-media-open]"));
    const mediaDeleteButtons = Array.from(document.querySelectorAll("[data-media-delete]"));
    const mediaRestoreButtons = Array.from(document.querySelectorAll("[data-media-restore]"));
    let activeTrigger = null;
    let viewerVideo = null;
    let viewerMediaResizeHandler = null;

    function setText(element, value, fallback = "—") {
        if (element) element.textContent = value || fallback;
    }

    function clearViewerMedia() {
        if (viewerMediaResizeHandler) {
            window.removeEventListener("resize", viewerMediaResizeHandler);
            viewerMediaResizeHandler = null;
        }
        if (viewerVideo) {
            viewerVideo.pause();
            viewerVideo.removeAttribute("src");
            viewerVideo.load();
            viewerVideo = null;
        }
        if (viewerMedia) viewerMedia.replaceChildren();
        dialog.style.removeProperty("width");
        dialog.style.removeProperty("height");
    }

    function validExternalUrl(value) {
        if (typeof value !== "string" || !value) return "";
        try {
            const parsed = new URL(value, window.location.href);
            return parsed.protocol === "http:" || parsed.protocol === "https:" ? value : "";
        } catch (_error) {
            return "";
        }
    }

    function getAdjacentVideoItem(item, direction) {
        const videoItems = mediaItems.filter((mediaItem) => mediaItem?.media_kind === "video");
        const currentIndex = videoItems.findIndex((mediaItem) => mediaItem.id === item.id);
        if (currentIndex < 0) return null;
        return videoItems[currentIndex + direction] || null;
    }

    function createVideoNavigationButton(direction, item) {
        const isPrevious = direction < 0;
        const button = document.createElement("button");
        button.type = "button";
        button.className = "settings-round-icon-button browser-video-nav-button";
        button.setAttribute("aria-label", isPrevious ? "Previous video" : "Next video");
        button.title = isPrevious ? "Previous video" : "Next video";
        button.disabled = !getAdjacentVideoItem(item, direction);
        const icon = document.createElement("span");
        icon.className = `icon ${isPrevious ? "icon-page-prev" : "icon-page-next"}`;
        icon.setAttribute("aria-hidden", "true");
        button.appendChild(icon);
        button.addEventListener("click", () => {
            const nextItem = getAdjacentVideoItem(item, direction);
            if (nextItem) openMediaItem(nextItem, activeTrigger);
        });
        return button;
    }

    function getFrameInset(frameStyles, startProperty, endProperty) {
        return (parseFloat(frameStyles[startProperty] || "0") || 0)
            + (parseFloat(frameStyles[endProperty] || "0") || 0);
    }

    function resizeViewerFrame(frame, intrinsicWidth, intrinsicHeight, fallbackRatio) {
        const ratio = intrinsicWidth > 0 && intrinsicHeight > 0
            ? intrinsicWidth / intrinsicHeight
            : fallbackRatio;
        const dialogStyles = window.getComputedStyle(dialog);
        const edgeInset = parseFloat(dialogStyles.getPropertyValue("--browser-media-viewer-edge-inset")) || 48;
        const frameStyles = window.getComputedStyle(frame);
        const horizontalInset = getFrameInset(frameStyles, "paddingLeft", "paddingRight")
            + getFrameInset(frameStyles, "borderLeftWidth", "borderRightWidth");
        const verticalInset = getFrameInset(frameStyles, "paddingTop", "paddingBottom")
            + getFrameInset(frameStyles, "borderTopWidth", "borderBottomWidth");
        const maxFrameWidth = Math.max(1, Math.min(1440, window.innerWidth - edgeInset));
        const maxFrameHeight = Math.max(1, Math.min(900, window.innerHeight - edgeInset));
        const maxMediaWidth = Math.max(1, maxFrameWidth - horizontalInset);
        const maxMediaHeight = Math.max(1, maxFrameHeight - verticalInset);
        let mediaWidth = maxMediaWidth;
        let mediaHeight = mediaWidth / ratio;
        if (mediaHeight > maxMediaHeight) {
            mediaHeight = maxMediaHeight;
            mediaWidth = mediaHeight * ratio;
        }
        dialog.style.width = `${Math.round(mediaWidth + horizontalInset)}px`;
        dialog.style.height = `${Math.round(mediaHeight + verticalInset)}px`;
    }

    function createImagePlayer(item) {
        const player = document.createElement("div");
        player.className = "browser-media-frame browser-image-player";
        player.setAttribute("data-image-player", "true");

        const image = document.createElement("img");
        image.className = "browser-dialog-media-element browser-dialog-image-element";
        image.alt = item.alt_text || item.title || item.filename;
        image.decoding = "async";
        image.src = item.media_url;
        player.appendChild(image);

        const resizePlayer = () => resizeViewerFrame(
            player,
            image.naturalWidth,
            image.naturalHeight,
            1,
        );
        image.addEventListener("load", resizePlayer, { once: true });
        resizePlayer();
        window.addEventListener("resize", resizePlayer, { passive: true });
        return { player, image, resizeHandler: resizePlayer };
    }

    function createVideoPlayer(item) {
        const player = document.createElement("div");
        player.className = "browser-media-frame browser-video-player";
        player.setAttribute("data-video-player", "true");

        const video = document.createElement("video");
        video.className = "browser-video-player-media";
        video.playsInline = true;
        video.setAttribute("playsinline", "");
        video.setAttribute("webkit-playsinline", "");
        video.preload = "metadata";
        video.controls = true;
        video.src = item.media_url;
        video.setAttribute("aria-label", "Video preview");

        const navigation = document.createElement("div");
        navigation.className = "browser-video-navigation";
        navigation.setAttribute("aria-label", "Video navigation");
        navigation.append(
            createVideoNavigationButton(-1, item),
            createVideoNavigationButton(1, item),
        );
        player.append(video, navigation);

        const resizePlayer = () => resizeViewerFrame(
            player,
            video.videoWidth,
            video.videoHeight,
            16 / 9,
        );
        video.addEventListener("loadedmetadata", resizePlayer, { once: true });
        resizePlayer();
        window.addEventListener("resize", resizePlayer, { passive: true });
        return { player, video, resizeHandler: resizePlayer };
    }

    function openDetails(trigger) {
        const card = trigger.closest("[data-media-id]");
        const item = mediaById.get(card?.dataset.mediaId);
        if (!item || !viewerMedia) return;
        openMediaItem(item, trigger);
    }

    function openMediaItem(item, trigger = activeTrigger) {
        if (!item || !viewerMedia) return;
        const isVideo = item.media_kind === "video";
        activeTrigger = trigger || activeTrigger;
        clearViewerMedia();
        dialog.classList.add("is-media-viewer");
        dialog.classList.toggle("is-image-lightbox", !isVideo);
        dialog.classList.toggle("is-video-player", isVideo);
        dialog.setAttribute("aria-label", isVideo ? "Video player" : "Image preview");
        const closeButton = dialog.querySelector("[data-dialog-close]");
        if (closeButton) closeButton.setAttribute("aria-label", isVideo ? "Close video player" : "Close image preview");
        setText(viewerTitle, item.title, item.filename);
        setText(viewerSource, item.source_label);
        setText(viewerCreator, item.creator || item.project_name);
        setText(viewerDate, item.captured_at_label);
        setText(viewerFilename, item.filename);
        setText(viewerSize, item.size_label || `${item.content_bytes || 0} bytes`);
        setText(viewerDescription, item.description || item.alt_text, "");
        if (viewerDescription) viewerDescription.hidden = !(item.description || item.alt_text);

        const externalUrl = validExternalUrl(item.source_url);
        const sourceLinkLabels = {
            x: "Open original post",
            chatgpt: "Open original conversation",
            grok: "Open original source",
        };
        if (viewerSourceLink) {
            viewerSourceLink.hidden = !externalUrl;
            if (externalUrl) {
                viewerSourceLink.href = externalUrl;
            } else {
                viewerSourceLink.removeAttribute("href");
            }
        }
        setText(viewerSourceLinkLabel, sourceLinkLabels[item.source] || "Open original source", "");
        setText(viewerSourceUrl, externalUrl, "");

        const mediaPlayer = isVideo ? createVideoPlayer(item) : createImagePlayer(item);
        viewerMediaResizeHandler = mediaPlayer.resizeHandler;
        if (isVideo) {
            viewerVideo = mediaPlayer.video;
            viewerVideo.addEventListener("error", () => {
                setText(viewerMedia, "Preview unavailable.");
            }, { once: true });
        } else {
            mediaPlayer.image.addEventListener("error", () => {
                setText(viewerMedia, "Preview unavailable.");
            }, { once: true });
        }
        viewerMedia.appendChild(mediaPlayer.player);

        if (!dialog.open && !dialog.hasAttribute("open")) {
            if (typeof dialog.showModal === "function") {
                dialog.showModal();
            } else {
                dialog.setAttribute("open", "");
            }
            if (closeButton) closeButton.focus();
        }
        dialog.classList.add("is-open");
        if (viewerMediaResizeHandler) {
            viewerMediaResizeHandler();
            window.requestAnimationFrame(viewerMediaResizeHandler);
        }
    }

    function closeDetails() {
        const wasOpen = dialog.open || dialog.hasAttribute("open") || dialog.classList.contains("is-open");
        clearViewerMedia();
        if (dialog.open && typeof dialog.close === "function") {
            dialog.close();
        } else {
            dialog.removeAttribute("open");
        }
        dialog.classList.remove("is-open");
        dialog.classList.remove("is-media-viewer", "is-image-lightbox", "is-video-player");
        dialog.removeAttribute("aria-label");
        const closeButton = dialog.querySelector("[data-dialog-close]");
        if (closeButton) closeButton.setAttribute("aria-label", "Close media details");
        if (wasOpen && activeTrigger && activeTrigger.isConnected) activeTrigger.focus();
        activeTrigger = null;
    }

    function setCardPreviewSource(card, item) {
        const preview = card.querySelector("[data-preview]");
        if (!preview) return;
        const source = item.preview_url || item.media_url;
        preview.dataset.mediaSrc = source || "";
        preview.removeAttribute("src");
        delete preview.dataset.previewLoaded;
        preview.hidden = false;
        setPreviewStatus(preview, "Loading preview");
        loadPreview(preview);
    }

    function setCardState(card, item) {
        const isDeleted = Boolean(item.is_deleted);
        card.dataset.deleted = String(isDeleted);
        card.classList.toggle("is-deleted", isDeleted);
        const deleteButton = card.querySelector("[data-media-delete]");
        const deletedBar = card.querySelector("[data-media-deleted-bar]");
        if (deleteButton) {
            deleteButton.hidden = isDeleted;
            deleteButton.disabled = false;
            deleteButton.setAttribute(
                "aria-label",
                `Delete locally and stop tracking ${item.title || item.filename}`,
            );
            deleteButton.title = "Delete locally and stop tracking";
        }
        if (deletedBar) {
            deletedBar.hidden = !isDeleted;
            const message = deletedBar.querySelector("[data-media-deleted-message]");
            if (message) {
                message.textContent = isDeleted ? "Deleted locally; future tracking stopped" : "";
            }
        }
        setCardPreviewSource(card, item);
    }

    async function updateMedia(card, action) {
        const item = mediaById.get(card.dataset.mediaId);
        if (!item) return;
        const button = action === "delete"
            ? card.querySelector("[data-media-delete]")
            : card.querySelector("[data-media-restore]");
        if (button) button.disabled = true;
        try {
            const response = await fetch(`/api/browser/media/${encodeURIComponent(item.id)}/${action}`, {
                method: "POST",
                headers: { "Accept": "application/json" },
            });
            const payload = await response.json();
            if (!response.ok || !payload.item) {
                throw new Error(payload.error || "The cache action failed.");
            }
            mediaById.set(payload.item.id, payload.item);
            setCardState(card, payload.item);
        } catch (error) {
            if (button) button.disabled = false;
            window.alert(error instanceof Error ? error.message : "The cache action failed.");
        }
    }

    mediaOpenButtons.forEach((button) => {
        button.addEventListener("click", () => openDetails(button));
    });
    mediaDeleteButtons.forEach((button) => {
        button.addEventListener("click", (event) => {
            event.stopPropagation();
            const card = button.closest("[data-media-id]");
            if (card) updateMedia(card, "delete");
        });
    });
    mediaRestoreButtons.forEach((button) => {
        button.addEventListener("click", (event) => {
            event.stopPropagation();
            const card = button.closest("[data-media-id]");
            if (card) updateMedia(card, "restore");
        });
    });
    closeButtons.forEach((button) => button.addEventListener("click", closeDetails));
    dialog.addEventListener("cancel", (event) => {
        event.preventDefault();
        closeDetails();
    });
    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && (dialog.open || dialog.hasAttribute("open"))) {
            event.preventDefault();
            closeDetails();
        }
    });
    dialog.addEventListener("click", (event) => {
        if (event.target === dialog) closeDetails();
    });
})();
