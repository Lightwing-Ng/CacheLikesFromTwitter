/* Code version: v0.1.0-codex.1 */

(() => {
    "use strict";

    function setNoticeHidden(notice, isHidden) {
        notice.hidden = isHidden;
        notice.setAttribute("aria-hidden", String(isHidden));
    }

    function restoreNoticeState(notice) {
        const storageKey = notice.dataset.noticeStorageKey || "";
        if (!storageKey) return;
        try {
            if (window.sessionStorage.getItem(storageKey) === "true") {
                setNoticeHidden(notice, true);
            }
        } catch (_error) {
        }
    }

    function persistNoticeState(notice) {
        const storageKey = notice.dataset.noticeStorageKey || "";
        if (!storageKey) return;
        try {
            window.sessionStorage.setItem(storageKey, String(notice.hidden));
        } catch (_error) {
        }
    }

    document.querySelectorAll("[data-dismissible-notice]").forEach((notice) => {
        restoreNoticeState(notice);
        const closeButton = notice.querySelector(".notice-close");
        if (!(closeButton instanceof HTMLElement) || closeButton.dataset.noticeBound === "1") return;
        closeButton.dataset.noticeBound = "1";
        closeButton.addEventListener("click", () => {
            setNoticeHidden(notice, true);
            persistNoticeState(notice);
        });
    });
})();
