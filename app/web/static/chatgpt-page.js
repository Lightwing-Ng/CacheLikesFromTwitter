/* Code version: v1.2.1-codex.1 */

(() => {
    "use strict";

    const contentModeStorageKey = "cachelikes:browser-content-mode:v1";
    const contentModeControl = document.querySelector("[data-cache-content-mode]");
    const contentModeInput = document.querySelector("[data-chatgpt-content-mode-input]");
    const mediaConfig = document.querySelector("[data-chatgpt-media-config]");

    if (!contentModeInput || !mediaConfig) return;

    function readContentMode() {
        try {
            return window.sessionStorage.getItem(contentModeStorageKey) === "media" ? "media" : "text";
        } catch (_error) {
            return "text";
        }
    }

    function applyContentMode(mode) {
        const normalizedMode = mode === "media" ? "media" : "text";
        contentModeInput.value = normalizedMode;
        mediaConfig.hidden = normalizedMode === "text";
        mediaConfig.querySelectorAll("input, select, textarea, button").forEach((control) => {
            control.disabled = normalizedMode === "text";
        });
        if (contentModeControl) {
            const options = Array.from(
                contentModeControl.querySelectorAll("[data-cache-content-mode-option]"),
            );
            const activeIndex = options.findIndex(
                (option) => option.dataset.cacheContentModeOption === normalizedMode,
            );
            contentModeControl.dataset.segmentedActiveIndex = String(Math.max(activeIndex, 0));
            options.forEach((option) => {
                const isActive = option.dataset.cacheContentModeOption === normalizedMode;
                option.classList.toggle("is-active", isActive);
                option.setAttribute("aria-checked", String(isActive));
            });
            window.CACHELIKES_SEGMENTED_CONTROLS?.sync(contentModeControl);
        }
        try {
            window.sessionStorage.setItem(contentModeStorageKey, normalizedMode);
        } catch (_error) {
        }
    }

    applyContentMode(readContentMode());
    contentModeControl?.addEventListener("click", (event) => {
        const option = event.target.closest("[data-cache-content-mode-option]");
        if (!option || !contentModeControl.contains(option)) return;
        event.preventDefault();
        applyContentMode(option.dataset.cacheContentModeOption);
    });
})();
