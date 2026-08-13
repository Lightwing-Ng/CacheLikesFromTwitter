/* Code version: v1.0.0-codex.1 */

(function initializeBrowserSessionActions() {
    "use strict";

    const root = document.querySelector("[data-browser-session-actions]");
    if (!(root instanceof HTMLElement)) return;

    const trigger = root.querySelector("[data-browser-session-actions-toggle]");
    const drawer = root.querySelector("[data-browser-session-actions-drawer]");
    if (!(trigger instanceof HTMLButtonElement) || !(drawer instanceof HTMLElement)) return;

    const setOpen = (isOpen) => {
        drawer.hidden = !isOpen;
        trigger.setAttribute("aria-expanded", isOpen ? "true" : "false");
        root.classList.toggle("is-open", isOpen);
    };

    trigger.addEventListener("click", () => {
        setOpen(drawer.hidden);
    });

    document.addEventListener("click", (event) => {
        if (drawer.hidden || !(event.target instanceof Node) || root.contains(event.target)) return;
        setOpen(false);
    });

    document.addEventListener("keydown", (event) => {
        if (event.key !== "Escape" || drawer.hidden) return;
        setOpen(false);
        trigger.focus();
    });

    drawer.querySelectorAll("a").forEach((link) => {
        link.addEventListener("click", () => setOpen(false));
    });
})();
