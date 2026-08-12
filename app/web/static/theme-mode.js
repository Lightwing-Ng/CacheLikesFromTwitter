/* Code version: v1.0.0-codex.1 */

(function initializeThemeMode() {
    "use strict";

    const storageKey = "cachelikes:theme-mode";
    const systemDarkMode = window.matchMedia("(prefers-color-scheme: dark)");

    function readPreference() {
        try {
            const stored = window.localStorage.getItem(storageKey);
            return stored === "light" || stored === "dark" ? stored : "system";
        } catch (_error) {
            return "system";
        }
    }

    function writePreference(mode) {
        try {
            window.localStorage.setItem(storageKey, mode);
        } catch (_error) {
        }
    }

    function effectiveMode(preference = readPreference()) {
        if (preference === "light" || preference === "dark") return preference;
        return systemDarkMode.matches ? "dark" : "light";
    }

    function applyPreference(preference) {
        if (preference === "light" || preference === "dark") {
            document.documentElement.setAttribute("data-theme-override", preference);
            return;
        }
        document.documentElement.removeAttribute("data-theme-override");
    }

    function syncToggle() {
        const toggle = document.getElementById("global_theme_toggle");
        if (!(toggle instanceof HTMLButtonElement)) return;
        const currentMode = effectiveMode();
        const nextMode = currentMode === "dark" ? "Light" : "Dark";
        toggle.dataset.effectiveTheme = currentMode;
        toggle.setAttribute("aria-label", `Switch to ${nextMode} mode`);
        toggle.setAttribute("title", `Switch to ${nextMode} mode`);
        toggle.setAttribute("aria-pressed", String(currentMode === "dark"));
    }

    function bindToggle() {
        const toggle = document.getElementById("global_theme_toggle");
        if (!(toggle instanceof HTMLButtonElement)) return;
        syncToggle();
        toggle.addEventListener("click", () => {
            const nextMode = effectiveMode() === "dark" ? "light" : "dark";
            writePreference(nextMode);
            applyPreference(nextMode);
            syncToggle();
        });
    }

    applyPreference(readPreference());
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", bindToggle, { once: true });
    } else {
        bindToggle();
    }
    systemDarkMode.addEventListener("change", () => {
        if (readPreference() === "system") syncToggle();
    });
})();
