/* Code version: v1.0.0-codex.2 */

(function initializeSidebar() {
    "use strict";

    const appShell = document.getElementById("app_shell");
    const appSidebar = document.querySelector(".sidebar");
    const sidebarToggle = document.getElementById("sidebar_toggle");
    const sidebarBackdrop = document.getElementById("sidebar_backdrop");
    const sidebarDock = document.querySelector(".sidebar-dock");
    if (!appShell || !appSidebar || !sidebarToggle) return;

    const mobileSidebarMedia = window.matchMedia("(max-width: 600px)");
    const sidebarMemoryKey = "cachelikes:sidebar-open";
    const sidebarMotionDurationMs = window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 1 : 500;
    let isSidebarOpen = true;
    let sidebarMotionResetTimer = 0;
    let dockPositionFrame = 0;

    function readSidebarMemory() {
        try {
            const storedValue = window.sessionStorage.getItem(sidebarMemoryKey);
            if (storedValue === "true") return true;
            if (storedValue === "false") return false;
        } catch (_error) {
        }
        return !mobileSidebarMedia.matches;
    }

    function writeSidebarMemory(value) {
        try {
            window.sessionStorage.setItem(sidebarMemoryKey, String(Boolean(value)));
        } catch (_error) {
        }
    }

    function setSidebarMotionState(direction) {
        if (sidebarMotionResetTimer) {
            window.clearTimeout(sidebarMotionResetTimer);
            sidebarMotionResetTimer = 0;
        }

        appShell.classList.remove("is-sidebar-animating", "is-sidebar-opening", "is-sidebar-closing");
        void appShell.offsetWidth;
        if (!direction) return;

        appShell.classList.add(
            "is-sidebar-animating",
            direction === "opening" ? "is-sidebar-opening" : "is-sidebar-closing",
        );
        sidebarMotionResetTimer = window.setTimeout(() => {
            appShell.classList.remove("is-sidebar-animating", "is-sidebar-opening", "is-sidebar-closing");
            sidebarMotionResetTimer = 0;
        }, sidebarMotionDurationMs);
    }

    function scheduleDockPosition() {
        if (!sidebarDock) return;
        if (dockPositionFrame) window.cancelAnimationFrame(dockPositionFrame);
        dockPositionFrame = window.requestAnimationFrame(() => {
            dockPositionFrame = 0;
            if (mobileSidebarMedia.matches) {
                sidebarDock.style.left = "";
                return;
            }
            const sidebarRect = appSidebar.getBoundingClientRect();
            sidebarDock.style.left = `${Math.round(sidebarRect.left + sidebarRect.width / 2)}px`;
        });
    }

    function applySidebarState(nextIsOpen, options = {}) {
        const { persist = true, animate = false } = options;
        const wasOpen = isSidebarOpen;
        isSidebarOpen = Boolean(nextIsOpen);

        document.documentElement.classList.toggle("sidebar-memory-collapsed", !isSidebarOpen);
        sidebarToggle.setAttribute("aria-hidden", "false");
        sidebarToggle.setAttribute("aria-expanded", String(isSidebarOpen));
        appShell.classList.toggle("is-sidebar-open", isSidebarOpen);
        appShell.classList.toggle("is-sidebar-collapsed", !isSidebarOpen);

        appSidebar.hidden = false;
        appSidebar.style.display = "";
        appSidebar.setAttribute("aria-hidden", String(!isSidebarOpen));
        if ("inert" in appSidebar) appSidebar.inert = !isSidebarOpen;

        if (sidebarBackdrop) {
            const shouldShowBackdrop = mobileSidebarMedia.matches && isSidebarOpen;
            sidebarBackdrop.hidden = !shouldShowBackdrop;
            sidebarBackdrop.setAttribute("aria-hidden", String(!shouldShowBackdrop));
            if ("inert" in sidebarBackdrop) sidebarBackdrop.inert = !shouldShowBackdrop;
            sidebarBackdrop.tabIndex = shouldShowBackdrop ? 0 : -1;
        }

        if (animate && wasOpen !== isSidebarOpen) {
            setSidebarMotionState(isSidebarOpen ? "opening" : "closing");
            window.setTimeout(scheduleDockPosition, sidebarMotionDurationMs + 20);
        }
        if (persist) writeSidebarMemory(isSidebarOpen);
        scheduleDockPosition();
    }

    window.setSidebarOpen = function setSidebarOpen(isOpen, options = {}) {
        applySidebarState(isOpen, options);
    };

    applySidebarState(readSidebarMemory(), { persist: false });

    sidebarToggle.addEventListener("click", () => {
        applySidebarState(!isSidebarOpen, { animate: true });
    });

    sidebarBackdrop?.addEventListener("click", () => {
        if (!mobileSidebarMedia.matches || !isSidebarOpen) return;
        applySidebarState(false);
    });

    const handleViewportChange = () => {
        applySidebarState(isSidebarOpen, { persist: false });
    };
    if (typeof mobileSidebarMedia.addEventListener === "function") {
        mobileSidebarMedia.addEventListener("change", handleViewportChange);
    } else if (typeof mobileSidebarMedia.addListener === "function") {
        mobileSidebarMedia.addListener(handleViewportChange);
    }

    window.addEventListener("resize", scheduleDockPosition);
    window.addEventListener("orientationchange", scheduleDockPosition);
    window.addEventListener("pageshow", scheduleDockPosition);
})();
