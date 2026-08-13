/* Code version: v2.1.0-codex.1 */

(function initializeAgentWorkspace() {
    "use strict";

    const runtimeForm = document.getElementById("agent_runtime_form");
    const promptForm = document.getElementById("agent_prompt_form");
    if (!(runtimeForm instanceof HTMLFormElement) || !(promptForm instanceof HTMLFormElement)) return;

    const elements = {
        phaseChip: document.getElementById("agent_phase_chip"),
        statusMessage: document.getElementById("agent_empty_response"),
        responseOutput: document.getElementById("agent_response_output"),
        conversationLink: document.getElementById("agent_conversation_link"),
        logPath: document.getElementById("agent_log_path"),
        runtimeStart: document.getElementById("agent_runtime_start"),
        runtimeStop: document.getElementById("agent_runtime_stop"),
        ask: document.getElementById("agent_ask_button"),
        stop: document.getElementById("agent_stop_button"),
        targetUrl: runtimeForm.querySelector("[data-agent-target-url]"),
        port: runtimeForm.querySelector("[data-agent-port]"),
        allowedRoot: runtimeForm.querySelector('input[name="allowed_root"]'),
        runtimeWorkspace: runtimeForm.querySelector("[data-agent-runtime-workspace]"),
        projectPath: document.querySelector("[data-agent-project-path]"),
        projectChoose: document.getElementById("agent_project_path_choose"),
        projectName: document.querySelector("[data-agent-project-name]"),
        platformHeading: document.querySelector("[data-agent-platform-heading]"),
        engineKicker: document.querySelector("[data-agent-engine-kicker]"),
        engineCopy: document.querySelector("[data-agent-engine-copy]"),
        readiness: document.querySelector(".agent-readiness"),
        readinessMessage: document.getElementById("agent_readiness_message"),
        workspacePath: promptForm.querySelector('input[name="workspace_path"]'),
        promptPlatform: promptForm.querySelector("[data-agent-prompt-platform]"),
        promptBrowser: promptForm.querySelector("[data-agent-prompt-browser]"),
        promptInput: promptForm.querySelector("[data-agent-prompt-input]"),
        activityPanel: document.getElementById("agent_activity_panel"),
        activityCount: document.getElementById("agent_activity_count"),
        activityList: document.getElementById("agent_activity_list"),
        webOnly: Array.from(document.querySelectorAll("[data-agent-web-only]")),
        comboboxTriggers: Array.from(document.querySelectorAll("[data-agent-combobox-trigger]")),
    };

    const platformLabels = {chatgpt: "ChatGPT", gemini: "Gemini", grok: "Grok"};
    const platformUrls = {
        chatgpt: "https://chatgpt.com/",
        gemini: "https://gemini.google.com/app",
        grok: "https://grok.com/",
    };
    const platformCookieName = "cachelikes_agent_platform";
    let lastPayload = {};
    let preferenceTimer = null;
    let activitySignature = "";

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

    function normalizePlatform(platform) {
        return Object.prototype.hasOwnProperty.call(platformLabels, platform)
            ? platform
            : "chatgpt";
    }

    function rememberPlatform(platform) {
        document.cookie = `${platformCookieName}=${normalizePlatform(platform)}; Path=/; SameSite=Lax`;
    }

    function selectedPlatform() {
        return normalizePlatform(
            document.querySelector('.agent-platform-combobox [name="platform"]')?.value || "chatgpt",
        );
    }

    function selectedBrowser() {
        return document.querySelector('.agent-browser-combobox [name="browser"]')?.value || "safari";
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
            const isSelected = option === selectedOption;
            option.classList.toggle("is-selected", isSelected);
            option.classList.toggle("is-active", isSelected);
            option.setAttribute("aria-selected", String(isSelected));
        });
        return normalizedPlatform;
    }

    function syncEngineUi(platform) {
        const normalizedPlatform = updatePlatformSelection(platform);
        const label = platformLabels[normalizedPlatform];
        const nativeMode = normalizedPlatform === "chatgpt";
        elements.webOnly.forEach((element) => {
            element.hidden = nativeMode;
        });
        if (elements.platformHeading) elements.platformHeading.textContent = `${label} Agent`;
        if (elements.engineKicker) {
            elements.engineKicker.textContent = nativeMode
                ? "Local subscription agent"
                : "DevSpace web bridge";
        }
        if (elements.engineCopy) {
            elements.engineCopy.textContent = nativeMode
                ? "Codex works directly in the selected project through the signed-in ChatGPT subscription. No MCP App, public tunnel, API key, or copied password is required."
                : `The signed-in ${label} web session coordinates the connected DevSpace tools through its subscription.`;
        }
        if (elements.promptInput) {
            elements.promptInput.placeholder = `Ask ${label} to inspect, change, or verify this workspace…`;
        }
        if (elements.ask) {
            elements.ask.setAttribute("aria-label", `Ask ${label}`);
            elements.ask.setAttribute("title", `Ask ${label}`);
        }
        if (elements.targetUrl instanceof HTMLInputElement) {
            elements.targetUrl.value = platformUrls[normalizedPlatform];
        }
        if (elements.promptPlatform instanceof HTMLInputElement) {
            elements.promptPlatform.value = normalizedPlatform;
        }
        if (elements.promptBrowser instanceof HTMLInputElement) {
            elements.promptBrowser.value = selectedBrowser();
        }
        return nativeMode;
    }

    function projectNameFromPath(path) {
        const normalizedPath = String(path || "").replace(/[\\/]+$/, "");
        return normalizedPath.split(/[\\/]/).pop() || normalizedPath;
    }

    function syncProjectPath(path) {
        const normalizedPath = String(path || "").trim();
        if (!normalizedPath) return;
        if (elements.allowedRoot instanceof HTMLInputElement) elements.allowedRoot.value = normalizedPath;
        if (elements.runtimeWorkspace instanceof HTMLInputElement) elements.runtimeWorkspace.value = normalizedPath;
        if (elements.workspacePath instanceof HTMLInputElement) elements.workspacePath.value = normalizedPath;
        if (elements.projectName) elements.projectName.textContent = projectNameFromPath(normalizedPath);
    }

    function preferencePayload() {
        return {
            workspace_path: elements.workspacePath?.value || "",
            platform: selectedPlatform(),
            browser: selectedBrowser(),
        };
    }

    function schedulePreferenceSave() {
        if (preferenceTimer !== null) window.clearTimeout(preferenceTimer);
        preferenceTimer = window.setTimeout(async () => {
            preferenceTimer = null;
            try {
                await requestJson("/api/agent/preferences", {
                    method: "POST",
                    body: JSON.stringify(preferencePayload()),
                });
            } catch (error) {
                if (elements.statusMessage) elements.statusMessage.textContent = error.message;
                setChip(elements.phaseChip, "failed", "failed");
            }
        }, 250);
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
        const toggleCombobox = (combobox) => {
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
            trigger.addEventListener("click", () => toggleCombobox(combobox));
            options.forEach((option) => option.addEventListener("click", () => {
                input.value = option.dataset.agentComboboxOption || "";
                const label = combobox.querySelector("[data-agent-combobox-selected-label]");
                const icon = combobox.querySelector("[data-agent-combobox-selected-icon]");
                if (label) label.textContent = option.dataset.agentComboboxLabel || "";
                if (icon && option.dataset.agentComboboxIcon) {
                    icon.style.setProperty("--cache-source-mark", `url('${option.dataset.agentComboboxIcon}')`);
                }
                if (icon?.tagName === "IMG" && option.dataset.agentComboboxIcon) {
                    icon.src = option.dataset.agentComboboxIcon;
                }
                const fieldLabel = combobox.closest(".field")?.querySelector(".field-label")?.textContent?.trim() || "Option";
                trigger.setAttribute("aria-label", `${fieldLabel}: ${option.dataset.agentComboboxLabel || ""}`);
                options.forEach((other) => {
                    const isSelected = other === option;
                    other.classList.toggle("is-selected", isSelected);
                    other.classList.toggle("is-active", isSelected);
                    other.setAttribute("aria-selected", String(isSelected));
                });
                closeCombobox(combobox);
                if (input.name === "platform") rememberPlatform(syncEngineUi(input.value));
                if (elements.promptBrowser instanceof HTMLInputElement) {
                    elements.promptBrowser.value = selectedBrowser();
                }
                schedulePreferenceSave();
                render(lastPayload);
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

    function readinessState(payload, platform) {
        if (platform === "chatgpt") {
            const native = payload.native || {};
            return {
                ready: Boolean(native.ready),
                message: native.message || "Checking the local Codex login…",
            };
        }
        const runtime = payload.runtime || {};
        const connection = runtime.connection || {};
        if (!runtime.ready) return {ready: false, message: "Start the local MCP runtime."};
        if (!connection.public_configured) {
            return {ready: false, message: "Add the public HTTPS origin in Settings."};
        }
        if (!connection.connected) {
            return {
                ready: false,
                message: `Add or refresh the DevSpace app in ${platformLabels[platform]}.`,
            };
        }
        return {ready: true, message: "DevSpace is connected and ready."};
    }

    function renderActivity(events, running) {
        if (!elements.activityPanel || !elements.activityList || !elements.activityCount) return;
        const safeEvents = Array.isArray(events) ? events : [];
        const nextSignature = JSON.stringify(safeEvents);
        const activityChanged = nextSignature !== activitySignature;
        if (activityChanged) {
            activitySignature = nextSignature;
            elements.activityList.replaceChildren(...safeEvents.map((event) => {
                const item = document.createElement("li");
                item.className = "agent-activity-item";
                item.dataset.status = event.status || "running";

                const status = document.createElement("span");
                status.className = "agent-activity-status";
                status.setAttribute("aria-hidden", "true");

                const content = document.createElement("span");
                content.className = "agent-activity-content";
                const label = document.createElement("span");
                label.className = "agent-activity-label";
                label.textContent = event.label || "Working";
                const detail = document.createElement("span");
                detail.className = "agent-activity-detail";
                detail.textContent = event.detail || "";
                content.append(label, detail);

                const meta = document.createElement("span");
                meta.className = "agent-activity-meta";
                meta.textContent = event.meta || "";
                item.append(status, content, meta);
                return item;
            }));
        }
        elements.activityPanel.hidden = safeEvents.length === 0;
        elements.activityCount.textContent = String(safeEvents.length);
        if (running && safeEvents.length) {
            elements.activityPanel.open = true;
            if (activityChanged) elements.activityList.scrollTop = elements.activityList.scrollHeight;
        }
    }

    function render(payload) {
        lastPayload = payload || {};
        const runtime = lastPayload.runtime || {};
        const agent = lastPayload.agent || {};
        const platform = selectedPlatform();
        const nativeMode = syncEngineUi(platform);
        const readiness = readinessState(lastPayload, platform);
        const agentRunning = Boolean(agent.running);
        const runtimeManaged = Boolean(runtime.managed);

        if (elements.port instanceof HTMLInputElement && runtime.settings?.port) {
            elements.port.value = String(runtime.settings.port);
        }
        setChip(elements.phaseChip, agent.phase || "idle", agent.phase || "idle");
        if (elements.statusMessage) elements.statusMessage.textContent = agent.message || readiness.message;
        if (elements.responseOutput) {
            elements.responseOutput.innerHTML = agent.response_html || "";
            elements.responseOutput.hidden = !agent.response;
        }
        if (elements.statusMessage) elements.statusMessage.hidden = Boolean(agent.response);
        if (elements.logPath instanceof HTMLInputElement) elements.logPath.value = runtime.log_path || "";
        if (elements.conversationLink) {
            elements.conversationLink.hidden = !agent.conversation_url;
            if (agent.conversation_url) elements.conversationLink.href = agent.conversation_url;
        }
        if (elements.readiness) elements.readiness.dataset.ready = String(readiness.ready);
        if (elements.readinessMessage) elements.readinessMessage.textContent = readiness.message;
        renderActivity(agent.activity, agentRunning);

        if (elements.runtimeStart) elements.runtimeStart.disabled = Boolean(runtime.ready) || agentRunning;
        if (elements.runtimeStop) elements.runtimeStop.disabled = !runtimeManaged || agentRunning;
        if (elements.ask) elements.ask.disabled = !readiness.ready || agentRunning;
        if (elements.stop) elements.stop.disabled = !agentRunning;
        if (elements.projectChoose) elements.projectChoose.disabled = (!nativeMode && runtime.ready) || agentRunning;
        elements.comboboxTriggers.forEach((trigger) => {
            trigger.disabled = agentRunning;
        });
    }

    async function mutate(url, payload = {}) {
        try {
            render(await requestJson(url, {method: "POST", body: JSON.stringify(payload)}));
        } catch (error) {
            if (elements.statusMessage) {
                elements.statusMessage.hidden = false;
                elements.statusMessage.textContent = error.message;
            }
            if (elements.responseOutput) elements.responseOutput.hidden = true;
            setChip(elements.phaseChip, "failed", "failed");
        }
    }

    function resizePrompt() {
        if (!(elements.promptInput instanceof HTMLTextAreaElement)) return;
        elements.promptInput.style.height = "auto";
        elements.promptInput.style.height = `${Math.min(240, Math.max(120, elements.promptInput.scrollHeight))}px`;
    }

    runtimeForm.addEventListener("submit", (event) => {
        event.preventDefault();
        if (selectedPlatform() === "chatgpt") return;
        mutate("/api/agent/runtime/start", formPayload(runtimeForm));
    });
    elements.runtimeStop?.addEventListener("click", () => mutate("/api/agent/runtime/stop"));
    promptForm.addEventListener("submit", (event) => {
        event.preventDefault();
        if (elements.ask?.disabled) return;
        schedulePreferenceSave();
        mutate("/api/agent/ask", formPayload(promptForm));
    });
    elements.stop?.addEventListener("click", () => mutate("/api/agent/stop"));

    elements.promptInput?.addEventListener("input", resizePrompt);
    elements.promptInput?.addEventListener("keydown", (event) => {
        if (event.key !== "Enter" || event.shiftKey || event.isComposing) return;
        event.preventDefault();
        if (!elements.ask?.disabled) promptForm.requestSubmit();
    });
    elements.projectPath?.addEventListener("change", () => {
        syncProjectPath(elements.projectPath.value);
        schedulePreferenceSave();
    });

    const cacheDockLink = document.querySelector('[data-dock-section="cache"]');
    cacheDockLink?.addEventListener("click", (event) => {
        const targetUrl = new URL("/cache/chatgpt", window.location.origin);
        targetUrl.searchParams.set("agent_platform", selectedPlatform());
        event.preventDefault();
        window.location.assign(`${targetUrl.pathname}${targetUrl.search}`);
    }, true);

    initializeComboboxes();
    syncProjectPath(elements.projectPath?.value || elements.workspacePath?.value || "");
    syncEngineUi(selectedPlatform());
    resizePrompt();

    async function pollStatus() {
        try {
            render(await requestJson("/api/agent/status"));
        } catch (_error) {
        } finally {
            const delay = lastPayload.agent?.running ? 800 : 2_500;
            window.setTimeout(pollStatus, delay);
        }
    }
    pollStatus();
})();
