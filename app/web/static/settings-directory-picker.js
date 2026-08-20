/* Code version: v1.1.0-codex.1 */

(function initializeSettingsDirectoryPickers() {
    "use strict";

    const pickerButtons = Array.from(
        document.querySelectorAll("[data-settings-directory-picker]"),
    );

    pickerButtons.forEach((button) => {
        const inputId = button.dataset.directoryInput;
        const fieldName = button.dataset.directoryField;
        const directoryLabel = button.dataset.directoryLabel || "directory";
        const input = inputId ? document.getElementById(inputId) : null;
        const status = button.closest(".field")?.querySelector("[data-directory-picker-status]");
        if (!input || !fieldName) return;

        function renderStatus(message = "") {
            if (!status) return;
            status.textContent = message;
            status.hidden = !message;
        }

        button.addEventListener("click", async () => {
            button.disabled = true;
            input.setAttribute("aria-busy", "true");
            input.removeAttribute("aria-invalid");
            renderStatus();
            const wait = window.CacheWaitModal?.begin?.({
                title: "Opening folder picker",
                copy: `Waiting for the system to let you choose the ${directoryLabel}.`,
                delay: 120,
            });

            try {
                const response = await fetch("/api/settings/directory", {
                    method: "POST",
                    cache: "no-store",
                    headers: {
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    },
                    body: JSON.stringify({
                        field: fieldName,
                        initial_path: input.value,
                    }),
                });
                const payload = await response.json();
                if (!response.ok) {
                    throw new Error(payload.error || "Could not open the folder picker.");
                }
                if (payload.directory) {
                    input.value = payload.directory;
                    input.dispatchEvent(new Event("change", { bubbles: true }));
                    input.focus();
                }
            } catch (error) {
                input.setAttribute("aria-invalid", "true");
                renderStatus(error.message || "Could not open the folder picker.");
            } finally {
                wait?.finish?.();
                input.removeAttribute("aria-busy");
                button.disabled = false;
            }
        });
    });
})();
