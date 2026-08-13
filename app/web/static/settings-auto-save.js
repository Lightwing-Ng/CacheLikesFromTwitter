/* Code version: v1.0.0-codex.1 */

(() => {
    const form = document.getElementById("settings_form");
    if (!form) return;

    let saveTimer = null;
    let saveQueue = Promise.resolve();

    function saveSettings() {
        saveQueue = saveQueue
            .then(async () => {
                form.setAttribute("aria-busy", "true");
                const response = await fetch(form.action, {
                    method: "POST",
                    body: new FormData(form),
                    headers: { Accept: "text/html" },
                    credentials: "same-origin",
                });
                if (!response.ok) {
                    throw new Error(`Settings save failed with status ${response.status}.`);
                }
            })
            .catch(() => {
                // Keep the page usable when a local save request fails.
            })
            .finally(() => {
                form.removeAttribute("aria-busy");
            });
    }

    function scheduleSave() {
        if (saveTimer !== null) {
            window.clearTimeout(saveTimer);
        }
        saveTimer = window.setTimeout(() => {
            saveTimer = null;
            saveSettings();
        }, 400);
    }

    form.querySelectorAll("input, select, textarea").forEach((control) => {
        if (control instanceof HTMLInputElement && control.type === "hidden") {
            return;
        }
        control.addEventListener("change", scheduleSave);
        if (!(control instanceof HTMLInputElement) || control.type !== "checkbox") {
            control.addEventListener("input", scheduleSave);
        }
    });
})();
