/* Code version: v1.0.0-codex.1 */

(function initializeBrowserSearch() {
    "use strict";

    const searchRoot = document.querySelector("[data-browser-search]");
    const input = searchRoot?.querySelector("[data-browser-search-input]");
    const menu = searchRoot?.querySelector("[data-browser-search-menu]");
    const form = input
        ? document.getElementById(input.getAttribute("form") || "") || input.form
        : null;
    const dataNode = document.getElementById("browser_search_suggestion_data");
    if (!searchRoot || !input || !menu || !form) return;

    const storageKey = "cachelikes:browser-search-history:v1";
    const maximumHistory = 8;
    const maximumSuggestions = 8;
    let activeIndex = -1;
    let visibleCandidates = [];

    function normalizeDisplay(value) {
        return String(value || "").replace(/\s+/g, " ").trim().slice(0, 120);
    }

    function normalizeSearch(value) {
        return normalizeDisplay(value)
            .normalize("NFKC")
            .toLocaleLowerCase()
            .replace(/[^\p{L}\p{N}]+/gu, " ")
            .trim();
    }

    function compactSearch(value) {
        return normalizeSearch(value).replace(/\s+/g, "");
    }

    function searchTokens(value) {
        return normalizeSearch(value).split(/\s+/).filter(Boolean);
    }

    function isSubsequence(needle, haystack) {
        if (!needle) return true;
        let cursor = 0;
        for (const character of haystack) {
            if (character === needle[cursor]) cursor += 1;
            if (cursor === needle.length) return true;
        }
        return false;
    }

    function editDistance(left, right) {
        if (left === right) return 0;
        if (!left) return right.length;
        if (!right) return left.length;

        let previous = Array.from({ length: right.length + 1 }, (_value, index) => index);
        for (let row = 1; row <= left.length; row += 1) {
            const current = [row];
            for (let column = 1; column <= right.length; column += 1) {
                const substitution = previous[column - 1] + (left[row - 1] === right[column - 1] ? 0 : 1);
                current[column] = Math.min(
                    substitution,
                    previous[column] + 1,
                    current[column - 1] + 1,
                );
            }
            previous = current;
        }
        return previous[right.length];
    }

    function scoreCandidate(value, query) {
        const normalizedValue = normalizeSearch(value);
        const queryParts = searchTokens(query);
        if (!normalizedValue) return null;
        if (!queryParts.length) return 0;

        const candidateParts = searchTokens(normalizedValue);
        const compactValue = compactSearch(normalizedValue);
        let score = 0;
        for (const queryPart of queryParts) {
            let bestScore = Number.POSITIVE_INFINITY;
            const compactQueryPart = queryPart.replace(/\s+/g, "");
            for (const candidatePart of [...candidateParts, compactValue]) {
                const compactCandidatePart = candidatePart.replace(/\s+/g, "");
                if (candidatePart === queryPart) {
                    bestScore = Math.min(bestScore, 0);
                } else if (candidatePart.startsWith(queryPart)) {
                    bestScore = Math.min(bestScore, 1);
                } else if (candidatePart.includes(queryPart)) {
                    bestScore = Math.min(bestScore, 2);
                } else if (isSubsequence(compactQueryPart, compactCandidatePart)) {
                    bestScore = Math.min(bestScore, 3 + (compactCandidatePart.length - compactQueryPart.length) / 100);
                } else {
                    const tolerance = queryPart.length >= 5 ? 2 : 1;
                    const distance = editDistance(compactQueryPart, compactCandidatePart);
                    if (distance <= tolerance) bestScore = Math.min(bestScore, 4 + distance);
                }
            }
            if (!Number.isFinite(bestScore)) return null;
            score += bestScore;
        }
        if (normalizedValue.startsWith(normalizeSearch(query))) score -= 2;
        return score;
    }

    function parseServerCandidates() {
        if (!dataNode) return [];
        try {
            const parsed = JSON.parse(dataNode.textContent || "[]");
            if (!Array.isArray(parsed)) return [];
            return parsed
                .map((item) => ({
                    value: normalizeDisplay(item?.value),
                    detail: normalizeDisplay(item?.detail) || "Cached resource",
                    kind: "recommended",
                }))
                .filter((item) => item.value);
        } catch (_error) {
            return [];
        }
    }

    function readHistory() {
        try {
            const parsed = JSON.parse(window.localStorage.getItem(storageKey) || "[]");
            return Array.isArray(parsed)
                ? parsed.map(normalizeDisplay).filter(Boolean).slice(0, maximumHistory)
                : [];
        } catch (_error) {
            return [];
        }
    }

    function rememberSearch(value) {
        const normalized = normalizeDisplay(value);
        if (!normalized) return;
        const normalizedKey = normalizeSearch(normalized);
        const nextHistory = [
            normalized,
            ...readHistory().filter((item) => normalizeSearch(item) !== normalizedKey),
        ];
        try {
            window.localStorage.setItem(storageKey, JSON.stringify(nextHistory.slice(0, maximumHistory)));
        } catch (_error) {
        }
    }

    function collectCandidates() {
        const candidates = [
            ...readHistory().map((value) => ({ value, detail: "Recent search", kind: "history" })),
            ...parseServerCandidates(),
        ];
        document.querySelectorAll(
            ".browser-media-card-title, .browser-session-table-title, .browser-chat-message-title",
        ).forEach((node) => {
            const value = normalizeDisplay(node.textContent);
            if (value) candidates.push({ value, detail: "Cached resource", kind: "recommended" });
        });

        const seen = new Set();
        return candidates.filter((candidate) => {
            const key = normalizeSearch(candidate.value);
            if (!key || seen.has(key)) return false;
            seen.add(key);
            return true;
        });
    }

    function setMenuOpen(isOpen) {
        menu.hidden = !isOpen;
        searchRoot.classList.toggle("is-browser-search-open", isOpen);
        input.setAttribute("aria-expanded", String(isOpen));
        if (!isOpen) {
            activeIndex = -1;
            input.removeAttribute("aria-activedescendant");
        }
    }

    function setActiveIndex(nextIndex) {
        if (!visibleCandidates.length) return;
        activeIndex = (nextIndex + visibleCandidates.length) % visibleCandidates.length;
        const options = Array.from(menu.querySelectorAll("[data-browser-search-option]"));
        options.forEach((option, index) => {
            const isActive = index === activeIndex;
            option.classList.toggle("is-active", isActive);
            option.setAttribute("aria-selected", String(isActive));
        });
        const activeOption = options[activeIndex];
        if (activeOption) {
            input.setAttribute("aria-activedescendant", activeOption.id);
            activeOption.scrollIntoView({ block: "nearest" });
        }
    }

    function selectCandidate(candidate) {
        input.value = candidate.value;
        rememberSearch(candidate.value);
        setMenuOpen(false);
        form.requestSubmit();
    }

    function renderMenu(query) {
        const queryText = normalizeDisplay(query);
        const matches = collectCandidates()
            .map((candidate, order) => ({
                ...candidate,
                score: scoreCandidate(candidate.value, queryText),
                order,
            }))
            .filter((candidate) => candidate.score !== null)
            .sort((left, right) => left.score - right.score || left.order - right.order)
            .slice(0, maximumSuggestions);
        visibleCandidates = matches;
        activeIndex = -1;
        menu.replaceChildren();

        const heading = document.createElement("div");
        heading.className = "browser-search-suggestions-heading";
        heading.textContent = queryText ? "Search recommendations" : "Recent and recommended";
        menu.append(heading);

        if (!matches.length) {
            const emptyState = document.createElement("div");
            emptyState.className = "browser-search-suggestions-empty";
            emptyState.textContent = "Press Enter to search this cache.";
            menu.append(emptyState);
        } else {
            matches.forEach((candidate, index) => {
                const option = document.createElement("button");
                option.type = "button";
                option.className = "browser-search-suggestion";
                option.id = `browser_search_option_${index}`;
                option.dataset.browserSearchOption = "true";
                option.setAttribute("role", "option");
                option.setAttribute("aria-selected", "false");

                const value = document.createElement("span");
                value.className = "browser-search-suggestion-value";
                value.textContent = candidate.value;
                const detail = document.createElement("span");
                detail.className = "browser-search-suggestion-detail";
                detail.textContent = candidate.detail;
                option.append(value, detail);
                option.addEventListener("mousedown", (event) => event.preventDefault());
                option.addEventListener("click", () => selectCandidate(candidate));
                menu.append(option);
            });
        }
        setMenuOpen(true);
    }

    input.addEventListener("focus", () => renderMenu(input.value));
    input.addEventListener("click", () => renderMenu(input.value));
    input.addEventListener("input", () => renderMenu(input.value));
    input.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
            if (menu.hidden) return;
            event.preventDefault();
            setMenuOpen(false);
            return;
        }
        if (event.key === "ArrowDown" || event.key === "ArrowUp") {
            if (menu.hidden) renderMenu(input.value);
            if (!visibleCandidates.length) return;
            event.preventDefault();
            setActiveIndex(activeIndex + (event.key === "ArrowDown" ? 1 : -1));
            return;
        }
        if (event.key === "Enter" && !menu.hidden && activeIndex >= 0) {
            event.preventDefault();
            selectCandidate(visibleCandidates[activeIndex]);
            return;
        }
        if (event.key === "Tab") setMenuOpen(false);
    });

    form.addEventListener("submit", () => {
        rememberSearch(input.value);
        setMenuOpen(false);
    });
    document.addEventListener("pointerdown", (event) => {
        if (!searchRoot.contains(event.target)) setMenuOpen(false);
    });
})();
