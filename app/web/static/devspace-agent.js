/* Code version: v1.5.7-codex.1 */

(function initializeDevSpaceAgent() {
    "use strict";

    const runtimeForm = document.getElementById("agent_runtime_form");
    const promptForm = document.getElementById("agent_prompt_form");
    if (!(runtimeForm instanceof HTMLFormElement) || !(promptForm instanceof HTMLFormElement)) return;

    const elements = {
        runtimeChip: document.getElementById("agent_runtime_chip"),
        phaseChip: document.getElementById("agent_phase_chip"),
        statusMessage: document.getElementById("agent_empty_response"),
        responseOutput: document.getElementById("agent_response_output"),
        emptyResponse: document.getElementById("agent_empty_response"),
        conversationLink: document.getElementById("agent_conversation_link"),
        logPath: document.getElementById("agent_log_path"),
        runtimeStart: document.getElementById("agent_runtime_start"),
        runtimeStop: document.getElementById("agent_runtime_stop"),
        ask: document.getElementById("agent_ask_button"),
        stop: document.getElementById("agent_stop_button"),
        targetUrl: document.querySelector("[data-agent-target-url]"),
        port: document.querySelector("[data-agent-port]"),
        allowedRoot: runtimeForm.querySelector('input[name="allowed_root"]'),
        projectPath: document.querySelector("[data-agent-project-path]"),
        projectName: document.querySelector("[data-agent-project-name]"),
        platformHeading: document.querySelector("[data-agent-platform-heading]"),
        workspacePath: promptForm.querySelector('input[name="workspace_path"]'),
        promptInput: document.querySelector("[data-agent-prompt-input]"),
    };

    function formPayload(form) {
        return Object.fromEntries(new FormData(form).entries());
    }

    async function requestJson(url, options = {}) {
        const response = await fetch(url, {
            ...options,
            headers: {"Content-Type": "application/json", ...(options.headers || {})},
        });
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.error || `Request failed with ${response.status}.`);
        return payload;
    }

    function setChip(element, label, state) {
        if (!element) return;
        element.textContent = label;
        element.className = `status-chip status-${state}`;
    }

    const platformLabels = {chatgpt: "ChatGPT", gemini: "Gemini", grok: "Grok"};
    const platformUrls = {
        chatgpt: "https://chatgpt.com/",
        gemini: "https://gemini.google.com/app",
        grok: "https://grok.com/",
    };
    const platformCookieName = "cachelikes_agent_platform";

    function normalizePlatform(platform) {
        return Object.prototype.hasOwnProperty.call(platformLabels, platform)
            ? platform
            : "chatgpt";
    }

    function rememberPlatform(platform) {
        document.cookie = `${platformCookieName}=${normalizePlatform(platform)}; Path=/; SameSite=Lax`;
    }

    function updatePlatformSelection(platform) {
        const normalizedPlatform = normalizePlatform(platform);
        const combobox = document.querySelector(".agent-platform-combobox");
        const input = combobox?.querySelector('[data-agent-combobox-input][name="platform"]');
        const trigger = combobox?.querySelector("[data-agent-combobox-trigger]");
        const selectedLabel = combobox?.querySelector("[data-agent-combobox-selected-label]");
        const selectedIcon = combobox?.querySelector("[data-agent-combobox-selected-icon]");
        const options = combobox
            ? Array.from(combobox.querySelectorAll("[data-agent-combobox-option]"))
            : [];
        const selectedOption = options.find(
            (option) => option.dataset.agentComboboxOption === normalizedPlatform,
        );
        const label = selectedOption?.dataset.agentComboboxLabel || platformLabels[normalizedPlatform];
        const icon = selectedOption?.dataset.agentComboboxIcon || "";

        if (input instanceof HTMLInputElement) input.value = normalizedPlatform;
        if (selectedLabel) selectedLabel.textContent = label;
        if (selectedIcon && icon) selectedIcon.style.setProperty("--cache-source-mark", `url('${icon}')`);
        if (trigger) trigger.setAttribute("aria-label", `Platform: ${label}`);
        options.forEach((option) => {
            const selected = option === selectedOption;
            option.classList.toggle("is-selected", selected);
            option.classList.toggle("is-active", selected);
            option.setAttribute("aria-selected", String(selected));
        });

        return normalizedPlatform;
    }

    function syncPlatformUi(platform) {
        const normalizedPlatform = updatePlatformSelection(platform);
        const label = platformLabels[normalizedPlatform];
        if (elements.platformHeading) elements.platformHeading.textContent = `${label} Web Agent`;
        if (elements.promptInput) elements.promptInput.placeholder = `Ask ${label} to inspect, change, or verify this workspace…`;
        if (elements.ask) {
            elements.ask.setAttribute("aria-label", `Ask ${label}`);
            elements.ask.setAttribute("title", `Ask ${label}`);
        }
        if (elements.targetUrl) elements.targetUrl.value = platformUrls[normalizedPlatform];
    }

    function projectNameFromPath(path) {
        const normalizedPath = String(path || "").replace(/[\\/]+$/, "");
        return normalizedPath.split(/[\\/]/).pop() || normalizedPath;
    }

    function syncProjectPath(path) {
        const normalizedPath = String(path || "").trim();
        if (!normalizedPath) return;
        if (elements.allowedRoot) elements.allowedRoot.value = normalizedPath;
        if (elements.workspacePath) elements.workspacePath.value = normalizedPath;
        if (elements.projectName) elements.projectName.textContent = projectNameFromPath(normalizedPath);
    }

    function initializeComboboxes() {
        const comboboxes = Array.from(document.querySelectorAll("[data-agent-combobox]"));
        const closeCombobox = (combobox) => {
            const trigger = combobox.querySelector("[data-agent-combobox-trigger]");
            const menu = combobox.querySelector("[data-agent-combobox-menu]");
            combobox.classList.remove("is-agent-combobox-open");
            trigger?.setAttribute("aria-expanded", "false");
            if (menu) menu.hidden = true;
        };
        const openCombobox = (combobox) => {
            comboboxes.forEach((other) => {
                if (other !== combobox) closeCombobox(other);
            });
            const trigger = combobox.querySelector("[data-agent-combobox-trigger]");
            const menu = combobox.querySelector("[data-agent-combobox-menu]");
            const isOpen = combobox.classList.contains("is-agent-combobox-open");
            combobox.classList.toggle("is-agent-combobox-open", !isOpen);
            trigger?.setAttribute("aria-expanded", String(!isOpen));
            if (menu) menu.hidden = isOpen;
        };

        comboboxes.forEach((combobox) => {
            const input = combobox.querySelector("[data-agent-combobox-input]");
            const trigger = combobox.querySelector("[data-agent-combobox-trigger]");
            const menu = combobox.querySelector("[data-agent-combobox-menu]");
            if (!(input instanceof HTMLInputElement) || !(trigger instanceof HTMLButtonElement) || !menu) return;
            const options = Array.from(menu.querySelectorAll("[data-agent-combobox-option]"));
            trigger.addEventListener("click", () => openCombobox(combobox));
            options.forEach((option) => option.addEventListener("click", () => {
                input.value = option.dataset.agentComboboxOption || "";
                const label = combobox.querySelector("[data-agent-combobox-selected-label]");
                const icon = combobox.querySelector("[data-agent-combobox-selected-icon]");
                if (label) label.textContent = option.dataset.agentComboboxLabel || "";
                if (icon && option.dataset.agentComboboxIcon) icon.style.setProperty("--cache-source-mark", `url('${option.dataset.agentComboboxIcon}')`);
                if (icon?.tagName === "IMG" && option.dataset.agentComboboxIcon) icon.src = option.dataset.agentComboboxIcon;
                const fieldLabel = combobox.closest(".field")?.querySelector(".field-label")?.textContent?.trim() || "Option";
                trigger.setAttribute("aria-label", `${fieldLabel}: ${option.dataset.agentComboboxLabel || ""}`);
                options.forEach((other) => {
                    const selected = other === option;
                    other.classList.toggle("is-selected", selected);
                    other.classList.toggle("is-active", selected);
                    other.setAttribute("aria-selected", String(selected));
                });
                closeCombobox(combobox);
                if (input.name === "platform") {
                    const selectedPlatform = syncPlatformUi(input.value);
                    rememberPlatform(selectedPlatform);
                }
            }));
        });
        document.addEventListener("click", (event) => {
            if (!(event.target instanceof Element) || event.target.closest("[data-agent-combobox]")) return;
            comboboxes.forEach(closeCombobox);
        });
        document.addEventListener("keydown", (event) => {
            if (event.key !== "Escape") return;
            comboboxes.forEach(closeCombobox);
        });
    }

    syncPlatformUi(normalizePlatform(document.querySelector('input[name="platform"]')?.value || "chatgpt"));
    elements.projectPath?.addEventListener("change", () => syncProjectPath(elements.projectPath.value));

    const cacheDockLink = document.querySelector('[data-dock-section="cache"]');
    cacheDockLink?.addEventListener("click", (event) => {
        const platform = normalizePlatform(document.querySelector('input[name="platform"]')?.value || "chatgpt");
        const targetUrl = new URL("/cache/chatgpt", window.location.origin);
        targetUrl.searchParams.set("agent_platform", platform);
        event.preventDefault();
        window.location.assign(`${targetUrl.pathname}${targetUrl.search}`);
    }, true);

    function render(payload) {
        const runtime = payload.runtime || {};
        const agent = payload.agent || {};
        syncPlatformUi(document.querySelector('input[name="platform"]')?.value || runtime.settings?.platform || "chatgpt");
        if (elements.port && runtime.settings?.port) elements.port.value = String(runtime.settings.port);
        setChip(elements.runtimeChip, runtime.ready ? "ready" : "offline", runtime.ready ? "running" : "idle");
        setChip(elements.phaseChip, agent.phase || "idle", agent.phase || "idle");
        if (elements.statusMessage) elements.statusMessage.textContent = agent.message || "Ready.";
        if (elements.responseOutput) elements.responseOutput.textContent = agent.response || "";
        if (elements.emptyResponse) elements.emptyResponse.hidden = Boolean(agent.response);
        if (elements.logPath instanceof HTMLInputElement) elements.logPath.value = runtime.log_path || "";
        if (elements.conversationLink) {
            elements.conversationLink.hidden = !agent.conversation_url;
            if (agent.conversation_url) elements.conversationLink.href = agent.conversation_url;
        }
        const agentRunning = Boolean(agent.running);
        const runtimeManaged = Boolean(runtime.managed);
        if (elements.runtimeStart) elements.runtimeStart.disabled = Boolean(runtime.ready);
        if (elements.runtimeStop) elements.runtimeStop.disabled = !runtimeManaged || agentRunning;
        if (elements.ask) elements.ask.disabled = !runtime.ready || agentRunning;
        if (elements.stop) elements.stop.disabled = !agentRunning;
    }

    async function mutate(url, payload = {}) {
        try {
            render(await requestJson(url, {method: "POST", body: JSON.stringify(payload)}));
        } catch (error) {
            if (elements.statusMessage) elements.statusMessage.textContent = error.message;
            setChip(elements.phaseChip, "failed", "failed");
        }
    }

    runtimeForm.addEventListener("submit", (event) => {
        event.preventDefault();
        mutate("/api/agent/runtime/start", formPayload(runtimeForm));
    });
    initializeComboboxes();
    elements.runtimeStop?.addEventListener("click", () => mutate("/api/agent/runtime/stop"));
    promptForm.addEventListener("submit", (event) => {
        event.preventDefault();
        mutate("/api/agent/ask", formPayload(promptForm));
    });
    elements.stop?.addEventListener("click", () => mutate("/api/agent/stop"));
    window.setInterval(async () => {
        try {
            render(await requestJson("/api/agent/status"));
        } catch (_error) {
        }
    }, 2_000);
})();
