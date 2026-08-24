/* Code version: v1.0.0-codex.4 */

(() => {
    "use strict";

    const status = document.querySelector("[data-style-token-copy-status]");

    const showStatus = (message) => {
        if (!status) {
            return;
        }
        status.textContent = message;
        window.clearTimeout(showStatus.timeoutId);
        showStatus.timeoutId = window.setTimeout(() => {
            status.textContent = "";
        }, 1800);
    };

    const copyText = async (value) => {
        if (navigator.clipboard?.writeText) {
            await navigator.clipboard.writeText(value);
            return;
        }
        const helper = document.createElement("textarea");
        helper.value = value;
        helper.setAttribute("readonly", "");
        helper.style.position = "fixed";
        helper.style.opacity = "0";
        document.body.appendChild(helper);
        helper.select();
        document.execCommand("copy");
        helper.remove();
    };

    const setPressedButton = (container, selectedButton) => {
        container.querySelectorAll("button").forEach((button) => {
            const isSelected = button === selectedButton;
            button.classList.toggle("is-active", isSelected);
            button.setAttribute("aria-pressed", String(isSelected));
        });
    };

    const bindSegmentedDemos = () => {
        document.querySelectorAll("[data-style-token-segmented]").forEach((container) => {
            container.addEventListener("click", (event) => {
                const button = event.target.closest("button");
                if (!button || !container.contains(button)) {
                    return;
                }
                setPressedButton(container, button);

                const stateDemo = container.closest("[data-style-token-state-demo]");
                if (stateDemo && button.dataset.styleTokenState) {
                    const state = button.dataset.styleTokenState;
                    const indicator = stateDemo.querySelector("[data-style-token-state-indicator]");
                    const copy = stateDemo.querySelector("[data-style-token-state-copy]");
                    stateDemo.dataset.state = state;
                    if (indicator) {
                        indicator.textContent = state[0].toUpperCase() + state.slice(1);
                        indicator.className = `status-chip is-${state}`;
                    }
                    if (copy) {
                        copy.textContent = `${indicator?.textContent || "Status"} feedback is now visible in the preview.`;
                    }
                }

                const productDemo = container.closest("[data-style-token-demo='product-summary']");
                if (productDemo && button.dataset.styleTokenProductFilter) {
                    const copy = productDemo.querySelector("[data-style-token-product-copy]");
                    const filter = button.dataset.styleTokenProductFilter;
                    if (copy) {
                        copy.textContent = `Showing ${filter} through the shared result summary.`;
                    }
                }
            });
        });
    };

    const bindToggleDemos = () => {
        document.querySelectorAll("[data-style-token-toggle]").forEach((toggle) => {
            toggle.addEventListener("change", () => {
                const demo = toggle.closest("[data-style-token-demo='control-playground']");
                const copy = demo?.querySelector("[data-style-token-toggle-copy]");
                if (copy) {
                    copy.textContent = toggle.checked
                        ? "Accent feedback is enabled."
                        : "Accent feedback is paused.";
                }
            });
        });
    };

    const bindWorkflowDemos = () => {
        document.querySelectorAll("[data-style-token-workflow-action]").forEach((button) => {
            button.addEventListener("click", () => {
                const demo = button.closest("[data-style-token-workflow-demo]");
                const state = demo?.querySelector("[data-style-token-workflow-state]");
                if (!state) {
                    return;
                }
                state.textContent = "Updated";
                state.className = "status-chip is-ready";
                showStatus("Preview refreshed");
            });
        });
    };

    const bindProductDemos = () => {
        document.querySelectorAll("[data-style-token-product-action]").forEach((button) => {
            button.addEventListener("click", () => {
                const demo = button.closest("[data-style-token-demo='product-summary']");
                const copy = demo?.querySelector("[data-style-token-product-copy]");
                if (copy) {
                    copy.textContent = "Local resources preview opened in place.";
                }
                showStatus("Local resources preview opened");
            });
        });
    };

    bindSegmentedDemos();
    bindToggleDemos();
    bindWorkflowDemos();
    bindProductDemos();

    document.addEventListener("click", (event) => {
        const button = event.target.closest("[data-style-token-copy]");
        if (!button) {
            return;
        }
        const tokenName = button.dataset.styleTokenCopy;
        if (!tokenName) {
            return;
        }
        copyText(tokenName)
            .then(() => {
                button.classList.add("is-copied");
                window.clearTimeout(button.copyResetTimeoutId);
                button.copyResetTimeoutId = window.setTimeout(() => {
                    button.classList.remove("is-copied");
                }, 1800);
                showStatus(`Copied: ${tokenName}`);
            })
            .catch(() => showStatus("Copy unavailable"));
    });
})();
