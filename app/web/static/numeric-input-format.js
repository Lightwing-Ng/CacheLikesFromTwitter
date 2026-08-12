/* Code version: v1.1.0-codex.1 */

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

    function readNumberOption(input, dataName, propertyName) {
        const rawValue = input.dataset[dataName] || input[propertyName] || "";
        const parsedValue = Number.parseFloat(rawValue);
        return Number.isFinite(parsedValue) ? parsedValue : null;
    }

    function decimalPlaces(stepValue) {
        const stepText = String(stepValue);
        return (stepText.split(".")[1] || "").length;
    }

    function updateNumberFieldState(field, input) {
        const current = Number.parseFloat(normalizeRawValue(input.value));
        const minimum = readNumberOption(input, "numberMin", "min");
        const maximum = readNumberOption(input, "numberMax", "max");
        if (Number.isFinite(current)) {
            input.setAttribute("aria-valuenow", String(current));
        } else {
            input.removeAttribute("aria-valuenow");
        }

        field.querySelectorAll("[data-cache-number-stepper]").forEach((button) => {
            const decrement = button.dataset.cacheNumberStepper === "decrement";
            button.disabled = Number.isFinite(current) && (
                decrement
                    ? minimum !== null && current <= minimum
                    : maximum !== null && current >= maximum
            );
        });
    }

    function adjustNumberField(field, input, direction) {
        const current = Number.parseFloat(normalizeRawValue(input.value));
        const minimum = readNumberOption(input, "numberMin", "min");
        const maximum = readNumberOption(input, "numberMax", "max");
        const configuredStep = readNumberOption(input, "numberStep", "step");
        const step = configuredStep !== null && configuredStep > 0 ? configuredStep : 1;
        const hasCurrentValue = Number.isFinite(current);
        const baseValue = hasCurrentValue
            ? current
            : minimum !== null
                ? minimum
                : 0;
        const steppedValue = hasCurrentValue ? baseValue + direction * step : baseValue;
        const nextValue = Math.min(
            maximum ?? Number.POSITIVE_INFINITY,
            Math.max(minimum ?? Number.NEGATIVE_INFINITY, steppedValue),
        );

        input.value = nextValue.toFixed(decimalPlaces(step));
        input.dispatchEvent(new Event("input", { bubbles: true }));
        input.dispatchEvent(new Event("change", { bubbles: true }));
        input.focus({ preventScroll: true });
        updateNumberFieldState(field, input);
    }

    function initializeNumberSteppers() {
        document.querySelectorAll("[data-cache-number-field]").forEach((field) => {
            const input = field.querySelector(".cache-number-input");
            if (!input) {
                return;
            }

            field.querySelectorAll("[data-cache-number-stepper]").forEach((button) => {
                button.addEventListener("click", () => {
                    const direction = button.dataset.cacheNumberStepper === "decrement" ? -1 : 1;
                    adjustNumberField(field, input, direction);
                });
            });
            input.addEventListener("input", () => updateNumberFieldState(field, input));
            input.addEventListener("keydown", (event) => {
                if (event.key !== "ArrowUp" && event.key !== "ArrowDown") {
                    return;
                }
                event.preventDefault();
                adjustNumberField(field, input, event.key === "ArrowDown" ? -1 : 1);
            });
            updateNumberFieldState(field, input);
        });
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

        initializeNumberSteppers();

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
