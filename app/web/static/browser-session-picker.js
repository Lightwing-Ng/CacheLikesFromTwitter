/* Code version: v1.3.0-gpt5.4.1 */

(() => {
    const SESSION_CACHE_PREFIX = "cachelikes:browser-session:v2:";
    const SESSION_CACHE_TTL_MS = 30_000;

    function readSessionValue(key) {
        try {
            return window.sessionStorage.getItem(key);
        } catch (_error) {
            return null;
        }
    }

    function writeSessionValue(key, value) {
        try {
            window.sessionStorage.setItem(key, value);
        } catch (_error) {
        }
    }

    function closeOtherMenus(activePanel) {
        document.querySelectorAll("[data-browser-session-panel]").forEach((panel) => {
            if (panel !== activePanel) {
                panel.classList.remove("is-browser-menu-open");
                const trigger = panel.querySelector('[data-role="browser-picker-trigger"]');
                if (trigger) {
                    trigger.setAttribute("aria-expanded", "false");
                }
            }
        });
    }

    function initBrowserSessionPanel(panel) {
        const platform = panel.dataset.platform;
        const selectionStorageKey = panel.dataset.selectionStorageKey;
        const trigger = panel.querySelector('[data-role="browser-picker-trigger"]');
        const selectedLabel = panel.querySelector('[data-role="browser-picker-selected-label"]');
        const selectedIcon = panel.querySelector('[data-role="browser-picker-selected-icon"]');
        const selectedIconShell = panel.querySelector('[data-role="browser-picker-selected-icon-shell"]');
        const statusCard = panel.querySelector('[data-role="browser-session-status"]');
        const statusAccount = panel.querySelector('[data-role="browser-session-account"]');
        const statusCheckmark = panel.querySelector('[data-role="browser-session-checkmark"]');
        const optionButtons = Array.from(panel.querySelectorAll("[data-browser-option]"));

        let activeBrowser = "";

        function setMenuOpen(isOpen) {
            panel.classList.toggle("is-browser-menu-open", isOpen);
            trigger.setAttribute("aria-expanded", String(isOpen));
            if (isOpen) {
                closeOtherMenus(panel);
            }
        }

        function setSelectedBrowser(browserId) {
            activeBrowser = browserId || "";
            optionButtons.forEach((button) => {
                button.classList.toggle("is-selected", button.dataset.browserOption === activeBrowser);
                button.setAttribute("aria-selected", String(button.dataset.browserOption === activeBrowser));
            });

            const selectedButton = optionButtons.find((button) => button.dataset.browserOption === activeBrowser);
            if (!selectedButton) {
                selectedLabel.textContent = "Select browser";
                selectedIcon.removeAttribute("src");
                selectedIcon.alt = "";
                selectedIconShell.hidden = true;
                return;
            }

            selectedLabel.textContent = selectedButton.dataset.browserLabel;
            selectedIcon.src = selectedButton.dataset.browserIcon;
            selectedIcon.alt = `${selectedButton.dataset.browserLabel} icon`;
            selectedIconShell.hidden = false;
        }

        function setStatus(payload) {
            statusCard.hidden = false;
            panel.classList.remove("is-browser-status-loading");
            panel.classList.toggle("is-browser-ready", Boolean(payload.can_download));
            statusAccount.textContent = payload.account_name || "No signed-in account detected";
            statusCheckmark.hidden = !Boolean(payload.can_download);
        }

        function setLoadingState() {
            statusCard.hidden = false;
            panel.classList.add("is-browser-status-loading");
            panel.classList.remove("is-browser-ready");
            statusAccount.textContent = "Checking signed-in account...";
            statusCheckmark.hidden = true;
        }

        async function loadBrowserStatus(browserId) {
            if (!browserId) {
                statusCard.hidden = true;
                panel.classList.remove("is-browser-status-loading", "is-browser-ready");
                return;
            }

            const cacheKey = `${SESSION_CACHE_PREFIX}${platform}:${browserId}`;
            const cachedPayload = readSessionValue(cacheKey);
            if (cachedPayload) {
                try {
                    const cachedEntry = JSON.parse(cachedPayload);
                    if (
                        cachedEntry
                        && typeof cachedEntry.cached_at === "number"
                        && (Date.now() - cachedEntry.cached_at) < SESSION_CACHE_TTL_MS
                        && cachedEntry.payload
                    ) {
                        setStatus(cachedEntry.payload);
                        return;
                    }
                } catch (_error) {
                }
            }

            setLoadingState();
            try {
                const response = await fetch(
                    `/api/browser-session?platform=${encodeURIComponent(platform)}&browser=${encodeURIComponent(browserId)}`,
                    { cache: "no-store" },
                );
                const payload = await response.json();
                if (!response.ok) {
                    throw new Error(payload.error || "Failed to probe browser session.");
                }
                writeSessionValue(cacheKey, JSON.stringify({
                    cached_at: Date.now(),
                    payload,
                }));
                setStatus(payload);
            } catch (error) {
                setStatus({
                    browser_label: selectedLabel.textContent,
                    account_name: "",
                    can_download: false,
                    message: error instanceof Error ? error.message : "Failed to probe browser session.",
                });
            }
        }

        trigger.addEventListener("click", () => {
            setMenuOpen(!panel.classList.contains("is-browser-menu-open"));
        });

        optionButtons.forEach((button) => {
            button.addEventListener("click", () => {
                const browserId = button.dataset.browserOption || "";
                setSelectedBrowser(browserId);
                setMenuOpen(false);
                writeSessionValue(selectionStorageKey, browserId);
                void loadBrowserStatus(browserId);
            });
        });

        document.addEventListener("click", (event) => {
            if (!panel.contains(event.target)) {
                setMenuOpen(false);
            }
        });

        document.addEventListener("keydown", (event) => {
            if (event.key === "Escape") {
                setMenuOpen(false);
            }
        });

        const storedSelection = readSessionValue(selectionStorageKey) || "";
        if (storedSelection) {
            setSelectedBrowser(storedSelection);
            void loadBrowserStatus(storedSelection);
        } else {
            setSelectedBrowser("");
            statusCard.hidden = true;
        }
    }

    document.addEventListener("DOMContentLoaded", () => {
        document.querySelectorAll("[data-browser-session-panel]").forEach((panel) => {
            initBrowserSessionPanel(panel);
        });
    });
})();
