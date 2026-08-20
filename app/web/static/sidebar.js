/* Code version: v1.18.0-codex.1 */

(function initializeSidebar() {
    "use strict";

    const appShell = document.getElementById("app_shell");
    const appSidebar = document.querySelector(".sidebar");
    const sidebarToggle = document.getElementById("sidebar_toggle");
    const sidebarBackdrop = document.getElementById("sidebar_backdrop");
    const sidebarDock = document.querySelector(".sidebar-dock");
    if (!appShell || !appSidebar || !sidebarToggle) return;

    const sidebarOverlayMedia = window.CACHELIKES_RESPONSIVE.media("sidebarOverlayMax");
    const sidebarMemoryKey = "cachelikes:sidebar-open";
    const dockLocationMemoryPrefix = "cachelikes:dock-location:v1:";
    const dockSections = new Set(["agent", "cache", "local-resources", "settings"]);
    const cacheSectionPaths = new Set(["/cache/x", "/cache/grok", "/cache/chatgpt", "/cache/gemini"]);
    const legacyCachePathMap = new Map([
        ["/", "/cache/x"],
        ["/grok", "/cache/grok"],
        ["/chatgpt", "/cache/chatgpt"],
        ["/gemini", "/cache/gemini"],
    ]);
    const localResourceFilterNames = ["view", "source", "kind", "q", "sort", "session_view"];
    const agentRoutePattern = /^\/agent\/(?:safari\/chatgpt|(?:edge|chrome)\/(?:chatgpt|gemini|grok))$/;
    const settingsCategoryPattern = /^#settings-(browser|downloads|chatgpt|cloud|maintenance)$/;
    const dockLinks = sidebarDock
        ? Array.from(sidebarDock.querySelectorAll("[data-dock-section], [data-section-link]"))
        : [];
    const sidebarMotionDurationMs = window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 1 : 500;
    let isSidebarOpen = sidebarToggle.getAttribute("aria-expanded") === "true";
    let sidebarMotionResetTimer = 0;
    let dockPositionFrame = 0;

    function readSidebarMemory() {
        try {
            const storedValue = window.sessionStorage.getItem(sidebarMemoryKey);
            if (storedValue === "true") return true;
            if (storedValue === "false") return false;
        } catch (_error) {
        }
        return !sidebarOverlayMedia.matches;
    }

    function writeSidebarMemory(value) {
        try {
            window.sessionStorage.setItem(sidebarMemoryKey, String(Boolean(value)));
        } catch (_error) {
        }
    }

    function dockLocationMemoryKey(section) {
        return `${dockLocationMemoryPrefix}${section}`;
    }

    function normalizeDockLocation(section, value) {
        if (!dockSections.has(section) || !value) return "";

        let targetUrl;
        try {
            targetUrl = new URL(value, window.location.origin);
        } catch (_error) {
            return "";
        }
        if (targetUrl.origin !== window.location.origin) return "";

        if (section === "agent") {
            return targetUrl.pathname === "/agent" || agentRoutePattern.test(targetUrl.pathname)
                ? `${targetUrl.pathname}${targetUrl.search}${targetUrl.hash}`
                : "";
        }
        if (section === "cache") {
            // Migrate the previous Cache destination, which incorrectly pointed
            // at the local browser, to the first cache source page.
            if (targetUrl.pathname === "/browser") return "/cache/chatgpt";
            const normalizedPath = legacyCachePathMap.get(targetUrl.pathname) || targetUrl.pathname;
            return cacheSectionPaths.has(normalizedPath) ? normalizedPath : "";
        }
        if (section === "settings") {
            if (targetUrl.pathname !== "/settings") return "";
            const categoryHash = settingsCategoryPattern.test(targetUrl.hash) ? targetUrl.hash : "";
            return `${targetUrl.pathname}${categoryHash}`;
        }
        if (targetUrl.pathname !== "/browser") return "";

        const normalizedUrl = new URL(targetUrl.pathname, window.location.origin);
        localResourceFilterNames.forEach((name) => {
            if (targetUrl.searchParams.has(name)) {
                normalizedUrl.searchParams.set(name, targetUrl.searchParams.get(name) || "");
            }
        });
        return `${normalizedUrl.pathname}${normalizedUrl.search}`;
    }

    function readDockLocation(section) {
        try {
            return normalizeDockLocation(
                section,
                window.sessionStorage.getItem(dockLocationMemoryKey(section)) || "",
            );
        } catch (_error) {
            return "";
        }
    }

    function writeDockLocation(section, location) {
        const normalizedLocation = normalizeDockLocation(section, location);
        if (!normalizedLocation) return;
        try {
            window.sessionStorage.setItem(dockLocationMemoryKey(section), normalizedLocation);
        } catch (_error) {
        }
    }

    function dockSectionForLink(link) {
        const explicitSection = link?.dataset.dockSection || "";
        if (dockSections.has(explicitSection)) return explicitSection;
        const legacySection = link?.dataset.sectionLink || "";
        if (["llm", "local-resources", "settings"].includes(legacySection)) return legacySection;
        return legacySection ? "cache" : "";
    }

    function activeDockSection() {
        const activeLink = dockLinks.find((link) => link.getAttribute("aria-current") === "page");
        const section = dockSectionForLink(activeLink);
        return dockSections.has(section) ? section : "";
    }

    function currentLocalResourcesLocation() {
        const filterForm = document.querySelector(".browser-filter-form");
        const browserUrl = new URL("/browser", window.location.origin);
        if (!(filterForm instanceof HTMLFormElement)) return browserUrl.pathname;

        localResourceFilterNames.forEach((name) => {
            const field = filterForm.elements.namedItem(name);
            if (field instanceof RadioNodeList) {
                browserUrl.searchParams.set(name, field.value);
            } else if (field instanceof HTMLInputElement || field instanceof HTMLSelectElement) {
                browserUrl.searchParams.set(name, field.value);
            }
        });
        return `${browserUrl.pathname}${browserUrl.search}`;
    }

    function currentSettingsLocation() {
        if (settingsCategoryPattern.test(window.location.hash)) {
            return `${window.location.pathname}${window.location.hash}`;
        }
        const activeCategory = document.querySelector('[data-settings-category][aria-current="page"]');
        const category = activeCategory?.dataset.settingsCategory || "";
        return category ? `/settings#settings-${category}` : "/settings";
    }

    function currentDockLocation(section) {
        if (section === "agent") {
            return window.location.pathname === "/agent" || agentRoutePattern.test(window.location.pathname)
                ? `${window.location.pathname}${window.location.search}${window.location.hash}`
                : "/agent";
        }
        if (section === "cache") {
            const normalizedPath = legacyCachePathMap.get(window.location.pathname) || window.location.pathname;
            return cacheSectionPaths.has(normalizedPath) ? normalizedPath : "/cache/chatgpt";
        }
        if (section === "local-resources") return currentLocalResourcesLocation();
        if (section === "settings") return currentSettingsLocation();
        return "";
    }

    function dockSectionForCurrentPath() {
        const normalizedPath = legacyCachePathMap.get(window.location.pathname) || window.location.pathname;
        if (normalizedPath === "/agent" || agentRoutePattern.test(window.location.pathname)) return "agent";
        if (cacheSectionPaths.has(normalizedPath)) return "cache";
        if (window.location.pathname === "/browser") return "local-resources";
        if (window.location.pathname === "/settings") return "settings";
        return "";
    }

    function syncDockActiveState() {
        const activeSection = dockSectionForCurrentPath();
        if (!activeSection) return;
        dockLinks.forEach((link) => {
            const isActive = dockSectionForLink(link) === activeSection;
            link.classList.toggle("is-active", isActive);
            if (isActive) {
                link.setAttribute("aria-current", "page");
            } else {
                link.removeAttribute("aria-current");
            }
        });
    }

    function syncDockDestinations() {
        dockLinks.forEach((link) => {
            const section = dockSectionForLink(link);
            const rememberedLocation = readDockLocation(section);
            if (rememberedLocation) link.href = rememberedLocation;
        });
    }

    function rememberCurrentDockLocation() {
        const section = activeDockSection();
        if (!section) return;
        writeDockLocation(section, currentDockLocation(section));
        syncDockDestinations();
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
            if (sidebarOverlayMedia.matches) {
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
            const shouldShowBackdrop = sidebarOverlayMedia.matches && isSidebarOpen;
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
    syncDockActiveState();
    rememberCurrentDockLocation();
    syncDockDestinations();

    sidebarDock?.addEventListener("click", (event) => {
        const dockLink = event.target instanceof Element
            ? event.target.closest("[data-dock-section], [data-section-link]")
            : null;
        if (!(dockLink instanceof HTMLAnchorElement)) return;
        rememberCurrentDockLocation();
        const rememberedLocation = readDockLocation(dockSectionForLink(dockLink));
        if (rememberedLocation) dockLink.href = rememberedLocation;
    });

    const localResourceFilterForm = document.querySelector(".browser-filter-form");
    localResourceFilterForm?.addEventListener("input", rememberCurrentDockLocation);
    localResourceFilterForm?.addEventListener("change", rememberCurrentDockLocation);

    document.addEventListener("click", (event) => {
        const categoryLink = event.target instanceof Element
            ? event.target.closest("[data-settings-category]")
            : null;
        if (!categoryLink) return;
        window.requestAnimationFrame(rememberCurrentDockLocation);
    });

    window.addEventListener("hashchange", rememberCurrentDockLocation);
    window.addEventListener("popstate", rememberCurrentDockLocation);

    sidebarToggle.addEventListener("click", () => {
        applySidebarState(!isSidebarOpen, { animate: true });
    });

    sidebarBackdrop?.addEventListener("click", () => {
        if (!sidebarOverlayMedia.matches || !isSidebarOpen) return;
        applySidebarState(false);
    });

    const handleViewportChange = () => {
        applySidebarState(isSidebarOpen, { persist: false });
    };
    if (typeof sidebarOverlayMedia.addEventListener === "function") {
        sidebarOverlayMedia.addEventListener("change", handleViewportChange);
    } else if (typeof sidebarOverlayMedia.addListener === "function") {
        sidebarOverlayMedia.addListener(handleViewportChange);
    }

    window.addEventListener("resize", scheduleDockPosition);
    window.addEventListener("orientationchange", () => {
        scheduleDockPosition();
    });
    window.addEventListener("pageshow", () => {
        scheduleDockPosition();
        syncDockActiveState();
        rememberCurrentDockLocation();
    });
})();
