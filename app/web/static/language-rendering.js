/* Code version: v1.0.0-codex.1 */

(function initializeLanguageRendering() {
    "use strict";

    const SIMPLIFIED_CHINESE_LANGUAGE = "zh-CN";
    const HAN_CHARACTER_PATTERN = /[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]/u;
    const LANGUAGE_BOUNDARY_SELECTOR = [
        "a",
        "button",
        "dd",
        "dt",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "input",
        "label",
        "li",
        "option",
        "p",
        "small",
        "span",
        "strong",
        "td",
        "th",
        "time",
        "textarea",
    ].join(",");
    const LANGUAGE_TEXT_ATTRIBUTES = [
        "alt",
        "aria-label",
        "placeholder",
        "title",
        "value",
    ];

    const hasHanCharacters = (value) => HAN_CHARACTER_PATTERN.test(String(value || ""));

    function hasExplicitAncestorLanguage(element) {
        let current = element;
        const documentRoot = document.documentElement;
        while (current && current !== documentRoot) {
            if (current.hasAttribute("lang")) return true;
            current = current.parentElement;
        }
        return false;
    }

    function languageBoundaryFor(element) {
        let current = element;
        while (current && current !== document.body && current !== document.documentElement) {
            if (
                current.matches(LANGUAGE_BOUNDARY_SELECTOR)
                || current.hasAttribute("data-language-boundary")
            ) {
                return current;
            }
            current = current.parentElement;
        }
        return element;
    }

    function annotateElement(element) {
        if (!(element instanceof Element)) return;
        if (
            element === document.documentElement
            || element === document.body
            || element.hasAttribute("lang")
            || hasExplicitAncestorLanguage(element)
        ) {
            return;
        }

        const directTextContainsHan = Array.from(element.childNodes).some(
            (child) => child.nodeType === Node.TEXT_NODE && hasHanCharacters(child.nodeValue),
        );
        const attributeContainsHan = LANGUAGE_TEXT_ATTRIBUTES.some((attribute) =>
            hasHanCharacters(element.getAttribute(attribute)),
        );
        const valuePropertyContainsHan = "value" in element && hasHanCharacters(element.value);
        if (!directTextContainsHan && !attributeContainsHan && !valuePropertyContainsHan) return;

        const boundary = languageBoundaryFor(element);
        if (
            boundary
            && boundary !== document.documentElement
            && boundary !== document.body
            && !boundary.hasAttribute("lang")
            && !hasExplicitAncestorLanguage(boundary)
        ) {
            boundary.setAttribute("lang", SIMPLIFIED_CHINESE_LANGUAGE);
        }
    }

    function annotateSubtree(node) {
        if (node.nodeType === Node.TEXT_NODE) {
            annotateElement(node.parentElement);
            return;
        }
        if (!(node instanceof Element)) return;

        annotateElement(node);
        node.querySelectorAll("*").forEach(annotateElement);
    }

    function start() {
        annotateSubtree(document.documentElement);

        const observer = new MutationObserver((mutations) => {
            mutations.forEach((mutation) => {
                if (mutation.type === "characterData") {
                    annotateElement(mutation.target.parentElement);
                    return;
                }
                if (mutation.type === "attributes") {
                    annotateElement(mutation.target);
                    return;
                }
                mutation.addedNodes.forEach(annotateSubtree);
            });
        });
        observer.observe(document.documentElement, {
            attributeFilter: LANGUAGE_TEXT_ATTRIBUTES,
            attributes: true,
            characterData: true,
            childList: true,
            subtree: true,
        });
        document.addEventListener("input", (event) => {
            annotateElement(event.target);
        }, true);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", start, { once: true });
    } else {
        start();
    }
})();
