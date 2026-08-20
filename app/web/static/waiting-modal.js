/* Code version: v1.1.0-codex.1 */

(function initializeWaitingModal() {
    "use strict";

    const modal = document.getElementById("cache_wait_modal");
    if (!modal) return;

    const title = document.getElementById("cache_wait_modal_title");
    const copy = document.getElementById("cache_wait_modal_copy");
    const closeButton = modal.querySelector("[data-wait-modal-close]");
    const activeWaits = new Map();
    let focusReturnTarget = null;

    function normalizedText(value, fallback) {
        const text = typeof value === "string" ? value.trim() : "";
        return text || fallback;
    }

    function optionsFromElement(element) {
        if (!(element instanceof HTMLElement)) return null;
        const titleText = element.dataset.waitTitle;
        const copyText = element.dataset.waitCopy;
        if (!titleText && !copyText) return null;
        return {
            title: normalizedText(titleText, "Working locally"),
            copy: normalizedText(copyText, "Please wait while the app completes your request on this computer."),
        };
    }

    function renderLatestWait() {
        const latestWait = Array.from(activeWaits.values()).at(-1);
        if (!latestWait) {
            modal.hidden = true;
            return;
        }

        if (title) title.textContent = latestWait.title;
        if (copy) copy.textContent = latestWait.copy;
        modal.hidden = false;
    }

    function begin(options = {}) {
        const waitToken = Symbol("cache-wait");
        const delay = Math.max(0, Number(options.delay) || 0);
        const waitOptions = {
            title: normalizedText(options.title, "Working locally"),
            copy: normalizedText(options.copy, "Please wait while the app completes your request on this computer."),
        };
        let timeoutId = 0;
        let finished = false;

        const reveal = () => {
            if (finished) return;
            activeWaits.set(waitToken, waitOptions);
            renderLatestWait();
        };

        if (delay > 0) {
            timeoutId = window.setTimeout(reveal, delay);
        } else {
            reveal();
        }

        return {
            finish() {
                if (finished) return;
                finished = true;
                if (timeoutId) window.clearTimeout(timeoutId);
                activeWaits.delete(waitToken);
                renderLatestWait();
            },
        };
    }

    function show(options = {}) {
        return begin({ ...options, delay: 0 });
    }

    function hide() {
        activeWaits.clear();
        renderLatestWait();
    }

    function closeModal() {
        hide();
        if (focusReturnTarget instanceof HTMLElement && focusReturnTarget.isConnected) {
            focusReturnTarget.focus({ preventScroll: true });
        }
        focusReturnTarget = null;
    }

    window.CacheWaitModal = Object.freeze({ begin, show, hide });

    closeButton?.addEventListener("click", closeModal);
    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && !modal.hidden) {
            event.preventDefault();
            closeModal();
        }
    });

    document.addEventListener("submit", (event) => {
        if (event.defaultPrevented || !(event.target instanceof HTMLFormElement)) return;
        const submitter = event.submitter instanceof HTMLElement ? event.submitter : null;
        const options = optionsFromElement(submitter) || optionsFromElement(event.target);
        if (!options) return;
        focusReturnTarget = submitter || document.activeElement;
        show(options);
    });

    document.addEventListener("click", (event) => {
        if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
            return;
        }
        const link = event.target instanceof Element
            ? event.target.closest("a[data-wait-title], a[data-wait-copy]")
            : null;
        const options = optionsFromElement(link);
        if (!options) return;
        focusReturnTarget = link;
        show(options);
    });
})();
