/* Code version: v1.0.0-codex.1 */

(() => {
    function normalizeRawValue(value) {
        return String(value || "").replace(/,/g, "").trim();
    }

    function formatValue(input) {
        const rawValue = normalizeRawValue(input.value);
        if (!rawValue) {
            input.value = "";
            return;
        }

        const numberValue = Number(rawValue);
        if (!Number.isFinite(numberValue)) {
            return;
        }

        if (input.dataset.numberFormat === "decimal") {
            input.value = numberValue.toLocaleString("en-US", {
                minimumFractionDigits: 2,
                maximumFractionDigits: 2,
            });
            return;
        }

        input.value = Math.round(numberValue).toLocaleString("en-US");
    }

    function unformatValue(input) {
        input.value = normalizeRawValue(input.value);
    }

    document.addEventListener("DOMContentLoaded", () => {
        const inputs = Array.from(document.querySelectorAll("[data-number-format]"));
        if (!inputs.length) {
            return;
        }

        inputs.forEach((input) => {
            formatValue(input);
            input.addEventListener("focus", () => {
                unformatValue(input);
                input.select();
            });
            input.addEventListener("blur", () => {
                formatValue(input);
            });
        });

        document.querySelectorAll("form").forEach((form) => {
            form.addEventListener("submit", () => {
                inputs.forEach((input) => {
                    if (form.contains(input)) {
                        unformatValue(input);
                    }
                });
            });
        });
    });
})();
