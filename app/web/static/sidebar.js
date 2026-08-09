/* Code version: v1.2.0-codex.1 */

(function initializeSidebar() {
    "use strict";

    const appShell = document.getElementById("app_shell");
    const appSidebar = document.querySelector(".sidebar");
    const sidebarToggle = document.getElementById("sidebar_toggle");
    const sidebarBackdrop = document.getElementById("sidebar_backdrop");
    const sidebarDock = document.querySelector(".sidebar-dock");
    const cacheSourceMenu = document.querySelector("[data-cache-source-menu]");
    const cacheSourceTrigger = cacheSourceMenu?.querySelector(".sidebar-dock-cache-trigger");
    const cacheSourceDropdown = cacheSourceMenu?.querySelector("[data-role='cache-source-menu']");
    const cacheSourceOptions = cacheSourceMenu
        ? Array.from(cacheSourceMenu.querySelectorAll("[data-cache-source-option]"))
        : [];
    if (!appShell || !appSidebar || !sidebarToggle) return;

    const mobileSidebarMedia = window.matchMedia("(max-width: 600px)");
    const sidebarMemoryKey = "cachelikes:sidebar-open";
    const sidebarMotionDurationMs = window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 1 : 500;
    let isSidebarOpen = true;
    let sidebarMotionResetTimer = 0;
    let dockPositionFrame = 0;
    let cacheSourceMenuCloseTimer = 0;

    function positionCacheSourceDropdown() {
        if (!cacheSourceMenu || !cacheSourceTrigger || !cacheSourceDropdown || cacheSourceDropdown.hidden) return;

        const viewportPadding = 12;
        const triggerRect = cacheSourceTrigger.getBoundingClientRect();
        const menuRect = cacheSourceMenu.getBoundingClientRect();
        const dropdownRect = cacheSourceDropdown.getBoundingClientRect();
        const maxLeft = Math.max(viewportPadding, window.innerWidth - dropdownRect.width - viewportPadding);
        const maxTop = Math.max(viewportPadding, window.innerHeight - dropdownRect.height - viewportPadding);
        const viewportLeft = Math.min(
            Math.max(triggerRect.right + viewportPadding, viewportPadding),
            maxLeft,
        );
        const viewportTop = Math.min(
            Math.max(triggerRect.top - dropdownRect.height - viewportPadding, viewportPadding),
            maxTop,
        );

        cacheSourceDropdown.style.left = `${Math.round(viewportLeft - menuRect.left)}px`;
        cacheSourceDropdown.style.top = `${Math.round(viewportTop - menuRect.top)}px`;
        cacheSourceDropdown.style.right = "auto";
        cacheSourceDropdown.style.bottom = "auto";
    }

    function scheduleCacheSourceMenuClose() {
        if (cacheSourceMenuCloseTimer) window.clearTimeout(cacheSourceMenuCloseTimer);
        cacheSourceMenuCloseTimer = window.setTimeout(() => {
            cacheSourceMenuCloseTimer = 0;
            setCacheSourceMenuOpen(false);
        }, 140);
    }

    function setCacheSourceMenuOpen(isOpen) {
        if (!cacheSourceMenu || !cacheSourceTrigger || !cacheSourceDropdown) return;

        if (cacheSourceMenuCloseTimer) {
            window.clearTimeout(cacheSourceMenuCloseTimer);
            cacheSourceMenuCloseTimer = 0;
        }

        const nextIsOpen = Boolean(isOpen);
        cacheSourceMenu.classList.toggle("is-cache-source-menu-open", nextIsOpen);
        cacheSourceTrigger.setAttribute("aria-expanded", String(nextIsOpen));
        cacheSourceDropdown.hidden = !nextIsOpen;
        if (nextIsOpen) {
            positionCacheSourceDropdown();
        } else {
            cacheSourceDropdown.style.removeProperty("left");
            cacheSourceDropdown.style.removeProperty("top");
            cacheSourceDropdown.style.removeProperty("right");
            cacheSourceDropdown.style.removeProperty("bottom");
        }
    }

    function focusCacheSourceOption(index) {
        const option = cacheSourceOptions[index];
        if (option instanceof HTMLElement) option.focus();
    }

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

        if (!isSidebarOpen) setCacheSourceMenuOpen(false);

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

    cacheSourceMenu?.addEventListener("mouseenter", () => {
        setCacheSourceMenuOpen(true);
    });

    cacheSourceMenu?.addEventListener("mouseleave", () => {
        scheduleCacheSourceMenuClose();
    });

    cacheSourceTrigger?.addEventListener("click", () => {
        setCacheSourceMenuOpen(!cacheSourceMenu?.classList.contains("is-cache-source-menu-open"));
    });

    cacheSourceTrigger?.addEventListener("keydown", (event) => {
        if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;

        event.preventDefault();
        setCacheSourceMenuOpen(true);
        focusCacheSourceOption(event.key === "ArrowDown" ? 0 : cacheSourceOptions.length - 1);
    });

    cacheSourceOptions.forEach((option, index) => {
        option.addEventListener("click", () => setCacheSourceMenuOpen(false));
        option.addEventListener("keydown", (event) => {
            if (event.key === "Escape") {
                event.preventDefault();
                setCacheSourceMenuOpen(false);
                cacheSourceTrigger?.focus();
                return;
            }
            if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;

            event.preventDefault();
            const nextIndex = (index + (event.key === "ArrowDown" ? 1 : -1) + cacheSourceOptions.length)
                % cacheSourceOptions.length;
            focusCacheSourceOption(nextIndex);
        });
    });

    document.addEventListener("click", (event) => {
        if (!cacheSourceMenu?.contains(event.target)) setCacheSourceMenuOpen(false);
    });

    document.addEventListener("keydown", (event) => {
        if (event.key !== "Escape" || !cacheSourceMenu?.classList.contains("is-cache-source-menu-open")) return;

        setCacheSourceMenuOpen(false);
        cacheSourceTrigger?.focus();
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
    window.addEventListener("resize", positionCacheSourceDropdown);
    window.addEventListener("orientationchange", () => {
        scheduleDockPosition();
        positionCacheSourceDropdown();
    });
    window.addEventListener("pageshow", scheduleDockPosition);
})();
