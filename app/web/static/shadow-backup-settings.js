/* Code version: v1.2.0-codex.1 */

(() => {
    const section = document.querySelector("[data-shadow-backup-section]");
    const enabledInput = document.getElementById("shadow_backup_enabled");
    const mirrorDeletionsInput = document.getElementById("shadow_backup_mirror_deletions");
    const chooseDestinationButton = document.getElementById("shadow_backup_choose_destination");
    const destinationInput = document.getElementById("shadow_backup_destination");
    const syncButton = document.getElementById("shadow_backup_sync_now");
    const statusCopy = document.getElementById("shadow_backup_status");
    const statusSpinner = statusCopy?.querySelector("[data-shadow-backup-status-spinner]");
    const statusMessage = statusCopy?.querySelector("[data-shadow-backup-status-copy]");
    const statusPhase = document.getElementById("shadow_backup_phase");
    const lastSyncedCopy = document.getElementById("shadow_backup_last_synced");
    const mirrorWarning = document.querySelector("[data-shadow-backup-mirror-warning]");

    if (!section || !enabledInput || !mirrorDeletionsInput || !chooseDestinationButton || !destinationInput) {
        return;
    }

    let isSyncRunning = statusCopy?.dataset.phase === "syncing";
    let statusRefreshTimer = null;

    function renderStatusCopy(message, phase) {
        if (statusCopy) {
            const target = statusMessage || statusCopy;
            target.textContent = message || "Shadow cloud backup status is unavailable.";
            statusCopy.dataset.phase = phase || "idle";
        }
        if (statusSpinner) {
            statusSpinner.hidden = !isSyncRunning;
        }
    }

    function updateControlState() {
        const enabled = enabledInput.checked;
        section.dataset.shadowBackupEnabled = String(enabled);
        if (syncButton) {
            syncButton.disabled = !enabled || isSyncRunning;
        }
        if (mirrorWarning) {
            mirrorWarning.hidden = !mirrorDeletionsInput.checked;
        }
        if (statusSpinner) {
            statusSpinner.hidden = !isSyncRunning;
        }
    }

    function renderStatus(snapshot) {
        isSyncRunning = Boolean(snapshot.running);
        renderStatusCopy(snapshot.message, snapshot.phase);
        if (statusPhase) {
            statusPhase.textContent = snapshot.phase || "idle";
            for (const className of [...statusPhase.classList]) {
                if (className.startsWith("status-")) {
                    statusPhase.classList.remove(className);
                }
            }
            statusPhase.classList.add(`status-${snapshot.phase || "idle"}`);
        }
        if (lastSyncedCopy) {
            if (snapshot.last_synced_at) {
                lastSyncedCopy.textContent = `Last successful sync: ${snapshot.last_synced_at}`;
                lastSyncedCopy.hidden = false;
            } else {
                lastSyncedCopy.hidden = true;
            }
        }
        updateControlState();
    }

    async function refreshStatus() {
        try {
            const response = await fetch("/api/settings/shadow-backup/status", { cache: "no-store" });
            if (!response.ok) {
                return;
            }
            const snapshot = await response.json();
            renderStatus(snapshot);
            if (!snapshot.running && statusRefreshTimer !== null) {
                window.clearInterval(statusRefreshTimer);
                statusRefreshTimer = null;
            }
        } catch (_error) {
            // The page remains usable when a transient local request fails.
        }
    }

    function beginStatusPolling() {
        if (statusRefreshTimer !== null) {
            return;
        }
        statusRefreshTimer = window.setInterval(refreshStatus, 2_000);
        refreshStatus();
    }

    enabledInput.addEventListener("change", updateControlState);
    mirrorDeletionsInput.addEventListener("change", updateControlState);

    chooseDestinationButton.addEventListener("click", async () => {
        chooseDestinationButton.disabled = true;
        const wait = window.CacheWaitModal?.begin?.({
            title: "Opening folder picker",
            copy: "Waiting for macOS to let you choose the cloud destination for the local cache mirror.",
            delay: 120,
        });
        try {
            const response = await fetch("/api/settings/shadow-backup/destination", {
                method: "POST",
                cache: "no-store",
                headers: {
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({ initial_path: destinationInput.value }),
            });
            const payload = await response.json();
            if (!response.ok) {
                throw new Error(payload.error || "Could not open the macOS folder picker.");
            }
            if (payload.destination) {
                destinationInput.value = payload.destination;
                destinationInput.focus();
            }
        } catch (error) {
            renderStatusCopy(error.message || "Could not open the macOS folder picker.", "failed");
        } finally {
            wait?.finish?.();
            chooseDestinationButton.disabled = false;
        }
    });

    updateControlState();
    if (isSyncRunning) {
        beginStatusPolling();
    }
})();
