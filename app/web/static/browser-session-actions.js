/* Code version: v1.1.0-codex.1 */

(function initializeBrowserSessionActions() {
    "use strict";

    const root = document.querySelector("[data-browser-session-actions]");
    if (!(root instanceof HTMLElement)) return;

    const openOriginalButton = root.querySelector("[data-browser-session-open-original]");
    if (openOriginalButton instanceof HTMLButtonElement) {
        openOriginalButton.addEventListener("click", () => {
            const originalUrl = openOriginalButton.dataset.browserSessionOriginalUrl;
            if (originalUrl) window.open(originalUrl, "_blank", "noopener,noreferrer");
        });
    }

    root.querySelectorAll("[data-browser-session-refresh-url]").forEach((button) => {
        if (!(button instanceof HTMLButtonElement)) return;
        button.addEventListener("click", () => {
            const refreshUrl = button.dataset.browserSessionRefreshUrl;
            if (refreshUrl) window.location.assign(refreshUrl);
        });
    });

    root.querySelectorAll("[data-browser-session-download-url]").forEach((button) => {
        if (!(button instanceof HTMLButtonElement)) return;
        button.addEventListener("click", () => {
            const downloadUrl = button.dataset.browserSessionDownloadUrl;
            if (downloadUrl) window.location.assign(downloadUrl);
        });
    });
})();
