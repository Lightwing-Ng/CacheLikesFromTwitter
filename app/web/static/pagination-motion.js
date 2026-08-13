/* Code version: v1.1.0-codex.1 */

(() => {
    "use strict";

    const DEFAULT_MOTION_DURATION_MS = 560;

    function ensurePaginationIndicator(pagination) {
        if (!pagination) return null;
        let indicator = pagination.querySelector(".local-store-pagination-indicator");
        if (!indicator) {
            indicator = document.createElement("span");
            indicator.className = "local-store-pagination-indicator";
            indicator.setAttribute("aria-hidden", "true");
            pagination.prepend(indicator);
        }
        return indicator;
    }

    function positionPaginationIndicator(pagination, target, { immediate = false } = {}) {
        if (!pagination || !target) return;
        const indicator = ensurePaginationIndicator(pagination);
        if (!indicator) return;

        const paginationRect = pagination.getBoundingClientRect();
        const targetRect = target.getBoundingClientRect();
        const x = targetRect.left - paginationRect.left - pagination.clientLeft;
        const y = targetRect.top - paginationRect.top - pagination.clientTop;
        if (immediate) indicator.style.transition = "none";
        indicator.style.width = `${targetRect.width}px`;
        indicator.style.height = `${targetRect.height}px`;
        indicator.style.transform = `translate3d(${x}px, ${y}px, 0)`;
        pagination.classList.add("is-animated");
        if (immediate) {
            void indicator.offsetWidth;
            indicator.style.removeProperty("transition");
        }
    }

    function clearPaginationAnimation(pagination) {
        const timer = pagination?.__cacheLikesPaginationAnimationTimer;
        if (timer) window.clearTimeout(timer);
        if (pagination) {
            delete pagination.__cacheLikesPaginationAnimationTimer;
            pagination.classList.remove("is-animating");
        }
    }

    function getPaginationMotionDurationMs(
        pagination,
        fallback = DEFAULT_MOTION_DURATION_MS,
    ) {
        if (!pagination) return fallback;
        const rawDuration = window.getComputedStyle(pagination)
            .getPropertyValue("--local-store-pagination-motion-duration")
            .trim();
        const parsedDuration = Number.parseFloat(rawDuration);
        if (!Number.isFinite(parsedDuration) || parsedDuration <= 0) return fallback;
        if (rawDuration.endsWith("ms")) return parsedDuration;
        if (rawDuration.endsWith("s")) return parsedDuration * 1000;
        return fallback;
    }

    function getPaginationTargetPage(button, pageTargetAttribute = "data-pagination-target") {
        const page = Number(button?.getAttribute(pageTargetAttribute));
        return Number.isFinite(page) && page > 0 ? page : 0;
    }

    function findPaginationTarget(
        pagination,
        targetPage,
        pageTargetAttribute = "data-pagination-target",
    ) {
        const normalizedTargetPage = Number(targetPage);
        if (!Number.isFinite(normalizedTargetPage) || normalizedTargetPage <= 0) return null;
        return Array.from(pagination.querySelectorAll(".local-store-page-button"))
            .find((button) => (
                !button.classList.contains("local-store-page-nav")
                && !button.classList.contains("local-store-page-placeholder")
                && getPaginationTargetPage(button, pageTargetAttribute) === normalizedTargetPage
            )) || null;
    }

    function capturePaginationAnimation(
        pagination,
        targetPage,
        { pageTargetAttribute = "data-pagination-target" } = {},
    ) {
        if (!pagination || pagination.hidden) return null;
        const current = pagination.querySelector(".local-store-page-button.is-active")
            || pagination.querySelector(".local-store-page-button[data-pagination-current=\"1\"]");
        const normalizedTargetPage = Number(targetPage);
        if (!current || !Number.isFinite(normalizedTargetPage) || normalizedTargetPage <= 0) return null;

        const currentRect = current.getBoundingClientRect();
        return {
            fromRect: {
                left: currentRect.left,
                top: currentRect.top,
                width: currentRect.width,
                height: currentRect.height,
            },
            targetPage: normalizedTargetPage,
            pageTargetAttribute,
        };
    }

    function animatePaginationIndicator(
        pagination,
        animationState,
        { pageTargetAttribute = animationState?.pageTargetAttribute || "data-pagination-target" } = {},
    ) {
        if (!pagination || pagination.hidden) {
            positionPaginationIndicator(
                pagination,
                pagination?.querySelector(".local-store-page-button.is-active"),
                { immediate: true },
            );
            return;
        }

        const fromRect = animationState?.fromRect;
        const target = findPaginationTarget(pagination, animationState?.targetPage, pageTargetAttribute);
        if (!target || !fromRect) {
            positionPaginationIndicator(
                pagination,
                pagination.querySelector(".local-store-page-button.is-active"),
                { immediate: true },
            );
            return;
        }

        const indicator = ensurePaginationIndicator(pagination);
        if (!indicator) return;
        const paginationRect = pagination.getBoundingClientRect();
        const targetRect = target.getBoundingClientRect();
        const fromX = fromRect.left - paginationRect.left - pagination.clientLeft;
        const fromY = fromRect.top - paginationRect.top - pagination.clientTop;
        const targetX = targetRect.left - paginationRect.left - pagination.clientLeft;
        const targetY = targetRect.top - paginationRect.top - pagination.clientTop;
        clearPaginationAnimation(pagination);
        pagination.classList.add("is-animated", "is-animating");
        indicator.style.transition = "none";
        indicator.style.width = `${fromRect.width}px`;
        indicator.style.height = `${fromRect.height}px`;
        indicator.style.transform = `translate3d(${fromX}px, ${fromY}px, 0)`;
        void indicator.offsetWidth;
        indicator.style.removeProperty("transition");
        window.requestAnimationFrame(() => {
            indicator.style.width = `${targetRect.width}px`;
            indicator.style.height = `${targetRect.height}px`;
            indicator.style.transform = `translate3d(${targetX}px, ${targetY}px, 0)`;
        });
        pagination.__cacheLikesPaginationAnimationTimer = window.setTimeout(() => {
            delete pagination.__cacheLikesPaginationAnimationTimer;
            pagination.classList.remove("is-animating");
            positionPaginationIndicator(pagination, target, { immediate: true });
        }, getPaginationMotionDurationMs(pagination));
    }

    window.CACHELIKES_PAGINATION_MOTION = Object.freeze({
        animatePaginationIndicator,
        capturePaginationAnimation,
        clearPaginationAnimation,
        ensurePaginationIndicator,
        getPaginationMotionDurationMs,
        positionPaginationIndicator,
    });
})();
