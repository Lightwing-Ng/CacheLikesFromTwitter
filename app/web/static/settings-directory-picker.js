/* Code version: v1.3.1-codex.1 */

(function initializeSettingsDirectoryPickers() {
    "use strict";

    /** Timeout in milliseconds for picker and path-validation fetches. */
    var PICKER_TIMEOUT_MS = 30000;

    var pickerButtons = Array.from(
        document.querySelectorAll("[data-settings-directory-picker]"),
    );

    pickerButtons.forEach(function (button) {
        var inputId = button.dataset.directoryInput;
        var fieldName = button.dataset.directoryField;
        var directoryLabel = button.dataset.directoryLabel || "directory";
        var input = inputId ? document.getElementById(inputId) : null;
        var status = button.closest(".field")?.querySelector("[data-directory-picker-status]");
        if (!input || !fieldName) return;

        input.removeAttribute("readonly");
        input.removeAttribute("aria-readonly");

        if (status) {
            if (!status.id && input.id) {
                status.id = input.id + "_status";
            }
            if (status.id && input.getAttribute("aria-describedby") !== status.id) {
                input.setAttribute("aria-describedby", status.id);
            }
            if (!status.getAttribute("role")) status.setAttribute("role", "status");
            if (!status.getAttribute("aria-live")) status.setAttribute("aria-live", "polite");
        }

        function renderStatus(message, isError) {
            if (!status) return;
            status.textContent = message || "";
            status.hidden = !message;
            if (isError) {
                status.classList.add("field-status--error");
            } else {
                status.classList.remove("field-status--error");
            }
        }

        function clearLoadingState() {
            input.removeAttribute("aria-busy");
            button.disabled = false;
        }

        function parseJsonPayload(response, rawText) {
            try {
                return JSON.parse(rawText);
            } catch (_jsonError) {
                throw new Error("The server returned a malformed response.");
            }
        }

        button.addEventListener("click", async function () {
            button.disabled = true;
            input.setAttribute("aria-busy", "true");
            input.removeAttribute("aria-invalid");
            renderStatus("");
            var wait = window.CacheWaitModal?.begin?.({
                title: "Opening folder picker",
                copy: "Waiting for the system to let you choose the " + directoryLabel + ".",
                delay: 120,
            });

            var controller = new AbortController();
            var timeoutId = setTimeout(function () {
                controller.abort();
            }, PICKER_TIMEOUT_MS);

            try {
                var response = await fetch("/api/settings/directory", {
                    method: "POST",
                    cache: "no-store",
                    signal: controller.signal,
                    headers: {
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    },
                    body: JSON.stringify({
                        field: fieldName,
                        initial_path: input.value,
                    }),
                });
                clearTimeout(timeoutId);

                var rawText = await response.text();
                var payload = parseJsonPayload(response, rawText);

                if (!response.ok) {
                    throw new Error(payload.error || "Could not open the folder picker.");
                }
                if (payload.cancelled) {
                    renderStatus("Selection cancelled.", false);
                    return;
                }
                if (payload.directory) {
                    input.value = payload.directory;
                    input.dispatchEvent(new Event("change", { bubbles: true }));
                    input.focus();
                    renderStatus("Folder selected: " + payload.directory, false);
                }
            } catch (error) {
                clearTimeout(timeoutId);
                input.setAttribute("aria-invalid", "true");
                if (error && error.name === "AbortError") {
                    renderStatus(
                        "The folder picker did not respond. You can type the path directly.",
                        true,
                    );
                } else {
                    renderStatus(
                        (error && error.message) || "Could not open the folder picker.",
                        true,
                    );
                }
            } finally {
                wait?.finish?.();
                clearLoadingState();
            }
        });

        input.addEventListener("change", async function () {
            var pathValue = (input.value || "").trim();
            if (!pathValue) {
                renderStatus("");
                input.removeAttribute("aria-invalid");
                return;
            }
            var controller = new AbortController();
            var timeoutId = setTimeout(function () {
                controller.abort();
            }, PICKER_TIMEOUT_MS);
            try {
                var response = await fetch("/api/settings/directory/validate", {
                    method: "POST",
                    cache: "no-store",
                    signal: controller.signal,
                    headers: {
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    },
                    body: JSON.stringify({ path: pathValue }),
                });
                clearTimeout(timeoutId);
                var rawText = await response.text();
                var result = parseJsonPayload(response, rawText);
                if (!response.ok) {
                    throw new Error(result.error || "Could not validate the folder path.");
                }
                if (result.valid) {
                    input.removeAttribute("aria-invalid");
                    renderStatus("", false);
                } else {
                    input.setAttribute("aria-invalid", "true");
                    renderStatus(result.reason || "Invalid path.", true);
                }
            } catch (error) {
                clearTimeout(timeoutId);
                input.setAttribute("aria-invalid", "true");
                if (error && error.name === "AbortError") {
                    renderStatus(
                        "Path validation timed out. Check the folder path and try again.",
                        true,
                    );
                } else {
                    renderStatus(
                        (error && error.message) || "Could not validate the folder path.",
                        true,
                    );
                }
            }
        });
    });
})();
