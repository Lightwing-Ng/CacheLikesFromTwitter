/* Code version: v1.6.0-codex.1 */

(() => {
    const SESSION_CACHE_PREFIX = "cachelikes:browser-session:v5:";
    const SESSION_CACHE_TTL_MS = 300_000;
    const SESSION_STALE_MAX_AGE_MS = 1_800_000;
    const statusRequests = new Map();

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

    function readCachedStatus(cacheKey) {
        const cachedPayload = readSessionValue(cacheKey);
        if (!cachedPayload) return null;
        try {
            const cachedEntry = JSON.parse(cachedPayload);
            if (
                !cachedEntry
                || typeof cachedEntry.cached_at !== "number"
                || !cachedEntry.payload
            ) return null;
            return {
                ageMs: Math.max(Date.now() - cachedEntry.cached_at, 0),
                payload: cachedEntry.payload,
            };
        } catch (_error) {
            return null;
        }
    }

    function requestBrowserStatus(platform, browserId, scope) {
        const requestScope = scope || "default";
        const requestKey = `${requestScope}:${platform}:${browserId}`;
        if (statusRequests.has(requestKey)) return statusRequests.get(requestKey);
        const query = new URLSearchParams({platform, browser: browserId});
        if (scope) query.set("scope", scope);
        const request = fetch(
            `/api/browser-session?${query.toString()}`,
            {cache: "no-store"},
        )
            .then(async (response) => {
                const payload = await response.json();
                if (!response.ok) {
                    throw new Error(payload.error || "Failed to probe browser session.");
                }
                return payload;
            })
            .finally(() => statusRequests.delete(requestKey));
        statusRequests.set(requestKey, request);
        return request;
    }

    function initBrowserSessionStatus(root, options = {}) {
        if (!root) return null;

        let platform = String(options.platform || root.dataset.browserSessionPlatform || "").trim().toLowerCase();
        const statusCard = root.querySelector('[data-role="browser-session-status"]');
        const statusAccount = root.querySelector('[data-role="browser-session-account"]');
        const statusMessage = root.querySelector('[data-role="browser-session-message"]');
        const statusSpinner = root.querySelector('[data-role="browser-session-spinner"]');
        const statusCheckmark = root.querySelector('[data-role="browser-session-checkmark"]');
        const hideReadyMessage = statusCard?.dataset.browserSessionHideReadyMessage === "true";
        const startButtonSelector = root.dataset.startButtonSelector || "";
        const requiresDownloadReady = root.dataset.requireDownloadReady === "true";
        const startButton = startButtonSelector ? document.querySelector(startButtonSelector) : null;
        const startButtonInitiallyDisabled = startButton ? startButton.disabled : false;
        const onStateChange = typeof options.onStateChange === "function" ? options.onStateChange : null;
        const scope = String(options.scope || root.dataset.browserSessionScope || "").trim().toLowerCase();
        let activeBrowser = "";
        let lastPayload = null;

        if (!platform || !statusCard || !statusAccount || !statusCheckmark) return null;

        function accountLabel(payload) {
            const platformLabel = String(root.dataset.browserSessionAccountLabel || "").trim();
            return platformLabel ? `${platformLabel} account` : (payload.account_name || "No signed-in account detected");
        }

        function notify(payload, browserId, state) {
            onStateChange?.(payload, browserId, state);
        }

        function setStartButtonReady(isReady) {
            if (requiresDownloadReady) {
                root.dataset.browserDownloadReady = String(isReady);
            }
            if (!requiresDownloadReady || !startButton || startButtonInitiallyDisabled) return;
            startButton.disabled = !isReady;
        }

        function hideStatusCheckmark() {
            statusCheckmark.hidden = true;
            statusCheckmark.removeAttribute("data-status-state");
        }

        function showStatusCheckmark(state) {
            statusCheckmark.dataset.statusState = state;
            statusCheckmark.hidden = false;
        }

        function setStatus(payload, browserId) {
            lastPayload = payload;
            statusCard.hidden = false;
            statusCard.removeAttribute("aria-busy");
            root.classList.remove("is-browser-status-loading", "is-browser-status-refreshing");
            const isReady = Boolean(payload.can_download);
            root.classList.toggle("is-browser-ready", isReady);
            statusAccount.textContent = accountLabel(payload);
            if (statusMessage) {
                statusMessage.textContent = payload.message || "";
                statusMessage.hidden = (hideReadyMessage && isReady) || !payload.message;
            }
            if (statusSpinner) statusSpinner.hidden = true;
            showStatusCheckmark(isReady ? "ready" : "error");
            setStartButtonReady(isReady);
            notify(payload, browserId, "ready");
        }

        function setLoadingState(browserId) {
            statusCard.hidden = false;
            statusCard.setAttribute("aria-busy", "true");
            root.classList.add("is-browser-status-loading");
            root.classList.remove("is-browser-ready", "is-browser-status-refreshing");
            statusAccount.textContent = "Checking signed-in account...";
            if (statusMessage) {
                statusMessage.textContent = "";
                statusMessage.hidden = true;
            }
            if (statusSpinner) statusSpinner.hidden = false;
            hideStatusCheckmark();
            setStartButtonReady(false);
            notify({can_download: false, account_name: "", message: "Checking signed-in account..."}, browserId, "loading");
        }

        function setRefreshingState(browserId) {
            statusCard.setAttribute("aria-busy", "true");
            root.classList.remove("is-browser-status-loading");
            root.classList.add("is-browser-status-refreshing");
            if (statusSpinner) statusSpinner.hidden = false;
            hideStatusCheckmark();
            notify(lastPayload || {can_download: false, account_name: "", message: "Refreshing signed-in account status..."}, browserId, "refreshing");
        }

        function clearStatus() {
            statusCard.hidden = true;
            statusCard.removeAttribute("aria-busy");
            root.classList.remove("is-browser-status-loading", "is-browser-status-refreshing", "is-browser-ready");
            if (statusMessage) {
                statusMessage.textContent = "";
                statusMessage.hidden = true;
            }
            if (statusSpinner) statusSpinner.hidden = true;
            hideStatusCheckmark();
            setStartButtonReady(false);
            notify(null, "", "cleared");
        }

        async function load(browserId, options = {}) {
            activeBrowser = browserId || "";
            if (!activeBrowser) {
                clearStatus();
                return;
            }

            const requestPlatform = platform;
            const cacheKey = `${SESSION_CACHE_PREFIX}${scope || "default"}:${requestPlatform}:${activeBrowser}`;
            const cachedStatus = readCachedStatus(cacheKey);
            const forceRefresh = options.force === true;
            if (!forceRefresh && cachedStatus && cachedStatus.ageMs < SESSION_STALE_MAX_AGE_MS) {
                setStatus(cachedStatus.payload, activeBrowser);
                if (cachedStatus.payload.can_download && cachedStatus.ageMs < SESSION_CACHE_TTL_MS) return;
                setRefreshingState(activeBrowser);
            } else {
                setLoadingState(activeBrowser);
            }

            try {
                const payload = await requestBrowserStatus(requestPlatform, activeBrowser, scope);
                writeSessionValue(cacheKey, JSON.stringify({cached_at: Date.now(), payload}));
                if (activeBrowser !== browserId || platform !== requestPlatform) return;
                setStatus(payload, browserId);
            } catch (error) {
                if (activeBrowser !== browserId || platform !== requestPlatform) return;
                setStatus({
                    browser_label: statusAccount.textContent,
                    account_name: "",
                    can_download: false,
                    message: error instanceof Error ? error.message : "Failed to probe browser session.",
                }, browserId);
            }
        }

        const controller = {
            setBrowser(browserId) {
                void load(String(browserId || "").trim().toLowerCase());
            },
            setPlatform(platformId) {
                const nextPlatform = String(platformId || "").trim().toLowerCase();
                if (nextPlatform === platform) return;
                platform = nextPlatform;
                root.dataset.browserSessionPlatform = nextPlatform;
                lastPayload = null;
                clearStatus();
                void load(activeBrowser);
            },
            refresh() {
                return load(activeBrowser, {force: true});
            },
            getBrowser() {
                return activeBrowser;
            },
        };
        controller.setBrowser(
            typeof options.browserId === "string"
                ? options.browserId
                : (typeof options.getBrowser === "function" ? options.getBrowser() : ""),
        );
        return controller;
    }

    window.CACHELIKES_BROWSER_SESSION_STATUS = {init: initBrowserSessionStatus};
})();
