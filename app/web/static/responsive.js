/* Code version: v1.0.0-codex.1 */

(function initializeResponsiveContract() {
    "use strict";

    const root = document.documentElement;
    const fallbackBreakpoints = Object.freeze({
        compactContentMax: 600,
        sidebarOverlayMax: 900,
    });

    function readCssPixel(tokenName, fallback) {
        const rawValue = window.getComputedStyle(root).getPropertyValue(tokenName).trim();
        const value = Number.parseFloat(rawValue);
        return Number.isFinite(value) ? value : fallback;
    }

    const breakpoints = Object.freeze({
        compactContentMax: readCssPixel(
            "--responsive-breakpoint-compact-content-max",
            fallbackBreakpoints.compactContentMax,
        ),
        sidebarOverlayMax: readCssPixel(
            "--responsive-breakpoint-sidebar-overlay-max",
            fallbackBreakpoints.sidebarOverlayMax,
        ),
    });

    function media(name) {
        const value = breakpoints[name];
        if (!Number.isFinite(value)) {
            throw new Error(`Unknown responsive breakpoint: ${name}`);
        }
        return window.matchMedia(`(max-width: ${value}px)`);
    }

    window.CACHELIKES_RESPONSIVE = Object.freeze({
        breakpoints,
        media,
    });
})();
