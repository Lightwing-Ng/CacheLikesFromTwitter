/* Code version: v1.0.1-codex.1 */

(function initializeBrowserSessionMessages() {
    "use strict";

    const toggleButtons = Array.from(document.querySelectorAll("[data-browser-session-message-toggle]"));
    if (!toggleButtons.length) return;

    let resizeFrame = 0;

    function sourceFor(button) {
        const sourceId = button.getAttribute("aria-controls") || "";
        return sourceId ? document.getElementById(sourceId) : null;
    }

    function shellFor(button) {
        return button.closest(".browser-session-table-message-shell");
    }

    function setExpanded(button, nextExpanded) {
        const shell = shellFor(button);
        if (!shell) return;

        const messageNumber = button.dataset.browserSessionMessageNumber || "";
        const action = nextExpanded ? "Collapse" : "Expand";
        shell.classList.toggle("is-expanded", nextExpanded);
        button.setAttribute("aria-expanded", String(nextExpanded));
        button.setAttribute("aria-label", `${action} message ${messageNumber}`.trim());
        button.title = `${action} message`;
    }

    function updateOverflowState(button) {
        const source = sourceFor(button);
        const shell = shellFor(button);
        if (!(source instanceof HTMLElement) || !(shell instanceof HTMLElement)) return;

        if (button.getAttribute("aria-expanded") === "true") {
            shell.classList.add("is-collapsible");
            button.hidden = false;
            return;
        }

        const isCollapsible = source.scrollHeight > source.clientHeight + 1;
        shell.classList.toggle("is-collapsible", isCollapsible);
        button.hidden = !isCollapsible;
    }

    function updateAllOverflowStates() {
        toggleButtons.forEach(updateOverflowState);
    }

    function scheduleOverflowUpdate() {
        if (resizeFrame) return;
        resizeFrame = window.requestAnimationFrame(() => {
            resizeFrame = 0;
            updateAllOverflowStates();
        });
    }

    toggleButtons.forEach((button) => {
        button.addEventListener("click", () => {
            setExpanded(button, button.getAttribute("aria-expanded") !== "true");
            scheduleOverflowUpdate();
        });
    });

    if ("ResizeObserver" in window) {
        const observer = new ResizeObserver(scheduleOverflowUpdate);
        toggleButtons.forEach((button) => {
            const source = sourceFor(button);
            if (source instanceof HTMLElement) observer.observe(source);
        });
    }

    if ("MutationObserver" in window) {
        const observer = new MutationObserver(scheduleOverflowUpdate);
        toggleButtons.forEach((button) => {
            const source = sourceFor(button);
            if (source instanceof HTMLElement) {
                observer.observe(source, {childList: true, characterData: true, subtree: true});
            }
        });
    }

    window.addEventListener("resize", scheduleOverflowUpdate, { passive: true });
    window.requestAnimationFrame(updateAllOverflowStates);
    document.fonts?.ready?.then(scheduleOverflowUpdate).catch(() => {});
})();
