/* Code version: v1.1.1-codex.1 */

(function initializeSettingsNavigation() {
    "use strict";

    const shell = document.querySelector("[data-settings-category-shell]");
    const categoryLinks = Array.from(document.querySelectorAll("[data-settings-category]"));
    const categoryPanels = Array.from(document.querySelectorAll("[data-settings-panel]"));
    if (!shell || !categoryLinks.length || !categoryPanels.length) return;

    const categories = new Set(categoryPanels.map((panel) => panel.dataset.settingsPanel));
    const defaultCategory = "browser";

    function categoryFromHash() {
        const hashCategory = window.location.hash.replace(/^#settings-/, "");
        return categories.has(hashCategory) ? hashCategory : defaultCategory;
    }

    function activateCategory(category, options = {}) {
        const nextCategory = categories.has(category) ? category : defaultCategory;
        const { updateHistory = false } = options;

        shell.dataset.activeCategory = nextCategory;
        categoryLinks.forEach((link) => {
            const isActive = link.dataset.settingsCategory === nextCategory;
            link.classList.toggle("is-active", isActive);
            if (isActive) {
                link.setAttribute("aria-current", "page");
            } else {
                link.removeAttribute("aria-current");
            }
        });
        categoryPanels.forEach((panel) => {
            const isActive = panel.dataset.settingsPanel === nextCategory;
            panel.classList.toggle("is-active", isActive);
            panel.hidden = !isActive;
        });
        if (updateHistory) {
            const nextHash = `#settings-${nextCategory}`;
            window.history.pushState(null, "", nextHash);
        }
    }

    categoryLinks.forEach((link) => {
        link.addEventListener("click", (event) => {
            event.preventDefault();
            activateCategory(link.dataset.settingsCategory, { updateHistory: true });
            if (window.CACHELIKES_RESPONSIVE.media("sidebarOverlayMax").matches) {
                window.setSidebarOpen?.(false, { animate: true });
            }
        });
    });

    window.addEventListener("hashchange", () => activateCategory(categoryFromHash()));
    document.documentElement.classList.add("settings-navigation-ready");
    activateCategory(categoryFromHash());
})();
