/* Code version: v1.0.0-codex.1 */

(() => {
    "use strict";

    const page = document.querySelector("[data-cache-page]");
    if (!page) return;

    const sourceKey = page.dataset.cacheSource || "cache";
    const sourceLabel = page.dataset.cacheSourceLabel || "Cache";
    const statusUrl = page.dataset.cacheStatusUrl || "";
    const progressStrategyName = page.dataset.cacheProgressStrategy || "queue";
    const statusBannerStorageKey = page.dataset.cacheBannerStorageKey || `cachelikes:${sourceKey}:status-banner-dismissed`;
    const recentEventsPageSize = 12;
    const terminalPhases = new Set(["finished", "completed", "success", "stopped"]);
    const numberFormatter = new Intl.NumberFormat("en-US");

    const phaseChip = document.getElementById("phase_chip");
    const bannerPhase = document.getElementById("banner_phase");
    const bannerMessage = document.getElementById("banner_message");
    const statusBanner = document.getElementById("status_banner");
    const statusBannerDismiss = document.getElementById("status_banner_dismiss");
    const phaseValue = document.getElementById("phase_value");
    const startButton = document.getElementById("start_button");
    const stopButton = document.getElementById("stop_button");
    const browserSessionPanel = document.querySelector("[data-browser-session-panel]");
    const statusProgress = document.getElementById("status_progress");
    const statusProgressAudit = document.getElementById("status_progress_audit");
    const statusProgressFill = document.getElementById("status_progress_fill");
    const statusProgressValue = document.getElementById("status_progress_value");
    const statusProgressDetail = document.getElementById("status_progress_detail");
    const progressProcessedLabel = document.querySelector("[data-progress-unit-label]");
    const recentEventsBody = document.getElementById("recent_events_body");
    const recentEventsPrev = document.getElementById("recent_events_prev");
    const recentEventsNext = document.getElementById("recent_events_next");
    const recentEventsPage = document.getElementById("recent_events_page");
    const sectionLinks = Array.from(document.querySelectorAll("[data-section-link]"));
    const statusFields = Array.from(document.querySelectorAll("[data-status-field]"));
    const initialStateNode = document.getElementById("cache_page_initial_state");

    let recentEvents = [];
    let recentEventsCurrentPage = 1;

    function clampPercent(value) {
        return Math.min(Math.max(Math.round(Number(value) || 0), 0), 100);
    }

    function formatMetricNumber(value) {
        const parsed = Number(value);
        return Number.isFinite(parsed) ? numberFormatter.format(parsed) : "0";
    }

    function setStatusBannerVisible(isVisible, options = {}) {
        if (!statusBanner) return;
        const { persist = true } = options;
        statusBanner.hidden = !isVisible;
        statusBanner.setAttribute("aria-hidden", String(!isVisible));
        if (!persist) return;
        try {
            window.sessionStorage.setItem(statusBannerStorageKey, String(!isVisible));
        } catch (_error) {
        }
    }

    function restoreStatusBannerState() {
        try {
            if (window.sessionStorage.getItem(statusBannerStorageKey) === "true") {
                setStatusBannerVisible(false, { persist: false });
            }
        } catch (_error) {
        }
    }

    function setPhaseState(phase) {
        const normalizedPhase = String(phase || "idle");
        [phaseChip, bannerPhase].forEach((chip) => {
            if (!chip) return;
            chip.textContent = normalizedPhase;
            chip.className = `status-chip status-${normalizedPhase}`;
        });
        if (phaseValue) phaseValue.textContent = normalizedPhase;
    }

    function recentEventsTotalPages() {
        return Math.max(1, Math.ceil(recentEvents.length / recentEventsPageSize));
    }

    function renderRecentEventsPage() {
        if (!recentEventsBody || !recentEventsPage || !recentEventsPrev || !recentEventsNext) return;
        const totalPages = recentEventsTotalPages();
        recentEventsCurrentPage = Math.min(Math.max(recentEventsCurrentPage, 1), totalPages);
        const pageStartIndex = (recentEventsCurrentPage - 1) * recentEventsPageSize;
        const pageItems = recentEvents.slice(pageStartIndex, pageStartIndex + recentEventsPageSize);
        recentEventsBody.replaceChildren();

        if (!pageItems.length) {
            const row = document.createElement("tr");
            const indexCell = document.createElement("td");
            const messageCell = document.createElement("td");
            indexCell.textContent = "-";
            indexCell.className = "events-empty-index";
            messageCell.textContent = "No recent events.";
            messageCell.className = "events-empty-message";
            row.append(indexCell, messageCell);
            recentEventsBody.appendChild(row);
        } else {
            pageItems.forEach((eventText, index) => {
                const row = document.createElement("tr");
                const indexCell = document.createElement("td");
                const messageCell = document.createElement("td");
                indexCell.textContent = String(pageStartIndex + index + 1);
                messageCell.textContent = eventText;
                row.append(indexCell, messageCell);
                recentEventsBody.appendChild(row);
            });
        }

        recentEventsPage.textContent = `${recentEventsCurrentPage} / ${totalPages}`;
        recentEventsPrev.disabled = recentEventsCurrentPage <= 1;
        recentEventsNext.disabled = recentEventsCurrentPage >= totalPages;
    }

    function setRecentEvents(events) {
        recentEvents = (Array.isArray(events) ? events : [])
            .filter((eventText) => String(eventText || "").trim().length > 0);
        recentEventsCurrentPage = recentEventsTotalPages();
        renderRecentEventsPage();
    }

    function updateSectionLinkState(activeId) {
        const normalizedActiveId = ["overview", sourceKey, "activity"].includes(activeId)
            ? sourceKey
            : activeId;
        sectionLinks.forEach((link) => {
            link.classList.toggle("is-active", link.dataset.sectionLink === normalizedActiveId);
        });
    }

    function initializeSectionTracking() {
        const settingsDockLink = document.querySelector('[data-section-link="settings"]');
        settingsDockLink?.addEventListener("click", () => {
            if (typeof window.setSidebarOpen === "function") window.setSidebarOpen(true);
        });

        const observedSections = Array.from(document.querySelectorAll(".anchor-section"));
        if (!("IntersectionObserver" in window)) return;
        const sectionObserver = new IntersectionObserver((entries) => {
            const visibleEntry = entries
                .filter((entry) => entry.isIntersecting)
                .sort((left, right) => right.intersectionRatio - left.intersectionRatio)[0];
            if (visibleEntry) updateSectionLinkState(visibleEntry.target.id);
        }, {
            rootMargin: "-10% 0px -55% 0px",
            threshold: [0.2, 0.4, 0.6],
        });
        observedSections.forEach((section) => sectionObserver.observe(section));
    }

    function updateStatusFields(data) {
        statusFields.forEach((element) => {
            const fieldName = element.dataset.statusField;
            if (!fieldName) return;
            const rawValue = data[fieldName];
            if (element.dataset.statusFormat === "number") {
                element.textContent = formatMetricNumber(rawValue);
                return;
            }
            const fallback = element.dataset.statusFallback || "";
            element.textContent = rawValue === null || rawValue === undefined || rawValue === ""
                ? fallback
                : String(rawValue);
        });
    }

    function renderProgressState(state) {
        if (!statusProgress || !statusProgressFill) return;
        const completePercent = clampPercent(state.completePercent);
        const auditPercent = clampPercent(state.auditPercent);
        const isIndeterminate = Boolean(state.isIndeterminate);
        statusProgress.classList.toggle("is-indeterminate", isIndeterminate);
        statusProgress.classList.toggle("is-auditing", auditPercent > 0 && !isIndeterminate);
        statusProgressFill.style.width = `${completePercent}%`;
        if (statusProgressAudit) statusProgressAudit.style.width = `${auditPercent}%`;
        if (state.detail) statusProgress.setAttribute("aria-valuetext", state.detail);
        if (isIndeterminate || state.hasMeasuredProgress === false) {
            statusProgress.removeAttribute("aria-valuenow");
        } else {
            statusProgress.setAttribute("aria-valuenow", String(Math.max(completePercent, auditPercent)));
        }
        if (statusProgressValue && state.label) statusProgressValue.textContent = state.label;
        if (statusProgressDetail && state.detail) statusProgressDetail.textContent = state.detail;
    }

    function discoveryProgress(data) {
        const discovered = Number(data.discovered_tweets) || 0;
        const processed = (Number(data.downloaded_posts) || 0)
            + (Number(data.skipped_tweets) || 0)
            + (Number(data.failed_tweets) || 0);
        let completePercent = 0;
        let isIndeterminate = false;
        if (["collecting", "starting", "stopping"].includes(data.phase)) {
            isIndeterminate = true;
        } else if (["downloading", "failed"].includes(data.phase)) {
            completePercent = (processed / Math.max(discovered, processed, 1)) * 100;
        } else if (terminalPhases.has(data.phase)) {
            completePercent = 100;
        }
        return {
            completePercent,
            auditPercent: 0,
            isIndeterminate,
            hasMeasuredProgress: !isIndeterminate,
            label: `${clampPercent(completePercent)}%`,
            detail: "",
        };
    }

    function parseGrokAuditProgress(message) {
        const match = String(message || "").match(/Auditing Grok image quality\s+(\d+)\s*\/\s*(\d+)/i);
        if (!match) return null;
        const current = Number(match[1]);
        const total = Number(match[2]);
        if (!Number.isFinite(current) || !Number.isFinite(total) || total <= 0) return null;
        return { current, total, percent: clampPercent((current / total) * 100) };
    }

    function grokAuditProgress(data) {
        const queued = Math.max(Number(data.queued_tweets) || 0, 0);
        const processed = Math.min(Math.max(Number(data.processed_tweets) || 0, 0), queued);
        const auditProgress = parseGrokAuditProgress(data.message);
        let completePercent = 0;
        let auditPercent = 0;
        let isIndeterminate = false;
        let detail = "No Grok sync is active.";

        if (auditProgress) {
            auditPercent = auditProgress.percent;
            detail = `Auditing image quality: ${formatMetricNumber(auditProgress.current)} of ${formatMetricNumber(auditProgress.total)} assets.`;
        } else if (data.running && !data.discovery_complete) {
            isIndeterminate = true;
            detail = queued > 0
                ? `Discovery is still running. ${formatMetricNumber(processed)} of ${formatMetricNumber(queued)} scheduled downloads processed; the total may increase.`
                : "Scanning the Grok library. The final download total is not known yet.";
        } else if (queued > 0) {
            completePercent = (processed / queued) * 100;
            const pending = Math.max(queued - processed, 0);
            detail = pending > 0
                ? `${formatMetricNumber(processed)} of ${formatMetricNumber(queued)} scheduled downloads processed; ${formatMetricNumber(pending)} pending.`
                : `${formatMetricNumber(processed)} of ${formatMetricNumber(queued)} scheduled downloads processed.`;
        } else if (terminalPhases.has(data.phase)) {
            completePercent = 100;
            detail = "No new Grok downloads were required for this run.";
        }

        return {
            completePercent,
            auditPercent,
            isIndeterminate,
            hasMeasuredProgress: !isIndeterminate,
            label: `${clampPercent(Math.max(completePercent, auditPercent))}%`,
            detail,
        };
    }

    function queueProgress(data) {
        const queued = Math.max(Number(data.queued_tweets) || 0, 0);
        const processed = Math.min(Math.max(Number(data.processed_tweets) || 0, 0), queued);
        const progressUnits = {
            images: "image assets",
            conversations: "conversations",
            resources: "resources",
        };
        const progressUnit = progressUnits[data.progress_unit] || "items";
        const hasMeasuredProgress = queued > 0;
        const isIndeterminate = Boolean(data.running && !hasMeasuredProgress);
        let completePercent = hasMeasuredProgress ? (processed / queued) * 100 : 0;
        let label = "Ready";
        let detail = `No ${sourceLabel} sync is active.`;

        if (isIndeterminate) {
            label = "Scanning";
            detail = `Scanning ${sourceLabel}. The final work-item total is not known yet.`;
        } else if (hasMeasuredProgress) {
            const pending = Math.max(queued - processed, 0);
            const percent = clampPercent(completePercent);
            label = `${percent}%`;
            detail = pending > 0
                ? `${formatMetricNumber(processed)} / ${formatMetricNumber(queued)} ${progressUnit} processed (${percent}%); ${formatMetricNumber(pending)} pending.`
                : `${formatMetricNumber(processed)} / ${formatMetricNumber(queued)} ${progressUnit} processed (${percent}%).`;
        } else if (terminalPhases.has(data.phase)) {
            completePercent = 100;
            label = "100%";
            detail = `No new ${sourceLabel} resources were required for this run.`;
        } else if (data.phase === "failed") {
            label = "Failed";
            detail = `${sourceLabel} sync failed before a work-item total was established.`;
        }

        return {
            completePercent,
            auditPercent: 0,
            isIndeterminate,
            hasMeasuredProgress: hasMeasuredProgress || terminalPhases.has(data.phase),
            label,
            detail,
        };
    }

    const progressStrategies = Object.freeze({
        discovery: discoveryProgress,
        "grok-audit": grokAuditProgress,
        queue: queueProgress,
    });

    function updateProgress(data) {
        const strategy = progressStrategies[progressStrategyName] || progressStrategies.queue;
        renderProgressState(strategy(data));
    }

    function updateProgressUnitLabel(data) {
        if (!progressProcessedLabel) return;
        const labels = {
            images: "Image assets processed",
            conversations: "Conversations processed",
            resources: "Resources processed",
        };
        progressProcessedLabel.textContent = labels[data.progress_unit] || "Work items processed";
    }

    function updateActionState(data) {
        const browserDownloadReady = browserSessionPanel
            ? browserSessionPanel.dataset.browserDownloadReady !== "false"
            : true;
        if (startButton) startButton.disabled = Boolean(data.running) || !browserDownloadReady;
        if (stopButton) stopButton.disabled = !Boolean(data.running);
    }

    async function refreshStatus() {
        if (!statusUrl) return;
        try {
            const response = await fetch(statusUrl, { cache: "no-store" });
            if (!response.ok) throw new Error(`Status request failed with ${response.status}`);
            const data = await response.json();
            updateStatusFields(data);
            if (bannerMessage) bannerMessage.textContent = data.message || "";
            setPhaseState(data.phase);
            setRecentEvents(data.recent_events || []);
            updateProgressUnitLabel(data);
            updateProgress(data);
            updateActionState(data);
        } catch (_error) {
            if (statusProgressDetail) statusProgressDetail.textContent = "Status refresh temporarily unavailable.";
        }
    }

    function initializeNumberSteppers() {
        document.querySelectorAll("[data-cache-number-field]").forEach((field) => {
            const input = field.querySelector("input[type='number']");
            if (!input) return;
            const step = Number.parseFloat(input.step);
            const minimum = Number.parseFloat(input.min);
            const maximum = Number.parseFloat(input.max);
            const decimalPlaces = (input.step.split(".")[1] || "").length;
            field.querySelectorAll("[data-cache-number-stepper]").forEach((button) => {
                button.addEventListener("click", () => {
                    const current = Number.parseFloat(input.value);
                    const baseValue = Number.isFinite(current)
                        ? current
                        : Number.isFinite(minimum)
                            ? minimum
                            : 0;
                    const direction = button.dataset.cacheNumberStepper === "decrement" ? -1 : 1;
                    const nextValue = Math.min(
                        Number.isFinite(maximum) ? maximum : Number.POSITIVE_INFINITY,
                        Math.max(
                            Number.isFinite(minimum) ? minimum : Number.NEGATIVE_INFINITY,
                            baseValue + direction * (Number.isFinite(step) && step > 0 ? step : 1),
                        ),
                    );
                    input.value = nextValue.toFixed(decimalPlaces);
                    input.dispatchEvent(new Event("input", { bubbles: true }));
                    input.dispatchEvent(new Event("change", { bubbles: true }));
                    input.focus({ preventScroll: true });
                });
            });
        });
    }

    function readInitialEvents() {
        if (!initialStateNode) return [];
        try {
            const payload = JSON.parse(initialStateNode.textContent || "{}");
            return Array.isArray(payload.recent_events) ? payload.recent_events : [];
        } catch (_error) {
            return [];
        }
    }

    statusBannerDismiss?.addEventListener("click", () => setStatusBannerVisible(false));
    recentEventsPrev?.addEventListener("click", () => {
        recentEventsCurrentPage -= 1;
        renderRecentEventsPage();
    });
    recentEventsNext?.addEventListener("click", () => {
        recentEventsCurrentPage += 1;
        renderRecentEventsPage();
    });

    restoreStatusBannerState();
    initializeNumberSteppers();
    initializeSectionTracking();
    setRecentEvents(readInitialEvents());
    refreshStatus();
    window.setInterval(refreshStatus, 3_000);
})();
