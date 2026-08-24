/* Code version: v1.0.0-codex.6 */

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

    const bindRangeModeDemos = () => {
        document.querySelectorAll(".style-token-demo .range-mode-shell").forEach((shell) => {
            if (!(shell instanceof HTMLElement) || shell.dataset.bound === "1") {
                return;
            }
            shell.dataset.bound = "1";

            const syncActiveValue = () => {
                const checkedInput = shell.querySelector('input[type="radio"]:checked');
                const options = Array.from(shell.querySelectorAll(".range-mode-option"));
                const activeIndex = Math.max(
                    0,
                    options.findIndex((option) => option.querySelector('input[type="radio"]') === checkedInput),
                );
                const optionCount = Math.max(options.length, 1);
                const nextValue = checkedInput instanceof HTMLInputElement ? checkedInput.value : "overview";
                shell.dataset.active = nextValue;
                shell.dataset.optionCount = String(optionCount);
                shell.dataset.segmentedActiveIndex = String(activeIndex);
                shell.style.setProperty("--segmented-option-count", String(optionCount));
                shell.style.setProperty("--segmented-active-index", String(activeIndex));
            };

            shell.querySelectorAll('input[type="radio"]').forEach((input) => {
                input.addEventListener("change", syncActiveValue);
            });
            syncActiveValue();
        });
    };

    const bindStyleTokenResizer = () => {
        const shell = document.querySelector("[data-style-token-shell]");
        const handle = shell?.querySelector("[data-style-token-resizer]");
        if (!(shell instanceof HTMLElement) || !(handle instanceof HTMLElement) || handle.dataset.bound === "1") {
            return;
        }
        const minWidth = 220;
        const getWidthRange = () => {
            const rect = shell.getBoundingClientRect();
            const computed = getComputedStyle(shell);
            const columnGap = Number.parseFloat(computed.getPropertyValue("--style-token-column-gap")) || 24;
            const maximum = Math.max(minWidth, rect.width - columnGap - 280);
            return {minimum: minWidth, maximum};
        };
        const widthFromPointer = (clientX) => {
            const rect = shell.getBoundingClientRect();
            const computed = getComputedStyle(shell);
            const columnGap = Number.parseFloat(computed.getPropertyValue("--style-token-column-gap")) || 24;
            return clientX - rect.left - (columnGap / 2);
        };
        const getCurrentWidth = () => {
            const demo = shell.querySelector(".style-token-demo");
            return demo instanceof HTMLElement ? demo.getBoundingClientRect().width : minWidth;
        };
        const setCurrentWidth = (nextWidth) => {
            shell.style.setProperty("--style-token-demo-width-current", `${nextWidth}px`);
        };
        const syncHandleY = () => {
            const rect = shell.getBoundingClientRect();
            if (!rect.height) {
                return;
            }
            const visibleTop = Math.max(0, rect.top);
            const visibleBottom = Math.min(window.innerHeight, rect.bottom);
            const visibleHeight = visibleBottom - visibleTop;
            if (visibleHeight <= 0) {
                return;
            }
            const visibleCenterY = visibleTop + (visibleHeight / 2);
            const targetY = Math.min(Math.max(16, visibleCenterY - rect.top), rect.height - 16);
            shell.style.setProperty("--style-token-resizer-y", `${targetY}px`);
        };
        const unbind = window.CACHE_LIKES_RESIZER?.bind(handle, {
            axis: "inline",
            root: shell,
            getRange: getWidthRange,
            getValue: getCurrentWidth,
            setValue: setCurrentWidth,
            valueFromPointer: widthFromPointer,
        });
        handle.dataset.bound = "1";
        syncHandleY();
        window.addEventListener("resize", syncHandleY, {passive: true});
        window.addEventListener("scroll", syncHandleY, {passive: true});
        handle._cacheLikesResizerCleanup = () => {
            unbind?.();
            window.removeEventListener("resize", syncHandleY);
            window.removeEventListener("scroll", syncHandleY);
            delete handle.dataset.bound;
        };
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
    bindRangeModeDemos();
    bindStyleTokenResizer();
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
