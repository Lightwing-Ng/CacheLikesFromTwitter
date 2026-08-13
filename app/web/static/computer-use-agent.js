/* Code version: v3.1.0-codex.4 */

(() => {
    const runtimeForm = document.getElementById("agent_runtime_form");
    const promptForm = document.getElementById("agent_prompt_form");
    if (!runtimeForm || !promptForm) return;

    const elements = {
        phaseChip: document.getElementById("agent_phase_chip"),
        statusMessage: document.getElementById("agent_empty_response"),
        responseOutput: document.getElementById("agent_response_output"),
        conversationLink: document.getElementById("agent_conversation_link"),
        ask: document.getElementById("agent_ask_button"),
        projectPath: document.querySelector("[data-agent-project-path]"),
        projectChoose: document.getElementById("agent_project_path_choose"),
        projectName: document.querySelector("[data-agent-project-name]"),
        readiness: document.querySelector(".agent-readiness"),
        readinessMessage: document.getElementById("agent_readiness_message"),
        workspacePath: promptForm.querySelector('input[name="workspace_path"]'),
        promptOs: promptForm.querySelector("[data-agent-prompt-os]"),
        promptBrowser: promptForm.querySelector("[data-agent-prompt-browser]"),
        promptSessionMode: promptForm.querySelector("[data-agent-prompt-session-mode]"),
        promptConversationUrl: promptForm.querySelector("[data-agent-prompt-conversation-url]"),
        promptProjectUrl: promptForm.querySelector("[data-agent-prompt-project-url]"),
        promptInput: promptForm.querySelector("[data-agent-prompt-input]"),
        activityPanel: document.getElementById("agent_activity_panel"),
        activityCount: document.getElementById("agent_activity_count"),
        activityList: document.getElementById("agent_activity_list"),
        browserSession: document.querySelector("[data-agent-browser-session]"),
        sessionSource: document.querySelector("[data-agent-session-source]"),
        sessionMode: document.querySelector("[data-agent-session-mode]"),
        osCombobox: document.querySelector(".agent-os-combobox"),
        sessionModeCombobox: document.querySelector(".agent-session-mode-combobox"),
        sessionHelp: document.querySelector("[data-agent-session-help]"),
        recentSessionField: document.querySelector("[data-agent-recent-session-field]"),
        recentSessionCombobox: document.querySelector('[data-agent-session-list="recent"]'),
        recentSessionUrl: document.querySelector("[data-agent-recent-session-url]"),
        projectField: document.querySelector("[data-agent-project-field]"),
        projectCombobox: document.querySelector('[data-agent-session-list="projects"]'),
        projectUrl: document.querySelector("[data-agent-project-url]"),
        projectSessionField: document.querySelector("[data-agent-project-session-field]"),
        projectSessionCombobox: document.querySelector('[data-agent-session-list="project-sessions"]'),
        projectSessionUrl: document.querySelector("[data-agent-project-session-url]"),
        comboboxTriggers: Array.from(document.querySelectorAll("[data-agent-combobox-trigger]")),
    };

    let lastPayload = {};
    let lastBrowserStatus = null;
    let browserStatusController = null;
    let preferenceTimer = null;
    let activitySignature = "";
    let sourceBrowser = "";
    let sourcesLoaded = false;
    let sourcesLoading = false;
    let sourceRequestId = 0;
    let projectSessionRequestId = 0;
    let chatgptSources = {recent_sessions: [], projects: []};
    let projectSessions = [];

    async function requestJson(url, options = {}) {
        const response = await fetch(url, {
            ...options,
            headers: {"Content-Type": "application/json", ...(options.headers || {})},
        });
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.error || `Request failed with ${response.status}.`);
        return payload;
    }

    function formPayload(form) {
        return Object.fromEntries(new FormData(form).entries());
    }

    function setChip(element, label, state) {
        if (!element) return;
        element.textContent = label;
        element.className = `status-chip status-${state}`;
    }

    function selectedValue(selector, fallback) {
        return document.querySelector(`${selector} [data-agent-combobox-input]`)?.value || fallback;
    }

    function selectedOs() {
        return selectedValue(".agent-os-combobox", "macos");
    }

    function selectedBrowser() {
        return selectedValue(".agent-browser-combobox", "safari");
    }

    function selectedBrowserLabel() {
        return document.querySelector(".agent-browser-combobox [data-agent-combobox-selected-label]")?.textContent?.trim() || "selected browser";
    }

    function detectedHostOperatingSystem() {
        const serverValue = elements.osCombobox?.dataset.agentHostOperatingSystem?.trim().toLowerCase();
        if (serverValue === "macos" || serverValue === "windows") return serverValue;
        const platform = String(
            window.navigator?.userAgentData?.platform || window.navigator?.platform || ""
        ).toLowerCase();
        if (platform.includes("mac")) return "macos";
        if (platform.includes("win")) return "windows";
        return "";
    }

    function autoSelectHostOperatingSystem() {
        const target = detectedHostOperatingSystem();
        const input = elements.osCombobox?.querySelector("[data-agent-combobox-input]");
        if (!target || !(input instanceof HTMLInputElement) || input.value === target) return;
        const option = Array.from(
            elements.osCombobox.querySelectorAll("[data-agent-combobox-option]")
        ).find((candidate) => candidate.dataset.agentComboboxOption === target);
        if (option instanceof HTMLButtonElement) option.click();
    }

    function selectedSessionMode() {
        return elements.sessionMode?.value || "new";
    }

    function selectedConversationUrl() {
        if (selectedSessionMode() === "recent") return elements.recentSessionUrl?.value || "";
        if (selectedSessionMode() === "project") return elements.projectSessionUrl?.value === "new" ? "" : elements.projectSessionUrl?.value || "";
        return "";
    }

    function selectedProjectUrl() {
        return elements.projectUrl?.value || "";
    }

    function sessionChoiceReady() {
        const mode = selectedSessionMode();
        if (mode === "new") return true;
        if (mode === "recent") return Boolean(elements.recentSessionUrl?.value);
        if (mode === "project") {
            const projectSession = elements.projectSessionUrl?.value || "new";
            return Boolean(selectedProjectUrl()) && (projectSession === "new" || Boolean(projectSession));
        }
        return false;
    }

    function setComboboxValue(combobox, value, label, icon = "") {
        if (!combobox) return;
        const input = combobox.querySelector("[data-agent-combobox-input]");
        const selectedLabel = combobox.querySelector("[data-agent-combobox-selected-label]");
        const selectedIcon = combobox.querySelector("[data-agent-combobox-selected-icon]");
        const trigger = combobox.querySelector("[data-agent-combobox-trigger]");
        if (input instanceof HTMLInputElement) input.value = value || "";
        if (selectedLabel) selectedLabel.textContent = label || "";
        if (selectedIcon instanceof HTMLImageElement && icon) selectedIcon.src = icon;
        if (trigger) {
            const fieldLabel = combobox.closest(".field")?.querySelector(".field-label")?.textContent?.trim() || "Option";
            trigger.setAttribute("aria-label", `${fieldLabel}: ${label || ""}`);
        }
    }

    function closeAllComboboxes() {
        document.querySelectorAll("[data-agent-combobox]").forEach((combobox) => {
            combobox.classList.remove("is-agent-combobox-open");
            combobox.querySelector("[data-agent-combobox-trigger]")?.setAttribute("aria-expanded", "false");
            const menu = combobox.querySelector("[data-agent-combobox-menu]");
            if (menu) menu.hidden = true;
        });
    }

    function updateSessionChoiceInputs() {
        const mode = selectedSessionMode();
        const projectSessionValue = elements.projectSessionUrl?.value || "new";
        const executionMode = mode === "project"
            ? (projectSessionValue === "new" ? "project_new" : "project_session")
            : mode;
        if (elements.promptSessionMode instanceof HTMLInputElement) elements.promptSessionMode.value = executionMode;
        if (elements.promptConversationUrl instanceof HTMLInputElement) elements.promptConversationUrl.value = selectedConversationUrl();
        if (elements.promptProjectUrl instanceof HTMLInputElement) elements.promptProjectUrl.value = selectedProjectUrl();
        if (elements.recentSessionField) elements.recentSessionField.hidden = mode !== "recent";
        if (elements.projectField) elements.projectField.hidden = mode !== "project";
        if (elements.projectSessionField) elements.projectSessionField.hidden = mode !== "project";
        if (elements.sessionHelp) {
            const help = {
                new: "Starts a new root-level ChatGPT session for this task.",
                recent: "Joins one of the 20 most recent root-level sessions.",
                project: "Choose a recent project, then start or join one of its sessions.",
            };
            elements.sessionHelp.textContent = help[mode] || help.new;
        }
        if (elements.projectSessionCombobox) {
            const projectSelected = Boolean(selectedProjectUrl());
            const trigger = elements.projectSessionCombobox.querySelector("[data-agent-combobox-trigger]");
            if (trigger) trigger.disabled = !projectSelected;
        }
        if (elements.sessionSource) {
            elements.sessionSource.dataset.agentSessionMode = executionMode;
        }
    }

    function sourceOptionButton(value, label, icon = "", selected = false) {
        const option = document.createElement("button");
        option.type = "button";
        option.className = `trade-strategy-dropdown-option agent-combobox-option${selected ? " is-selected is-active" : ""}`;
        option.dataset.agentComboboxOption = value || "";
        option.dataset.agentComboboxLabel = label || "";
        if (icon) option.dataset.agentComboboxIcon = icon;
        option.setAttribute("role", "option");
        option.setAttribute("aria-selected", String(selected));
        option.tabIndex = -1;
        const check = document.createElement("span");
        check.className = "trade-strategy-dropdown-check";
        check.setAttribute("aria-hidden", "true");
        const text = document.createElement("span");
        text.className = "trade-strategy-dropdown-text";
        text.textContent = label || "Untitled";
        if (icon) {
            const iconElement = document.createElement("img");
            iconElement.className = "browser-picker-option-icon";
            iconElement.src = icon;
            iconElement.alt = "";
            iconElement.setAttribute("aria-hidden", "true");
            option.append(check, iconElement, text);
        } else {
            option.append(check, text);
            option.style.gridTemplateColumns = "16px minmax(0, 1fr)";
        }
        return option;
    }

    function populateListCombobox(combobox, items, emptyLabel, icon = "") {
        if (!combobox) return;
        const menu = combobox.querySelector("[data-agent-combobox-menu]");
        const trigger = combobox.querySelector("[data-agent-combobox-trigger]");
        if (!menu || !trigger) return;
        menu.replaceChildren();
        const safeItems = Array.isArray(items) ? items : [];
        safeItems.forEach((item) => {
            const option = sourceOptionButton(item.url || "", item.title || "Untitled", icon);
            option.dataset.agentSourceId = item.id || "";
            option.dataset.agentSourceUpdatedAt = item.updated_at || "";
            menu.append(option);
        });
        const readyLabel = combobox.dataset.agentSessionList === "projects"
            ? "Choose a recent project"
            : "Choose a recent session";
        if (safeItems.length) {
            trigger.disabled = false;
            setComboboxValue(combobox, "", readyLabel, icon);
        } else {
            trigger.disabled = true;
            setComboboxValue(combobox, "", emptyLabel, icon);
        }
        updateSessionChoiceInputs();
    }

    function clearProjectSessionChoice(label = "Choose a project first", allowNew = false) {
        projectSessions = [];
        if (!elements.projectSessionCombobox) return;
        const menu = elements.projectSessionCombobox.querySelector("[data-agent-combobox-menu]");
        if (menu) {
            menu.replaceChildren();
            if (allowNew) menu.append(sourceOptionButton("new", "New session in project", "", true));
        }
        setComboboxValue(elements.projectSessionCombobox, "new", label);
        const trigger = elements.projectSessionCombobox.querySelector("[data-agent-combobox-trigger]");
        if (trigger) trigger.disabled = !allowNew;
        updateSessionChoiceInputs();
    }

    function populateProjectSessionChoices(items) {
        if (!elements.projectSessionCombobox) return;
        const menu = elements.projectSessionCombobox.querySelector("[data-agent-combobox-menu]");
        const trigger = elements.projectSessionCombobox.querySelector("[data-agent-combobox-trigger]");
        if (!menu || !trigger) return;
        menu.replaceChildren();
        const newOption = sourceOptionButton("new", "New session in project", "", true);
        menu.append(newOption);
        projectSessions = Array.isArray(items) ? items : [];
        projectSessions.forEach((item) => {
            const option = sourceOptionButton(item.url || "", item.title || "Untitled session");
            option.dataset.agentSourceId = item.id || "";
            menu.append(option);
        });
        setComboboxValue(elements.projectSessionCombobox, "new", "New session in project");
        trigger.disabled = false;
        updateSessionChoiceInputs();
    }

    function projectNameFromPath(path) {
        const normalizedPath = String(path || "").replace(/[\\/]+$/, "");
        return normalizedPath.split(/[\\/]/).pop() || normalizedPath;
    }

    function syncProjectPath(path) {
        const normalizedPath = String(path || "").trim();
        if (!normalizedPath) return;
        if (elements.workspacePath instanceof HTMLInputElement) elements.workspacePath.value = normalizedPath;
        if (elements.projectName) elements.projectName.textContent = projectNameFromPath(normalizedPath);
    }

    function syncExecutionChoices() {
        if (elements.promptOs instanceof HTMLInputElement) elements.promptOs.value = selectedOs();
        if (elements.promptBrowser instanceof HTMLInputElement) elements.promptBrowser.value = selectedBrowser();
    }

    function preferencePayload() {
        return {
            workspace_path: elements.workspacePath?.value || "",
            operating_system: selectedOs(),
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
                if (elements.statusMessage) {
                    elements.statusMessage.hidden = false;
                    elements.statusMessage.textContent = error.message;
                }
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
            trigger.addEventListener("click", () => toggleCombobox(combobox));
            const selectOption = (option) => {
                input.value = option.dataset.agentComboboxOption || "";
                const label = combobox.querySelector("[data-agent-combobox-selected-label]");
                const icon = combobox.querySelector("[data-agent-combobox-selected-icon]");
                if (label) label.textContent = option.dataset.agentComboboxLabel || "";
                if (icon instanceof HTMLImageElement && option.dataset.agentComboboxIcon) {
                    icon.src = option.dataset.agentComboboxIcon;
                }
                const fieldLabel = combobox.closest(".field")?.querySelector(".field-label")?.textContent?.trim() || "Option";
                trigger.setAttribute("aria-label", `${fieldLabel}: ${option.dataset.agentComboboxLabel || ""}`);
                Array.from(menu.querySelectorAll("[data-agent-combobox-option]")).forEach((other) => {
                    const isSelected = other === option;
                    other.classList.toggle("is-selected", isSelected);
                    other.classList.toggle("is-active", isSelected);
                    other.setAttribute("aria-selected", String(isSelected));
                });
                closeCombobox(combobox);
                syncExecutionChoices();
                schedulePreferenceSave();
                if (combobox.classList.contains("agent-browser-combobox")) {
                    sourceBrowser = "";
                    sourcesLoaded = false;
                    projectSessionRequestId += 1;
                    chatgptSources = {recent_sessions: [], projects: []};
                    if (elements.recentSessionUrl instanceof HTMLInputElement) elements.recentSessionUrl.value = "";
                    if (elements.projectUrl instanceof HTMLInputElement) elements.projectUrl.value = "";
                    if (elements.projectSessionUrl instanceof HTMLInputElement) elements.projectSessionUrl.value = "new";
                    clearProjectSessionChoice();
                    browserStatusController?.setBrowser(selectedBrowser());
                }
                if (combobox.classList.contains("agent-session-mode-combobox")) {
                    if (input.value === "new") {
                        if (elements.recentSessionUrl instanceof HTMLInputElement) elements.recentSessionUrl.value = "";
                        if (elements.projectUrl instanceof HTMLInputElement) elements.projectUrl.value = "";
                        if (elements.projectSessionUrl instanceof HTMLInputElement) elements.projectSessionUrl.value = "new";
                        setComboboxValue(elements.recentSessionCombobox, "", "Choose a recent session");
                        setComboboxValue(elements.projectCombobox, "", "Choose a recent project");
                        clearProjectSessionChoice();
                    } else if (input.value === "recent") {
                        if (elements.projectUrl instanceof HTMLInputElement) elements.projectUrl.value = "";
                        if (elements.projectSessionUrl instanceof HTMLInputElement) elements.projectSessionUrl.value = "new";
                        setComboboxValue(elements.projectCombobox, "", "Choose a recent project");
                        clearProjectSessionChoice();
                        if (!sourcesLoaded) loadChatgptSources();
                    } else if (input.value === "project") {
                        if (elements.recentSessionUrl instanceof HTMLInputElement) elements.recentSessionUrl.value = "";
                        if (elements.projectSessionUrl instanceof HTMLInputElement) elements.projectSessionUrl.value = "new";
                        setComboboxValue(elements.recentSessionCombobox, "", "Choose a recent session");
                        clearProjectSessionChoice();
                        if (!sourcesLoaded) loadChatgptSources();
                    }
                    updateSessionChoiceInputs();
                }
                if (combobox === elements.recentSessionCombobox) {
                    if (elements.recentSessionUrl instanceof HTMLInputElement) elements.recentSessionUrl.value = input.value;
                    updateSessionChoiceInputs();
                }
                if (combobox === elements.projectCombobox) {
                    if (elements.projectUrl instanceof HTMLInputElement) elements.projectUrl.value = input.value;
                    clearProjectSessionChoice("Loading project sessions…", true);
                    loadProjectSessions(input.value);
                    updateSessionChoiceInputs();
                }
                if (combobox === elements.projectSessionCombobox) {
                    if (elements.projectSessionUrl instanceof HTMLInputElement) elements.projectSessionUrl.value = input.value || "new";
                    updateSessionChoiceInputs();
                }
                render(lastPayload);
            };
            menu.addEventListener("click", (event) => {
                if (!(event.target instanceof Element)) return;
                const option = event.target.closest("[data-agent-combobox-option]");
                if (option && menu.contains(option)) selectOption(option);
            });
        });

        document.addEventListener("click", (event) => {
            if (!(event.target instanceof Element) || event.target.closest("[data-agent-combobox]")) return;
            comboboxes.forEach(closeCombobox);
        });
        document.addEventListener("keydown", (event) => {
            if (event.key === "Escape") comboboxes.forEach(closeCombobox);
        });
    }

    async function loadProjectSessions(projectUrl) {
        if (!projectUrl) return;
        const requestId = ++projectSessionRequestId;
        try {
            const query = new URLSearchParams({browser: selectedBrowser(), project_url: projectUrl});
            const payload = await requestJson(`/api/agent/chatgpt-project-sessions?${query.toString()}`);
            if (requestId !== projectSessionRequestId || projectUrl !== selectedProjectUrl()) return;
            populateProjectSessionChoices(payload.sessions || []);
        } catch (error) {
            if (requestId !== projectSessionRequestId) return;
            clearProjectSessionChoice("Project sessions unavailable", true);
            if (elements.sessionHelp) elements.sessionHelp.textContent = error.message;
        }
    }

    async function loadChatgptSources() {
        if (!lastBrowserStatus?.can_download || !selectedBrowser()) return;
        if (sourcesLoading && sourceBrowser === selectedBrowser()) return;
        if (sourcesLoaded && sourceBrowser === selectedBrowser()) return;
        const browserName = selectedBrowser();
        const requestId = ++sourceRequestId;
        sourceBrowser = browserName;
        sourcesLoading = true;
        if (elements.recentSessionCombobox) {
            const trigger = elements.recentSessionCombobox.querySelector("[data-agent-combobox-trigger]");
            if (trigger) trigger.disabled = true;
            setComboboxValue(elements.recentSessionCombobox, "", "Loading recent sessions…");
        }
        if (elements.projectCombobox) {
            const trigger = elements.projectCombobox.querySelector("[data-agent-combobox-trigger]");
            if (trigger) trigger.disabled = true;
            setComboboxValue(elements.projectCombobox, "", "Loading recent projects…");
        }
        try {
            const query = new URLSearchParams({browser: browserName});
            const payload = await requestJson(`/api/agent/chatgpt-sources?${query.toString()}`);
            if (requestId !== sourceRequestId || browserName !== selectedBrowser()) return;
            chatgptSources = payload;
            populateListCombobox(
                elements.recentSessionCombobox,
                payload.recent_sessions,
                "No recent sessions found",
            );
            populateListCombobox(
                elements.projectCombobox,
                payload.projects,
                "No recent projects found",
            );
            sourcesLoaded = true;
        } catch (error) {
            if (requestId !== sourceRequestId) return;
            chatgptSources = {recent_sessions: [], projects: []};
            setComboboxValue(elements.recentSessionCombobox, "", "Could not load recent sessions");
            setComboboxValue(elements.projectCombobox, "", "Could not load recent projects");
            if (elements.sessionHelp) elements.sessionHelp.textContent = error.message;
        } finally {
            if (requestId === sourceRequestId) sourcesLoading = false;
        }
    }

    function readinessState(payload) {
        const runtime = payload.runtime || {};
        if (selectedOs() !== "macos") {
            const hostOperatingSystem = runtime.host_operating_system || "this host";
            const hostLabel = hostOperatingSystem === "macos" ? "this macOS host" : "this host";
            return {ready: false, message: `Windows execution is planned but is not available on ${hostLabel}.`};
        }
        if (!runtime.ready) {
            return {
                ready: false,
                message: runtime.message || "Computer Use is not ready on this Mac.",
            };
        }
        if (!lastBrowserStatus) {
            return {
                ready: false,
                message: `Checking the signed-in ChatGPT account in ${selectedBrowserLabel()}...`,
            };
        }
        if (!lastBrowserStatus.can_download) {
            return {
                ready: false,
                message: lastBrowserStatus.message || `${selectedBrowserLabel()} is not signed in to ChatGPT Web.`,
            };
        }
        return {
            ready: true,
            message: lastBrowserStatus.message || `${selectedBrowserLabel()} is ready for ChatGPT Web.`,
        };
    }

    function initializeBrowserSessionStatus() {
        if (!elements.browserSession || !window.CACHELIKES_BROWSER_SESSION_STATUS?.init) return;
        browserStatusController = window.CACHELIKES_BROWSER_SESSION_STATUS.init(elements.browserSession, {
            platform: "chatgpt",
            getBrowser: selectedBrowser,
            onStateChange(payload, browserId, state) {
                lastBrowserStatus = state === "cleared"
                    ? null
                    : {...(payload || {}), browser: browserId};
                render(lastPayload);
            },
        });
    }

    function renderActivity(events, running) {
        if (!elements.activityPanel || !elements.activityList || !elements.activityCount) return;
        const safeEvents = Array.isArray(events) ? events : [];
        const signature = JSON.stringify(safeEvents);
        const changed = signature !== activitySignature;
        if (changed) {
            activitySignature = signature;
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
            if (changed) elements.activityList.scrollTop = elements.activityList.scrollHeight;
        }
    }

    function render(payload) {
        lastPayload = payload || {};
        const agent = lastPayload.agent || {};
        const readiness = readinessState(lastPayload);
        const running = Boolean(agent.running);
        syncExecutionChoices();

        setChip(elements.phaseChip, agent.phase || "idle", agent.phase || "idle");
        if (elements.statusMessage) {
            elements.statusMessage.textContent = agent.message || readiness.message;
            elements.statusMessage.hidden = Boolean(agent.response);
        }
        if (elements.responseOutput) {
            elements.responseOutput.innerHTML = agent.response_html || "";
            elements.responseOutput.hidden = !agent.response;
        }
        if (elements.conversationLink) {
            elements.conversationLink.hidden = !agent.conversation_url;
            if (agent.conversation_url) elements.conversationLink.href = agent.conversation_url;
        }
        if (elements.readiness) elements.readiness.dataset.ready = String(readiness.ready);
        if (elements.readinessMessage) elements.readinessMessage.textContent = readiness.message;
        renderActivity(agent.activity, running);
        updateSessionChoiceInputs();
        if (readiness.ready && !running) loadChatgptSources();

        if (elements.ask) {
            elements.ask.disabled = (!readiness.ready || !sessionChoiceReady()) && !running;
            elements.ask.classList.toggle("is-stop", running);
            elements.ask.dataset.agentAction = running ? "stop" : "ask";
            const label = running ? "Stop Agent task" : "Ask ChatGPT Web";
            elements.ask.setAttribute("aria-label", label);
            elements.ask.setAttribute("title", label);
        }
        if (elements.projectChoose) elements.projectChoose.disabled = running;
        elements.comboboxTriggers.forEach((trigger) => {
            if (running) {
                trigger.disabled = true;
                return;
            }
            const isRuntimeChoice = trigger.closest(
                ".agent-os-combobox, .agent-browser-combobox, .agent-session-mode-combobox"
            );
            if (isRuntimeChoice) trigger.disabled = false;
        });
        if (elements.sessionModeCombobox) {
            const trigger = elements.sessionModeCombobox.querySelector("[data-agent-combobox-trigger]");
            if (trigger) trigger.disabled = running;
        }
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

    promptForm.addEventListener("submit", (event) => {
        event.preventDefault();
        if (elements.ask?.disabled || lastPayload.agent?.running || elements.ask?.classList.contains("is-stop")) return;
        schedulePreferenceSave();
        mutate("/api/agent/ask", formPayload(promptForm));
    });
    elements.ask?.addEventListener("click", () => {
        if (elements.ask?.classList.contains("is-stop")) {
            mutate("/api/agent/stop");
            return;
        }
        if (!elements.ask.disabled) promptForm.requestSubmit();
    });
    elements.promptInput?.addEventListener("input", resizePrompt);
    elements.promptInput?.addEventListener("keydown", (event) => {
        if (event.key !== "Enter" || event.shiftKey || event.isComposing) return;
        event.preventDefault();
        if (!elements.ask?.disabled && !elements.ask?.classList.contains("is-stop")) promptForm.requestSubmit();
    });
    elements.projectPath?.addEventListener("change", () => {
        syncProjectPath(elements.projectPath.value);
        schedulePreferenceSave();
    });

    initializeComboboxes();
    autoSelectHostOperatingSystem();
    initializeBrowserSessionStatus();
    updateSessionChoiceInputs();
    syncProjectPath(elements.projectPath?.value || elements.workspacePath?.value || "");
    syncExecutionChoices();
    resizePrompt();

    async function pollStatus() {
        try {
            render(await requestJson("/api/agent/status"));
        } catch (_error) {
        } finally {
            window.setTimeout(pollStatus, lastPayload.agent?.running ? 800 : 2_500);
        }
    }
    pollStatus();
})();
