/* Code version: v1.0.4-codex.1 */

(() => {
    "use strict";

    const selector = ".segmented-control[data-option-count], .range-mode-shell[data-option-count]";

    const getOptions = (shell) => Array.from(shell.children)
        .filter((option) => option instanceof HTMLElement)
        .filter((option) => option.classList.contains("segmented-control-option") || option.classList.contains("range-mode-option"))
        .filter((option) => !option.hidden);

    const getActiveIndex = (shell, options) => {
        const checkedIndex = options.findIndex((option) => {
            const input = option.querySelector("input");
            return input instanceof HTMLInputElement && input.checked && !input.disabled;
        });
        if (checkedIndex >= 0) return checkedIndex;

        const markedIndex = options.findIndex((option) => (
            option.classList.contains("is-active")
            || option.getAttribute("aria-checked") === "true"
        ));
        if (markedIndex >= 0) return markedIndex;

        const declaredIndex = Number.parseInt(shell.dataset.segmentedActiveIndex || "", 10);
        if (Number.isInteger(declaredIndex)) return declaredIndex;
        return 0;
    };

    const setAttributeIfChanged = (element, name, value) => {
        if (element.getAttribute(name) !== value) element.setAttribute(name, value);
    };

    const setStylePropertyIfChanged = (element, property, value) => {
        if (element.style.getPropertyValue(property) !== value) {
            element.style.setProperty(property, value);
        }
    };

    const syncMeasuredPill = (shell, options, activeIndex) => {
        if (shell.dataset.segmentedPill !== "measured") {
            return;
        }
        const activeOption = options[activeIndex];
        if (!(activeOption instanceof HTMLElement)) {
            return;
        }
        const shellStyles = window.getComputedStyle(shell);
        const thumbInset = Number.parseFloat(shellStyles.getPropertyValue("--mode-switch-thumb-inset"))
            || Number.parseFloat(shellStyles.paddingLeft)
            || 0;
        setStylePropertyIfChanged(
            shell,
            "--segmented-pill-left",
            `${Math.max(0, activeOption.offsetLeft - thumbInset)}px`,
        );
        setStylePropertyIfChanged(
            shell,
            "--segmented-pill-width",
            `${Math.max(1, activeOption.offsetWidth)}px`,
        );
        shell.classList.add("is-pill-ready");
    };

    const sync = (shell) => {
        if (!(shell instanceof HTMLElement)) return;
        const options = getOptions(shell);
        const optionCount = Math.max(options.length, 1);
        const activeIndex = Math.min(
            Math.max(getActiveIndex(shell, options), 0),
            optionCount - 1,
        );

        setAttributeIfChanged(shell, "data-option-count", String(optionCount));
        setAttributeIfChanged(shell, "data-segmented-active-index", String(activeIndex));
        setStylePropertyIfChanged(shell, "--segmented-option-count", String(optionCount));
        setStylePropertyIfChanged(shell, "--segmented-active-index", String(activeIndex));
        syncMeasuredPill(shell, options, activeIndex);

        options.forEach((option, index) => {
            if (option.querySelector("input")) return;
            const isActive = index === activeIndex;
            option.classList.toggle("is-active", isActive);
            setAttributeIfChanged(option, "aria-checked", String(isActive));
        });
    };

    const bind = (shell) => {
        if (!(shell instanceof HTMLElement) || shell.dataset.segmentedControlBound === "1") return;
        shell.dataset.segmentedControlBound = "1";
        shell.addEventListener("change", () => sync(shell));
        shell.addEventListener("click", (event) => {
            const target = event.target instanceof Element ? event.target : null;
            const option = target?.closest(".segmented-control-option");
            if (!(option instanceof HTMLElement) || !shell.contains(option)) return;
            window.requestAnimationFrame(() => sync(shell));
        });
        sync(shell);
        if (shell.dataset.segmentedPill === "measured" && typeof ResizeObserver === "function") {
            const observer = new ResizeObserver(() => sync(shell));
            observer.observe(shell);
        }
    };

    const syncAll = () => {
        document.querySelectorAll(selector).forEach((shell) => {
            bind(shell);
            sync(shell);
        });
    };

    window.CACHELIKES_SEGMENTED_CONTROLS = Object.freeze({sync, syncAll});
    syncAll();
    window.addEventListener("resize", syncAll, {passive: true});

    if (typeof MutationObserver === "function") {
        const observer = new MutationObserver((records) => {
            const includesSegmentedControl = records.some((record) => (
                Array.from(record.addedNodes).some((node) => (
                    node instanceof Element
                    && (node.matches(selector) || node.querySelector(selector))
                ))
            ));
            if (includesSegmentedControl) {
                syncAll();
            }
        });
        observer.observe(document.body, {
            subtree: true,
            childList: true,
        });
    }
})();
