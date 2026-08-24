/* Code version: v1.1.0-codex.5 */

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

    const setStyleTokenMenuOpen = (container, trigger, menu, isOpen) => {
        container.classList.toggle("is-open", isOpen);
        trigger.setAttribute("aria-expanded", String(isOpen));
        menu.hidden = !isOpen;
        menu.setAttribute("aria-hidden", String(!isOpen));
    };

    const syncStyleTokenFilterSelection = (container, option) => {
        const trigger = container.querySelector("[data-style-token-shared-filter-trigger], [data-style-token-table-filter-trigger]");
        const label = container.querySelector("[data-style-token-shared-filter-label], [data-style-token-table-filter-label]");
        const options = Array.from(container.querySelectorAll("[data-style-token-shared-filter-option], [data-style-token-table-filter-option]"));
        const value = option?.dataset.styleTokenSharedFilterOption || option?.dataset.styleTokenTableFilterOption || "";
        options.forEach((candidate) => {
            const selected = candidate === option;
            candidate.classList.toggle("is-selected", selected);
            candidate.classList.toggle("is-active", selected);
            candidate.setAttribute("aria-selected", String(selected));
        });
        if (label && option) {
            label.textContent = option.textContent.trim();
        }
        if (trigger && option) {
            trigger.setAttribute("aria-label", `${container.hasAttribute("data-style-token-table-filter") ? "Type filter" : "Sort cached text"}: ${option.textContent.trim()}`);
        }
        return value;
    };

    const bindStyleTokenFilterMenus = () => {
        document.querySelectorAll("[data-style-token-shared-filter], [data-style-token-table-filter]").forEach((container) => {
            if (!(container instanceof HTMLElement) || container.dataset.bound === "1") {
                return;
            }
            const trigger = container.querySelector("[data-style-token-shared-filter-trigger], [data-style-token-table-filter-trigger]");
            const menu = container.querySelector("[data-style-token-shared-filter-menu], [data-style-token-table-filter-menu]");
            const options = Array.from(container.querySelectorAll("[data-style-token-shared-filter-option], [data-style-token-table-filter-option]"));
            if (!(trigger instanceof HTMLButtonElement) || !(menu instanceof HTMLElement) || !options.length) {
                return;
            }
            container.dataset.bound = "1";
            const selected = options.find((option) => option.getAttribute("aria-selected") === "true") || options[0];
            syncStyleTokenFilterSelection(container, selected);
            trigger.addEventListener("click", () => {
                setStyleTokenMenuOpen(container, trigger, menu, !container.classList.contains("is-open"));
            });
            trigger.addEventListener("keydown", (event) => {
                if (event.key === "Escape") {
                    event.preventDefault();
                    setStyleTokenMenuOpen(container, trigger, menu, false);
                    trigger.focus({preventScroll: true});
                }
            });
            options.forEach((option) => {
                option.addEventListener("click", () => {
                    const value = syncStyleTokenFilterSelection(container, option);
                    const nativeSelect = container.querySelector("select");
                    if (nativeSelect instanceof HTMLSelectElement) {
                        nativeSelect.value = value;
                    }
                    setStyleTokenMenuOpen(container, trigger, menu, false);
                    container.__styleTokenOnSelect?.(value);
                });
            });
        });
        if (document.documentElement.dataset.styleTokenFilterMenusBound === "1") {
            return;
        }
        document.documentElement.dataset.styleTokenFilterMenusBound = "1";
        document.addEventListener("click", (event) => {
            if (event.target instanceof Element && event.target.closest("[data-style-token-shared-filter], [data-style-token-table-filter]")) {
                return;
            }
            document.querySelectorAll("[data-style-token-shared-filter].is-open, [data-style-token-table-filter].is-open").forEach((container) => {
                const trigger = container.querySelector("[data-style-token-shared-filter-trigger], [data-style-token-table-filter-trigger]");
                const menu = container.querySelector("[data-style-token-shared-filter-menu], [data-style-token-table-filter-menu]");
                if (trigger instanceof HTMLButtonElement && menu instanceof HTMLElement) {
                    setStyleTokenMenuOpen(container, trigger, menu, false);
                }
            });
        });
    };

    const setStyleTokenAgentBrowserMenuOpen = (container, trigger, menu, isOpen) => {
        container.classList.toggle("is-agent-combobox-open", isOpen);
        trigger.setAttribute("aria-expanded", String(isOpen));
        menu.hidden = !isOpen;
        menu.setAttribute("aria-hidden", String(!isOpen));
    };

    const syncStyleTokenAgentBrowserSelection = (container, option) => {
        const input = container.querySelector("[data-style-token-agent-browser-input]");
        const trigger = container.querySelector("[data-style-token-agent-browser-trigger]");
        const label = container.querySelector("[data-style-token-agent-browser-selected-label]");
        const icon = container.querySelector("[data-style-token-agent-browser-selected-icon]");
        const options = Array.from(container.querySelectorAll("[data-style-token-agent-browser-option]"));
        if (!option) {
            return;
        }
        const value = option.dataset.styleTokenAgentBrowserOption || "";
        const optionLabel = option.dataset.styleTokenAgentBrowserLabel || option.textContent.trim();
        const optionIcon = option.dataset.styleTokenAgentBrowserIcon || "";
        if (input instanceof HTMLInputElement) {
            input.value = value;
        }
        if (label) {
            label.textContent = optionLabel;
        }
        if (icon instanceof HTMLImageElement && optionIcon) {
            icon.src = optionIcon;
        }
        if (trigger) {
            trigger.setAttribute("aria-label", `Browser: ${optionLabel}`);
        }
        options.forEach((candidate) => {
            const selected = candidate === option;
            candidate.classList.toggle("is-selected", selected);
            candidate.classList.toggle("is-active", selected);
            candidate.setAttribute("aria-selected", String(selected));
        });
    };

    const bindStyleTokenAgentBrowserDemo = () => {
        document.querySelectorAll("[data-style-token-agent-browser]").forEach((container) => {
            if (!(container instanceof HTMLElement) || container.dataset.bound === "1") {
                return;
            }
            const trigger = container.querySelector("[data-style-token-agent-browser-trigger]");
            const menu = container.querySelector("[data-style-token-agent-browser-menu]");
            const options = Array.from(container.querySelectorAll("[data-style-token-agent-browser-option]"));
            if (!(trigger instanceof HTMLButtonElement) || !(menu instanceof HTMLElement) || !options.length) {
                return;
            }
            container.dataset.bound = "1";
            const inputValue = container.querySelector("[data-style-token-agent-browser-input]")?.value || "edge";
            const selected = options.find((option) => option.dataset.styleTokenAgentBrowserOption === inputValue)
                || options.find((option) => option.getAttribute("aria-selected") === "true")
                || options[0];
            syncStyleTokenAgentBrowserSelection(container, selected);
            setStyleTokenAgentBrowserMenuOpen(
                container,
                trigger,
                menu,
                container.classList.contains("is-agent-combobox-open") || !menu.hidden,
            );
            trigger.addEventListener("click", () => {
                const isOpen = container.classList.contains("is-agent-combobox-open");
                document.querySelectorAll("[data-style-token-agent-browser].is-agent-combobox-open").forEach((other) => {
                    if (other === container) {
                        return;
                    }
                    const otherTrigger = other.querySelector("[data-style-token-agent-browser-trigger]");
                    const otherMenu = other.querySelector("[data-style-token-agent-browser-menu]");
                    if (otherTrigger instanceof HTMLButtonElement && otherMenu instanceof HTMLElement) {
                        setStyleTokenAgentBrowserMenuOpen(other, otherTrigger, otherMenu, false);
                    }
                });
                setStyleTokenAgentBrowserMenuOpen(container, trigger, menu, !isOpen);
            });
            trigger.addEventListener("keydown", (event) => {
                if (event.key !== "Escape") {
                    return;
                }
                event.preventDefault();
                setStyleTokenAgentBrowserMenuOpen(container, trigger, menu, false);
                trigger.focus({preventScroll: true});
            });
            options.forEach((option) => {
                option.addEventListener("click", () => {
                    syncStyleTokenAgentBrowserSelection(container, option);
                    setStyleTokenAgentBrowserMenuOpen(container, trigger, menu, false);
                    showStatus(`Browser preview: ${option.dataset.styleTokenAgentBrowserLabel || option.textContent.trim()}`);
                });
            });
        });
        if (document.documentElement.dataset.styleTokenAgentBrowserBound === "1") {
            return;
        }
        document.documentElement.dataset.styleTokenAgentBrowserBound = "1";
        document.addEventListener("click", (event) => {
            if (event.target instanceof Element && event.target.closest("[data-style-token-agent-browser]")) {
                return;
            }
            document.querySelectorAll("[data-style-token-agent-browser].is-agent-combobox-open").forEach((container) => {
                const trigger = container.querySelector("[data-style-token-agent-browser-trigger]");
                const menu = container.querySelector("[data-style-token-agent-browser-menu]");
                if (trigger instanceof HTMLButtonElement && menu instanceof HTMLElement) {
                    setStyleTokenAgentBrowserMenuOpen(container, trigger, menu, false);
                }
            });
        });
        document.addEventListener("keydown", (event) => {
            if (event.key !== "Escape") {
                return;
            }
            document.querySelectorAll("[data-style-token-agent-browser].is-agent-combobox-open").forEach((container) => {
                const trigger = container.querySelector("[data-style-token-agent-browser-trigger]");
                const menu = container.querySelector("[data-style-token-agent-browser-menu]");
                if (trigger instanceof HTMLButtonElement && menu instanceof HTMLElement) {
                    setStyleTokenAgentBrowserMenuOpen(container, trigger, menu, false);
                    trigger.focus({preventScroll: true});
                }
            });
        });
    };

    const syncStyleTokenPaginationIndicator = (pagination, immediate = true) => {
        const active = pagination.querySelector(".local-store-page-button.is-active");
        if (!active) {
            return;
        }
        window.CACHELIKES_PAGINATION_MOTION?.positionPaginationIndicator(pagination, active, {immediate});
    };

    const setStyleTokenPaginationPage = (pagination, page) => {
        const target = String(page);
        const button = Array.from(pagination.querySelectorAll(":scope > .local-store-page-button"))
            .find((candidate) => candidate.dataset.paginationTarget === target);
        if (!button) {
            return;
        }
        pagination.querySelectorAll(":scope > .local-store-page-button").forEach((candidate) => {
            const selected = candidate === button;
            candidate.classList.toggle("is-active", selected);
            candidate.dataset.paginationCurrent = selected ? "1" : "0";
            candidate.toggleAttribute("aria-current", selected);
            if (selected) {
                candidate.setAttribute("aria-current", "page");
            }
        });
        syncStyleTokenPaginationIndicator(pagination, false);
    };

    const bindStyleTokenPagination = () => {
        document.querySelectorAll("[data-style-token-pagination]").forEach((pagination) => {
            if (!(pagination instanceof HTMLElement) || pagination.dataset.bound === "1") {
                return;
            }
            pagination.dataset.bound = "1";
            pagination.querySelectorAll(":scope > .local-store-page-button").forEach((button) => {
                button.addEventListener("click", () => {
                    setStyleTokenPaginationPage(pagination, button.dataset.paginationTarget);
                    showStatus(`Showing session page ${button.dataset.paginationTarget}`);
                });
            });
            const range = pagination.querySelector("[data-style-token-pagination-range]");
            const rangeTrigger = range?.querySelector("[data-style-token-pagination-range-trigger]");
            const rangeMenu = range?.querySelector("[data-style-token-pagination-range-menu]");
            if (range instanceof HTMLElement && rangeTrigger instanceof HTMLButtonElement && rangeMenu instanceof HTMLElement) {
                rangeTrigger.addEventListener("click", () => {
                    const isOpen = range.classList.contains("is-open");
                    range.classList.toggle("is-open", !isOpen);
                    rangeTrigger.setAttribute("aria-expanded", String(!isOpen));
                    rangeMenu.hidden = isOpen;
                    rangeMenu.setAttribute("aria-hidden", String(isOpen));
                });
                range.querySelectorAll("[data-pagination-target]").forEach((option) => {
                    option.addEventListener("click", () => {
                        range.classList.remove("is-open");
                        rangeTrigger.setAttribute("aria-expanded", "false");
                        rangeMenu.hidden = true;
                        rangeMenu.setAttribute("aria-hidden", "true");
                        showStatus(`Range ${option.textContent.trim()} selected`);
                    });
                });
            }
            syncStyleTokenPaginationIndicator(pagination);
        });
    };

    const bindStyleTokenTableDemos = () => {
        document.querySelectorAll("[data-style-token-table-demo]").forEach((demo) => {
            if (!(demo instanceof HTMLElement) || demo.dataset.bound === "1") {
                return;
            }
            const rows = Array.from(demo.querySelectorAll("[data-style-token-table-row]"));
            const pagination = demo.querySelector("[data-style-token-table-pagination]");
            const summary = demo.querySelector("[data-style-token-table-filter-summary]");
            const filter = demo.querySelector("[data-style-token-table-filter]");
            const pageSize = Number(demo.dataset.styleTokenTablePageSize || 6);
            if (!(pagination instanceof HTMLElement) || !(summary instanceof HTMLElement) || !(filter instanceof HTMLElement)) {
                return;
            }
            demo.dataset.bound = "1";
            let activeFilter = "all";
            let currentPage = 1;
            const matchingRows = () => rows.filter((row) => activeFilter === "all" || row.dataset.styleTokenTableFilterValue === activeFilter);
            const renderPagination = (pageCount) => {
                pagination.replaceChildren();
                if (pageCount <= 1) {
                    pagination.hidden = true;
                    return;
                }
                pagination.hidden = false;
                const indicator = document.createElement("span");
                indicator.className = "local-store-pagination-indicator";
                indicator.setAttribute("aria-hidden", "true");
                pagination.append(indicator);
                for (let page = 1; page <= pageCount; page += 1) {
                    const button = document.createElement("button");
                    button.type = "button";
                    button.className = `local-store-page-button${page === currentPage ? " is-active" : ""}`;
                    button.dataset.paginationTarget = String(page);
                    button.dataset.paginationCurrent = page === currentPage ? "1" : "0";
                    button.setAttribute("aria-label", `Table page ${page}`);
                    if (page === currentPage) {
                        button.setAttribute("aria-current", "page");
                    }
                    button.textContent = String(page);
                    button.addEventListener("click", () => {
                        currentPage = page;
                        render();
                    });
                    pagination.append(button);
                }
                syncStyleTokenPaginationIndicator(pagination);
            };
            const render = () => {
                const matching = matchingRows();
                const pageCount = Math.max(1, Math.ceil(matching.length / pageSize));
                currentPage = Math.min(currentPage, pageCount);
                const firstIndex = (currentPage - 1) * pageSize;
                rows.forEach((row) => {
                    const rowIndex = matching.indexOf(row);
                    row.hidden = rowIndex < firstIndex || rowIndex >= firstIndex + pageSize;
                });
                summary.textContent = `${matching.length} filtered of ${rows.length} total`;
                renderPagination(pageCount);
            };
            filter.__styleTokenOnSelect = (value) => {
                activeFilter = value;
                currentPage = 1;
                render();
            };
            render();
        });
    };

    const bindSecondaryButtonDemo = () => {
        document.querySelectorAll("[data-style-token-secondary-button]").forEach((button) => {
            button.addEventListener("click", () => showStatus("Refresh cache control preview"));
        });
    };

    const bindStyleTokenPrimaryButtonDemo = () => {
        document.querySelectorAll("[data-style-token-primary-button]").forEach((button) => {
            if (!(button instanceof HTMLButtonElement) || button.dataset.bound === "1") {
                return;
            }
            button.dataset.bound = "1";
            button.addEventListener("click", () => showStatus("Start action preview"));
        });
    };

    const bindStyleTokenThemeToggleDemo = () => {
        document.querySelectorAll("[data-style-token-theme-toggle]").forEach((button) => {
            if (!(button instanceof HTMLButtonElement) || button.dataset.bound === "1") {
                return;
            }
            button.dataset.bound = "1";
            const label = button.closest("[data-style-token-demo='global-theme-toggle']")?.querySelector("[data-style-token-theme-toggle-label]");
            const sync = (effectiveTheme) => {
                const isDark = effectiveTheme === "dark";
                const nextLabel = isDark ? "Switch to Light mode" : "Switch to Dark mode";
                button.dataset.effectiveTheme = isDark ? "dark" : "light";
                button.setAttribute("aria-label", nextLabel);
                button.title = nextLabel;
                button.setAttribute("aria-pressed", String(isDark));
                if (label) {
                    label.textContent = nextLabel;
                }
            };
            sync(button.dataset.effectiveTheme || "light");
            button.addEventListener("click", () => {
                const nextTheme = button.dataset.effectiveTheme === "dark" ? "light" : "dark";
                sync(nextTheme);
                showStatus(`Theme preview: ${nextTheme}`);
            });
        });
    };

    bindSegmentedDemos();
    bindRangeModeDemos();
    bindStyleTokenResizer();
    bindToggleDemos();
    bindWorkflowDemos();
    bindProductDemos();
    bindStyleTokenTableDemos();
    bindStyleTokenFilterMenus();
    bindStyleTokenAgentBrowserDemo();
    bindStyleTokenPagination();
    bindSecondaryButtonDemo();
    bindStyleTokenPrimaryButtonDemo();
    bindStyleTokenThemeToggleDemo();

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
