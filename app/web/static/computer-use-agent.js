/* Code version: v3.9.2-codex.1 */

(() => {
    const runtimeForm = document.getElementById("agent_runtime_form");
    const promptForm = document.getElementById("agent_prompt_form");
    if (!runtimeForm || !promptForm) return;

    const elements = {
        phaseChip: document.getElementById("agent_phase_chip"),
        statusMessage: document.getElementById("agent_empty_response"),
        statusMessageCopy: document.querySelector("[data-agent-empty-response-copy]"),
        statusSpinner: document.querySelector("[data-agent-session-history-spinner]"),
        responseOutput: document.getElementById("agent_response_output"),
        responseQuestion: document.querySelector("[data-agent-response-question]"),
        responseAnswer: document.querySelector("[data-agent-response-answer]"),
        responseAnswerContent: document.querySelector("[data-agent-response-answer-content]"),
        responsePagination: document.querySelector("[data-agent-response-pagination]"),
        conversationLink: document.getElementById("agent_conversation_link"),
        ask: document.getElementById("agent_ask_button"),
        projectPath: document.querySelector("[data-agent-project-path]"),
        projectChoose: document.getElementById("agent_project_path_choose"),
        projectName: document.querySelector("[data-agent-project-name]"),
        readiness: document.querySelector(".agent-readiness"),
        readinessMessage: document.getElementById("agent_readiness_message"),
        workspacePath: promptForm.querySelector('input[name="workspace_path"]'),
        promptOs: promptForm.querySelector("[data-agent-prompt-os]"),
        promptPlatform: promptForm.querySelector("[data-agent-prompt-platform]"),
        promptBrowser: promptForm.querySelector("[data-agent-prompt-browser]"),
        modelInput: promptForm.querySelector("[data-agent-model-input]"),
        promptSessionMode: promptForm.querySelector("[data-agent-prompt-session-mode]"),
        promptConversationUrl: promptForm.querySelector("[data-agent-prompt-conversation-url]"),
        promptProjectUrl: promptForm.querySelector("[data-agent-prompt-project-url]"),
        promptSessionTitle: promptForm.querySelector("[data-agent-prompt-session-title]"),
        promptInput: promptForm.querySelector("[data-agent-prompt-input]"),
        activityPanel: document.getElementById("agent_activity_panel"),
        activityCount: document.getElementById("agent_activity_count"),
        activityList: document.getElementById("agent_activity_list"),
        browserSession: document.querySelector("[data-agent-browser-session]"),
        terminalExecutionStatus: document.querySelector("[data-agent-terminal-execution-status]"),
        terminalExecutionCopy: document.querySelector("[data-agent-terminal-execution-copy]"),
        terminalExecutionCheckmark: document.querySelector("[data-agent-terminal-execution-checkmark]"),
        platformCombobox: document.querySelector(".agent-platform-combobox"),
        sessionSource: document.querySelector("[data-agent-session-source]"),
        sessionMode: document.querySelector("[data-agent-session-mode]"),
        sessionModeCombobox: document.querySelector(".agent-session-mode-combobox"),
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
    let sessionTitleOverride = "";
    let boundAgentSessionSignature = "";
    let responseHistory = [];
    let responseHistoryPage = 1;
    let responseHistorySignature = "";
    let remoteSessionHistory = [];
    let remoteSessionHistoryUrl = "";
    let remoteSessionHistoryBrowser = "";
    let remoteSessionHistoryLoading = false;
    let remoteSessionHistoryError = "";
    let remoteSessionHistoryRequestId = 0;
    const paginationMotion = window.CACHELIKES_PAGINATION_MOTION;

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
        return selectedValue(".agent-os-combobox", elements.promptOs?.value || "macos");
    }

    function selectedBrowser() {
        return selectedValue(".agent-browser-combobox", "edge");
    }

    function selectedPlatform() {
        return selectedValue(".agent-platform-combobox", "chatgpt");
    }

    function selectedModel() {
        return selectedValue(".agent-model-combobox", "gpt-5.6-sol");
    }

    function selectedPlatformLabel() {
        return document.querySelector(".agent-platform-combobox [data-agent-combobox-selected-label]")?.textContent?.trim() || "Web AI";
    }

    function selectedPlatformHomeUrl() {
        const option = Array.from(
            document.querySelectorAll(".agent-platform-combobox [data-agent-combobox-option]"),
        ).find((candidate) => candidate.dataset.agentComboboxOption === selectedPlatform());
        return option?.dataset.agentPlatformHomeUrl || "https://chatgpt.com/";
    }

    function selectedBrowserLabel() {
        return document.querySelector(".agent-browser-combobox [data-agent-combobox-selected-label]")?.textContent?.trim() || "selected browser";
    }

    function selectedSessionMode() {
        return selectedPlatform() === "chatgpt" ? (elements.sessionMode?.value || "new") : "new";
    }

    function selectedConversationUrl() {
        if (selectedPlatform() !== "chatgpt") return "";
        if (selectedSessionMode() === "recent") return elements.recentSessionUrl?.value || "";
        if (selectedSessionMode() === "project") return elements.projectSessionUrl?.value === "new" ? "" : elements.projectSessionUrl?.value || "";
        return "";
    }

    function isChatgptConversationUrl(value) {
        return /^https:\/\/chatgpt\.com\/(?:g\/[^/]+\/)?c\/[^/]+\/?$/i.test(String(value || "").trim());
    }

    function historyUrlKey(value) {
        return String(value || "").trim().replace(/\/+$/, "").toLowerCase();
    }

    function resetRemoteSessionHistory() {
        remoteSessionHistoryRequestId += 1;
        remoteSessionHistory = [];
        remoteSessionHistoryUrl = "";
        remoteSessionHistoryBrowser = "";
        remoteSessionHistoryLoading = false;
        remoteSessionHistoryError = "";
        responseHistorySignature = "";
        responseHistoryPage = 1;
    }

    function remoteHistoryMatchesSelection() {
        const selectedUrl = selectedConversationUrl();
        return Boolean(selectedUrl)
            && historyUrlKey(remoteSessionHistoryUrl) === historyUrlKey(selectedUrl)
            && remoteSessionHistoryBrowser === selectedBrowser();
    }

    function selectedProjectUrl() {
        return elements.projectUrl?.value || "";
    }

    function selectedComboboxLabel(combobox) {
        const selectedValue = combobox?.querySelector("[data-agent-combobox-input]")?.value || "";
        const selectedOption = Array.from(
            combobox?.querySelectorAll("[data-agent-combobox-option]") || [],
        ).find((option) => option.dataset.agentComboboxOption === selectedValue);
        return selectedOption?.dataset.agentComboboxLabel
            || combobox?.querySelector("[data-agent-combobox-selected-label]")?.textContent?.trim()
            || "";
    }

    function selectedSessionTitle() {
        if (sessionTitleOverride) return sessionTitleOverride;
        const mode = selectedSessionMode();
        if (mode === "recent" && elements.recentSessionUrl?.value) {
            return selectedComboboxLabel(elements.recentSessionCombobox);
        }
        if (
            mode === "project"
            && elements.projectSessionUrl?.value
            && elements.projectSessionUrl.value !== "new"
        ) {
            return selectedComboboxLabel(elements.projectSessionCombobox);
        }
        return "";
    }

    function syncModelOptionsForPlatform() {
        const platform = selectedPlatform();
        const combobox = document.querySelector(".agent-model-combobox");
        const input = elements.modelInput;
        const menu = combobox?.querySelector("[data-agent-combobox-menu]");
        if (!combobox || !(input instanceof HTMLInputElement) || !menu) return;
        const options = Array.from(menu.querySelectorAll("[data-agent-combobox-option]"));
        const visibleOptions = options.filter((option) => option.dataset.agentPlatform === platform);
        options.forEach((option) => {
            option.hidden = option.dataset.agentPlatform !== platform;
        });
        let selectedOption = visibleOptions.find((option) => option.dataset.agentComboboxOption === input.value);
        if (!selectedOption) selectedOption = visibleOptions[0];
        if (!selectedOption) return;
        input.value = selectedOption.dataset.agentComboboxOption || "";
        const label = combobox.querySelector("[data-agent-combobox-selected-label]");
        if (label) label.textContent = selectedOption.dataset.agentComboboxLabel || "";
        const trigger = combobox.querySelector("[data-agent-combobox-trigger]");
        if (trigger) trigger.setAttribute("aria-label", `Model: ${selectedOption.dataset.agentComboboxLabel || ""}`);
        options.forEach((option) => {
            const isSelected = option === selectedOption;
            option.classList.toggle("is-selected", isSelected);
            option.classList.toggle("is-active", isSelected);
            option.setAttribute("aria-selected", String(isSelected));
        });
    }

    function syncPlatformState() {
        const platform = selectedPlatform();
        if (elements.promptPlatform instanceof HTMLInputElement) elements.promptPlatform.value = platform;
        if (elements.browserSession) {
            elements.browserSession.dataset.browserSessionPlatform = platform;
            elements.browserSession.dataset.browserSessionAccountLabel = selectedPlatformLabel();
        }
        syncModelOptionsForPlatform();
        const isChatgpt = platform === "chatgpt";
        if (elements.sessionSource) elements.sessionSource.hidden = !isChatgpt;
        if (!isChatgpt) {
            if (elements.sessionMode instanceof HTMLInputElement) elements.sessionMode.value = "new";
            if (elements.recentSessionField) elements.recentSessionField.hidden = true;
            if (elements.projectField) elements.projectField.hidden = true;
            if (elements.projectSessionField) elements.projectSessionField.hidden = true;
        }
        browserStatusController?.setPlatform?.(platform);
    }

    function syncConversationLink(agent) {
        if (!elements.conversationLink) return;
        const recordedUrl = String(agent?.conversation_url || "").trim();
        const platform = String(agent?.platform || selectedPlatform()).trim().toLowerCase();
        const targetUrl = recordedUrl.startsWith("https://chatgpt.com/")
            || recordedUrl.startsWith("https://gemini.google.com/")
            || recordedUrl.startsWith("https://grok.com/")
            ? recordedUrl
            : selectedPlatformHomeUrl();
        const hasRecordedTarget = Boolean(recordedUrl);
        const platformLabel = platform === selectedPlatform() ? selectedPlatformLabel() : platform;
        elements.conversationLink.href = targetUrl;
        elements.conversationLink.setAttribute(
            "aria-label",
            hasRecordedTarget ? `Open ${platformLabel} conversation` : `Open ${platformLabel}`,
        );
        elements.conversationLink.title = hasRecordedTarget
            ? `Open ${platformLabel} conversation`
            : `Open ${platformLabel}`;
    }

    function sessionChoiceReady() {
        if (selectedPlatform() !== "chatgpt") return true;
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
        if (input instanceof HTMLInputElement) input.value = value || "";
        syncComboboxTrigger(combobox, label, icon);
    }

    function syncComboboxTrigger(combobox, label, icon = "") {
        if (!combobox) return;
        const selectedLabel = combobox.querySelector("[data-agent-combobox-selected-label]");
        const selectedIcon = combobox.querySelector("[data-agent-combobox-selected-icon]");
        const trigger = combobox.querySelector("[data-agent-combobox-trigger]");
        if (selectedLabel) selectedLabel.textContent = label || "";
        if (selectedIcon instanceof HTMLImageElement && icon) selectedIcon.src = icon;
        if (trigger) {
            const fieldLabel = combobox.closest(".field")?.querySelector(".field-label")?.textContent?.trim() || "Option";
            trigger.setAttribute("aria-label", `${fieldLabel}: ${label || ""}`);
        }
    }

    function syncComboboxTriggerFromOption(combobox, option) {
        if (!combobox || !option) return;
        syncComboboxTrigger(
            combobox,
            option.dataset.agentComboboxLabel || "",
            option.dataset.agentComboboxIcon || "",
        );
        const menu = combobox.querySelector("[data-agent-combobox-menu]");
        Array.from(menu?.querySelectorAll("[data-agent-combobox-option]") || []).forEach((other) => {
            const isSelected = other === option;
            other.classList.toggle("is-selected", isSelected);
            other.classList.toggle("is-active", isSelected);
            other.setAttribute("aria-selected", String(isSelected));
        });
    }

    function syncSessionModeTrigger() {
        const combobox = elements.sessionModeCombobox;
        if (!combobox) return;
        const selectedValue = elements.sessionMode?.value || "new";
        const option = Array.from(combobox.querySelectorAll("[data-agent-combobox-option]")).find(
            (candidate) => candidate.dataset.agentComboboxOption === selectedValue,
        );
        if (!option) return;
        syncComboboxTriggerFromOption(combobox, option);
        if (sessionTitleOverride) {
            syncComboboxTrigger(
                combobox,
                sessionTitleOverride,
                option.dataset.agentComboboxIcon || "",
            );
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
        const isChatgpt = selectedPlatform() === "chatgpt";
        const mode = isChatgpt ? selectedSessionMode() : "new";
        const projectSessionValue = elements.projectSessionUrl?.value || "new";
        const executionMode = mode === "project"
            ? (projectSessionValue === "new" ? "project_new" : "project_session")
            : mode;
        if (elements.promptSessionMode instanceof HTMLInputElement) elements.promptSessionMode.value = executionMode;
        if (elements.promptConversationUrl instanceof HTMLInputElement) elements.promptConversationUrl.value = selectedConversationUrl();
        if (elements.promptProjectUrl instanceof HTMLInputElement) elements.promptProjectUrl.value = selectedProjectUrl();
        if (elements.promptSessionTitle instanceof HTMLInputElement) elements.promptSessionTitle.value = selectedSessionTitle();
        if (elements.recentSessionField) elements.recentSessionField.hidden = mode !== "recent";
        if (elements.projectField) elements.projectField.hidden = mode !== "project";
        if (elements.projectSessionField) elements.projectSessionField.hidden = mode !== "project";
        if (elements.projectSessionCombobox) {
            const projectSelected = Boolean(selectedProjectUrl());
            const trigger = elements.projectSessionCombobox.querySelector("[data-agent-combobox-trigger]");
            if (trigger) trigger.disabled = !projectSelected;
        }
        if (elements.sessionSource) {
            elements.sessionSource.hidden = !isChatgpt;
            elements.sessionSource.dataset.agentSessionMode = executionMode;
        }
        syncSessionModeTrigger();
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

    function setComboboxLoading(combobox, loading) {
        if (!combobox) return;
        const spinner = combobox.querySelector("[data-agent-combobox-spinner]");
        const trigger = combobox.querySelector("[data-agent-combobox-trigger]");
        if (spinner) spinner.hidden = !loading;
        if (!trigger) return;
        if (loading) {
            const fieldLabel = combobox.closest(".field")?.querySelector(".field-label")?.textContent?.trim() || "Option";
            trigger.setAttribute("aria-label", `${fieldLabel}: Loading`);
            trigger.setAttribute("aria-busy", "true");
        } else {
            trigger.removeAttribute("aria-busy");
        }
    }

    function populateListCombobox(combobox, items, emptyLabel, icon = "") {
        if (!combobox) return;
        const input = combobox.querySelector("[data-agent-combobox-input]");
        const menu = combobox.querySelector("[data-agent-combobox-menu]");
        const trigger = combobox.querySelector("[data-agent-combobox-trigger]");
        if (!menu || !trigger) return;
        const selectedValue = input instanceof HTMLInputElement ? input.value : "";
        const selectedLabel = selectedComboboxLabel(combobox);
        let selectedOption = null;
        menu.replaceChildren();
        const safeItems = Array.isArray(items) ? items : [];
        safeItems.forEach((item) => {
            const itemValue = item.url || "";
            const option = sourceOptionButton(
                itemValue,
                item.title || "Untitled",
                icon,
                Boolean(selectedValue && itemValue === selectedValue),
            );
            option.dataset.agentSourceId = item.id || "";
            option.dataset.agentSourceUpdatedAt = item.updated_at || "";
            if (selectedValue && itemValue === selectedValue) selectedOption = option;
            menu.append(option);
        });
        if (!selectedOption && selectedValue && selectedLabel) {
            selectedOption = sourceOptionButton(selectedValue, selectedLabel, icon, true);
            menu.prepend(selectedOption);
        }
        const readyLabel = combobox.dataset.agentSessionList === "projects"
            ? "Choose a recent project"
            : "Choose a recent session";
        if (menu.querySelector("[data-agent-combobox-option]")) {
            trigger.disabled = false;
            if (selectedOption) {
                if (input instanceof HTMLInputElement) input.value = selectedValue;
                syncComboboxTriggerFromOption(combobox, selectedOption);
                if (combobox === elements.recentSessionCombobox) {
                    sessionTitleOverride = selectedOption.dataset.agentComboboxLabel || "";
                }
            } else {
                setComboboxValue(combobox, "", readyLabel, icon);
            }
        } else {
            trigger.disabled = true;
            setComboboxValue(combobox, "", emptyLabel, icon);
        }
        setComboboxLoading(combobox, false);
        updateSessionChoiceInputs();
    }

    function clearProjectSessionChoice(label = "Choose a project first", allowNew = false, loading = false) {
        projectSessions = [];
        if (!elements.projectSessionCombobox) return;
        const menu = elements.projectSessionCombobox.querySelector("[data-agent-combobox-menu]");
        if (menu) {
            menu.replaceChildren();
            if (allowNew) menu.append(sourceOptionButton("new", "New session in project", "", true));
        }
        setComboboxValue(elements.projectSessionCombobox, "new", label);
        setComboboxLoading(elements.projectSessionCombobox, loading);
        const trigger = elements.projectSessionCombobox.querySelector("[data-agent-combobox-trigger]");
        if (trigger) trigger.disabled = !allowNew;
        updateSessionChoiceInputs();
    }

    function populateProjectSessionChoices(items) {
        if (!elements.projectSessionCombobox) return;
        const input = elements.projectSessionCombobox.querySelector("[data-agent-combobox-input]");
        const menu = elements.projectSessionCombobox.querySelector("[data-agent-combobox-menu]");
        const trigger = elements.projectSessionCombobox.querySelector("[data-agent-combobox-trigger]");
        if (!menu || !trigger) return;
        const selectedValue = input instanceof HTMLInputElement ? input.value : "new";
        const selectedLabel = selectedComboboxLabel(elements.projectSessionCombobox);
        let selectedOption = null;
        menu.replaceChildren();
        const newOption = sourceOptionButton(
            "new",
            "New session in project",
            "",
            selectedValue === "new",
        );
        if (selectedValue === "new") selectedOption = newOption;
        menu.append(newOption);
        projectSessions = Array.isArray(items) ? items : [];
        projectSessions.forEach((item) => {
            const itemValue = item.url || "";
            const option = sourceOptionButton(
                itemValue,
                item.title || "Untitled session",
                "",
                Boolean(selectedValue && itemValue === selectedValue),
            );
            option.dataset.agentSourceId = item.id || "";
            if (selectedValue && itemValue === selectedValue) selectedOption = option;
            menu.append(option);
        });
        if (!selectedOption && selectedValue && selectedValue !== "new" && selectedLabel) {
            selectedOption = sourceOptionButton(selectedValue, selectedLabel, "", true);
            menu.prepend(selectedOption);
        }
        if (selectedOption) {
            if (input instanceof HTMLInputElement) input.value = selectedValue;
            syncComboboxTriggerFromOption(elements.projectSessionCombobox, selectedOption);
            sessionTitleOverride = selectedValue === "new"
                ? ""
                : selectedOption.dataset.agentComboboxLabel || "";
        } else {
            setComboboxValue(elements.projectSessionCombobox, "new", "New session in project");
        }
        setComboboxLoading(elements.projectSessionCombobox, false);
        trigger.disabled = false;
        updateSessionChoiceInputs();
    }

    function selectSessionListValue(combobox, value, label) {
        if (!combobox || !value) return;
        const input = combobox.querySelector("[data-agent-combobox-input]");
        const menu = combobox.querySelector("[data-agent-combobox-menu]");
        const trigger = combobox.querySelector("[data-agent-combobox-trigger]");
        if (!(input instanceof HTMLInputElement) || !menu || !trigger) return;
        let option = Array.from(menu.querySelectorAll("[data-agent-combobox-option]")).find(
            (candidate) => candidate.dataset.agentComboboxOption === value,
        );
        if (!option) {
            option = sourceOptionButton(value, label || "Untitled session");
            menu.prepend(option);
        }
        input.value = value;
        if (label) {
            option.dataset.agentComboboxLabel = label;
            const text = option.querySelector(".trade-strategy-dropdown-text");
            text.textContent = label;
        }
        syncComboboxTriggerFromOption(combobox, option);
        setComboboxLoading(combobox, false);
        trigger.disabled = false;
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
        if (elements.promptPlatform instanceof HTMLInputElement) elements.promptPlatform.value = selectedPlatform();
        if (elements.promptBrowser instanceof HTMLInputElement) elements.promptBrowser.value = selectedBrowser();
        if (elements.modelInput instanceof HTMLInputElement) elements.modelInput.value = selectedModel();
    }

    function preferencePayload() {
        return {
            workspace_path: elements.workspacePath?.value || "",
            operating_system: selectedOs(),
            platform: selectedPlatform(),
            browser: selectedBrowser(),
            model: selectedModel(),
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
                syncComboboxTriggerFromOption(combobox, option);
                closeCombobox(combobox);
                syncExecutionChoices();
                schedulePreferenceSave();
                if (combobox.classList.contains("agent-platform-combobox")) {
                    sessionTitleOverride = "";
                    resetRemoteSessionHistory();
                    sourceBrowser = "";
                    sourcesLoaded = false;
                    sourceRequestId += 1;
                    projectSessionRequestId += 1;
                    chatgptSources = {recent_sessions: [], projects: []};
                    if (elements.recentSessionUrl instanceof HTMLInputElement) elements.recentSessionUrl.value = "";
                    if (elements.projectUrl instanceof HTMLInputElement) elements.projectUrl.value = "";
                    if (elements.projectSessionUrl instanceof HTMLInputElement) elements.projectSessionUrl.value = "new";
                    clearProjectSessionChoice();
                    setComboboxValue(elements.recentSessionCombobox, "", "Recent sessions");
                    setComboboxLoading(elements.recentSessionCombobox, true);
                    setComboboxValue(elements.projectCombobox, "", "Recent projects");
                    setComboboxLoading(elements.projectCombobox, true);
                    syncPlatformState();
                }
                if (combobox.classList.contains("agent-browser-combobox")) {
                    sessionTitleOverride = "";
                    resetRemoteSessionHistory();
                    sourceBrowser = "";
                    sourcesLoaded = false;
                    projectSessionRequestId += 1;
                    chatgptSources = {recent_sessions: [], projects: []};
                    if (elements.recentSessionUrl instanceof HTMLInputElement) elements.recentSessionUrl.value = "";
                    if (elements.projectUrl instanceof HTMLInputElement) elements.projectUrl.value = "";
                    if (elements.projectSessionUrl instanceof HTMLInputElement) elements.projectSessionUrl.value = "new";
                    clearProjectSessionChoice();
                    setComboboxValue(elements.recentSessionCombobox, "", "Recent sessions");
                    setComboboxLoading(elements.recentSessionCombobox, true);
                    setComboboxValue(elements.projectCombobox, "", "Recent projects");
                    setComboboxLoading(elements.projectCombobox, true);
                    browserStatusController?.setBrowser(selectedBrowser());
                }
                if (combobox.classList.contains("agent-session-mode-combobox")) {
                    sessionTitleOverride = "";
                    resetRemoteSessionHistory();
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
                    sessionTitleOverride = option.dataset.agentComboboxLabel || "";
                    if (elements.recentSessionUrl instanceof HTMLInputElement) elements.recentSessionUrl.value = input.value;
                    updateSessionChoiceInputs();
                    loadSelectedSessionHistory(input.value);
                }
                if (combobox === elements.projectCombobox) {
                    sessionTitleOverride = "";
                    resetRemoteSessionHistory();
                    if (elements.projectUrl instanceof HTMLInputElement) elements.projectUrl.value = input.value;
                    clearProjectSessionChoice("Project session", true, true);
                    loadProjectSessions(input.value);
                    updateSessionChoiceInputs();
                }
                if (combobox === elements.projectSessionCombobox) {
                    sessionTitleOverride = input.value === "new"
                        ? ""
                        : option.dataset.agentComboboxLabel || "";
                    if (elements.projectSessionUrl instanceof HTMLInputElement) elements.projectSessionUrl.value = input.value || "new";
                    updateSessionChoiceInputs();
                    if (input.value === "new") resetRemoteSessionHistory();
                    else loadSelectedSessionHistory(input.value);
                }
                render(lastPayload);
            };
            menu.addEventListener("click", (event) => {
                if (!(event.target instanceof Element)) return;
                const option = event.target.closest("[data-agent-combobox-option]");
                if (option && menu.contains(option)) {
                    selectOption(option);
                }
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
        } catch (_error) {
            if (requestId !== projectSessionRequestId) return;
            clearProjectSessionChoice("Project sessions unavailable", true);
        }
    }

    async function loadSelectedSessionHistory(conversationUrl) {
        const selectedUrl = String(conversationUrl || "").trim();
        if (selectedPlatform() !== "chatgpt" || !isChatgptConversationUrl(selectedUrl)) {
            resetRemoteSessionHistory();
            return;
        }
        const browserName = selectedBrowser();
        if (
            remoteHistoryMatchesSelection()
            && !remoteSessionHistoryLoading
            && !remoteSessionHistoryError
        ) {
            return;
        }

        const requestId = ++remoteSessionHistoryRequestId;
        remoteSessionHistory = [];
        remoteSessionHistoryUrl = selectedUrl;
        remoteSessionHistoryBrowser = browserName;
        remoteSessionHistoryLoading = true;
        remoteSessionHistoryError = "";
        responseHistorySignature = "";
        responseHistoryPage = 1;
        render(lastPayload);

        try {
            const query = new URLSearchParams({browser: browserName, conversation_url: selectedUrl});
            const payload = await requestJson(`/api/agent/chatgpt-session-history?${query.toString()}`);
            if (requestId !== remoteSessionHistoryRequestId || !remoteHistoryMatchesSelection()) return;
            remoteSessionHistory = Array.isArray(payload.history)
                ? payload.history.filter((item) => item && item.prompt && item.response)
                : [];
            remoteSessionHistoryLoading = false;
            remoteSessionHistoryError = "";
            if (payload.title && remoteHistoryMatchesSelection()) {
                sessionTitleOverride = String(payload.title).trim();
            }
            responseHistorySignature = "";
            responseHistoryPage = Math.max(remoteSessionHistory.length, 1);
            render(lastPayload);
        } catch (error) {
            if (requestId !== remoteSessionHistoryRequestId) return;
            remoteSessionHistoryLoading = false;
            remoteSessionHistoryError = error.message || "Could not load the selected ChatGPT session history.";
            responseHistorySignature = "";
            responseHistoryPage = 1;
            render(lastPayload);
        }
    }

    async function loadChatgptSources() {
        if (selectedPlatform() !== "chatgpt") return;
        if (!lastBrowserStatus?.can_download || !selectedBrowser()) return;
        if (sourcesLoading && sourceBrowser === selectedBrowser()) return;
        if (sourcesLoaded && sourceBrowser === selectedBrowser()) return;
        const browserName = selectedBrowser();
        const requestId = ++sourceRequestId;
        sourceBrowser = browserName;
        sourcesLoading = true;
        if (elements.recentSessionCombobox) {
            const trigger = elements.recentSessionCombobox.querySelector("[data-agent-combobox-trigger]");
            const input = elements.recentSessionCombobox.querySelector("[data-agent-combobox-input]");
            if (trigger) trigger.disabled = true;
            if (!(input instanceof HTMLInputElement) || !input.value) {
                setComboboxValue(elements.recentSessionCombobox, "", "Recent sessions");
            }
            setComboboxLoading(elements.recentSessionCombobox, true);
        }
        if (elements.projectCombobox) {
            const trigger = elements.projectCombobox.querySelector("[data-agent-combobox-trigger]");
            const input = elements.projectCombobox.querySelector("[data-agent-combobox-input]");
            if (trigger) trigger.disabled = true;
            if (!(input instanceof HTMLInputElement) || !input.value) {
                setComboboxValue(elements.projectCombobox, "", "Recent projects");
            }
            setComboboxLoading(elements.projectCombobox, true);
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
        } catch (_error) {
            if (requestId !== sourceRequestId) return;
            chatgptSources = {recent_sessions: [], projects: []};
            setComboboxValue(elements.recentSessionCombobox, "", "Could not load recent sessions");
            setComboboxValue(elements.projectCombobox, "", "Could not load recent projects");
            setComboboxLoading(elements.recentSessionCombobox, false);
            setComboboxLoading(elements.projectCombobox, false);
        } finally {
            if (requestId === sourceRequestId) sourcesLoading = false;
        }
    }

    function bindCompletedAgentSession(agent) {
        if (String(agent?.platform || "") !== "chatgpt" || agent?.running) return;
        const conversationUrl = String(agent?.conversation_url || "").trim();
        if (!/^https:\/\/chatgpt\.com\/(?:g\/[^/]+\/)?c\/[^/]+\/?$/i.test(conversationUrl)) return;
        const signature = `${agent.started_at || ""}|${agent.finished_at || ""}|${conversationUrl}`;
        if (!agent.finished_at || signature === boundAgentSessionSignature) return;
        boundAgentSessionSignature = signature;

        const sessionTitle = String(agent.session_title || agent.prompt || "Untitled session").trim();
        sessionTitleOverride = sessionTitle;
        sourceBrowser = "";
        sourcesLoaded = false;
        if (String(agent.session_mode || "").startsWith("project")) {
            if (elements.sessionMode instanceof HTMLInputElement) elements.sessionMode.value = "project";
            if (elements.projectUrl instanceof HTMLInputElement) {
                elements.projectUrl.value = String(agent.project_url || elements.projectUrl.value || "");
            }
            selectSessionListValue(elements.projectSessionCombobox, conversationUrl, sessionTitle);
            if (elements.projectUrl?.value) loadProjectSessions(elements.projectUrl.value);
        } else {
            if (elements.sessionMode instanceof HTMLInputElement) elements.sessionMode.value = "recent";
            selectSessionListValue(elements.recentSessionCombobox, conversationUrl, sessionTitle);
        }
        updateSessionChoiceInputs();
    }

    function readinessState(payload) {
        const platformLabel = selectedPlatformLabel();
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
                message: `Checking the signed-in ${platformLabel} account in ${selectedBrowserLabel()}...`,
            };
        }
        if (!lastBrowserStatus.can_download) {
            return {
                ready: false,
                message: lastBrowserStatus.message || `${selectedBrowserLabel()} is not signed in to ${platformLabel} Web.`,
            };
        }
        return {
            ready: true,
            message: lastBrowserStatus.message || `${selectedBrowserLabel()} is ready for ${platformLabel} Web.`,
        };
    }

    function initializeBrowserSessionStatus() {
        if (!elements.browserSession || !window.CACHELIKES_BROWSER_SESSION_STATUS?.init) return;
        browserStatusController = window.CACHELIKES_BROWSER_SESSION_STATUS.init(elements.browserSession, {
            platform: selectedPlatform(),
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

    function normalizePaginationPage(value, fallback = 1) {
        const numericValue = Number(value);
        if (!Number.isFinite(numericValue)) return fallback;
        return Math.max(1, Math.trunc(numericValue));
    }

    function buildAgentPaginationItems(totalPages, currentPage) {
        if (totalPages <= 1) return [];
        const chunkSize = 5;
        const startPage = Math.floor((currentPage - 1) / chunkSize) * chunkSize + 1;
        const endPage = Math.min(startPage + chunkSize - 1, totalPages);
        const items = [];
        if (startPage > 1) {
            items.push({kind: "previous", page: startPage - 1});
            items.push({kind: "page", page: 1});
            items.push({kind: "ellipsis"});
        }
        for (let page = startPage; page <= endPage; page += 1) {
            items.push({kind: "page", page, isActive: page === currentPage});
        }
        if (endPage < totalPages) {
            items.push({kind: "ellipsis"});
            items.push({kind: "page", page: totalPages});
            items.push({kind: "next", page: endPage + 1});
        }
        return items;
    }

    function positionAgentPaginationIndicator({immediate = false} = {}) {
        if (!elements.responsePagination || !paginationMotion) return;
        paginationMotion.positionPaginationIndicator(
            elements.responsePagination,
            elements.responsePagination.querySelector(".local-store-page-button.is-active"),
            {immediate},
        );
    }

    function renderAgentResponsePagination({animationState = null} = {}) {
        const pagination = elements.responsePagination;
        if (!pagination) return;
        const totalPages = responseHistory.length;
        responseHistoryPage = Math.min(
            Math.max(normalizePaginationPage(responseHistoryPage), 1),
            Math.max(totalPages, 1),
        );
        pagination.hidden = totalPages <= 1;
        if (totalPages <= 1) {
            paginationMotion?.clearPaginationAnimation(pagination);
            pagination.replaceChildren();
            pagination.style.removeProperty("--local-store-pagination-slots");
            pagination.classList.remove("is-animated");
            return;
        }

        const indicator = pagination.querySelector(".local-store-pagination-indicator")
            || document.createElement("span");
        indicator.className = "local-store-pagination-indicator";
        indicator.setAttribute("aria-hidden", "true");
        const items = buildAgentPaginationItems(totalPages, responseHistoryPage);
        const controls = items.map((item) => {
            if (item.kind === "ellipsis") {
                const ellipsis = document.createElement("span");
                ellipsis.className = "local-store-page-ellipsis";
                ellipsis.setAttribute("aria-hidden", "true");
                const dots = document.createElement("span");
                dots.className = "local-store-page-ellipsis-dots";
                ellipsis.append(dots);
                return ellipsis;
            }

            const button = document.createElement("button");
            button.type = "button";
            button.className = `local-store-page-button${item.isActive ? " is-active" : ""}${item.kind === "page" ? "" : " local-store-page-nav"}`;
            button.dataset.paginationTarget = String(item.page);
            button.dataset.paginationCurrent = item.isActive ? "1" : "0";
            if (item.isActive) button.setAttribute("aria-current", "page");
            if (item.kind === "page") {
                button.textContent = String(item.page);
                button.setAttribute("aria-label", `Conversation page ${item.page}`);
            } else {
                const isPrevious = item.kind === "previous";
                button.setAttribute(
                    "aria-label",
                    isPrevious ? "Previous conversation page group" : "Next conversation page group",
                );
                const icon = document.createElement("span");
                icon.className = `icon ${isPrevious ? "icon-page-prev" : "icon-page-next"}`;
                icon.setAttribute("aria-hidden", "true");
                button.append(icon);
            }
            button.addEventListener("click", () => {
                if (item.isActive) return;
                const nextAnimationState = paginationMotion?.capturePaginationAnimation(
                    pagination,
                    item.page,
                );
                responseHistoryPage = item.page;
                renderAgentResponsePage({animationState: nextAnimationState});
            });
            return button;
        });
        pagination.style.setProperty("--local-store-pagination-slots", String(items.length));
        pagination.replaceChildren(indicator, ...controls);
        window.requestAnimationFrame(() => {
            if (animationState && paginationMotion) {
                paginationMotion.animatePaginationIndicator(pagination, animationState);
                return;
            }
            positionAgentPaginationIndicator({immediate: true});
        });
    }

    function renderAgentResponsePage({animationState = null} = {}) {
        const entry = responseHistory[responseHistoryPage - 1] || null;
        if (elements.responseQuestion) elements.responseQuestion.textContent = entry?.prompt || "";
        if (elements.responseAnswerContent) {
            elements.responseAnswerContent.innerHTML = entry?.response_html || "";
        } else if (elements.responseAnswer) {
            elements.responseAnswer.innerHTML = entry?.response_html || "";
        }
        if (elements.responseAnswer) elements.responseAnswer.scrollTop = 0;
        if (elements.responseOutput) elements.responseOutput.hidden = !entry;
        renderAgentResponsePagination({animationState});
    }

    function renderAgentResponse(agent) {
        const localHistory = Array.isArray(agent?.history)
            ? agent.history.filter((item) => item && item.prompt && item.response)
            : [];
        if (!localHistory.length && agent?.response) {
            localHistory.push({
                prompt: agent.prompt || "",
                response: agent.response,
                response_html: agent.response_html || "",
                started_at: agent.started_at || "",
                finished_at: agent.finished_at || "",
            });
        }
        const selectedUrl = selectedConversationUrl();
        let history = localHistory;
        if (selectedUrl) {
            const localSessionMatches = historyUrlKey(agent?.conversation_url) === historyUrlKey(selectedUrl);
            if (remoteHistoryMatchesSelection()) {
                history = [...remoteSessionHistory];
                if (localSessionMatches) history = mergeAgentHistory(history, localHistory);
            } else {
                history = [];
            }
        }
        const signature = JSON.stringify(
            history.map((item) => [
                item.started_at || "",
                item.finished_at || "",
                item.prompt || "",
                item.response || "",
            ]),
        );
        if (signature !== responseHistorySignature) {
            responseHistorySignature = signature;
            responseHistory = history;
            responseHistoryPage = Math.max(history.length, 1);
        }
        renderAgentResponsePage();
        return responseHistory.length > 0;
    }

    function mergeAgentHistory(primary, secondary) {
        const merged = Array.isArray(primary) ? [...primary] : [];
        const seen = new Set(merged.map((item) => `${item.prompt || ""}\u0000${item.response || ""}`));
        (Array.isArray(secondary) ? secondary : []).forEach((item) => {
            const key = `${item.prompt || ""}\u0000${item.response || ""}`;
            if (!seen.has(key) && item.prompt && item.response) {
                seen.add(key);
                merged.push(item);
            }
        });
        return merged;
    }

    function renderTerminalExecution(runtime) {
        if (!elements.terminalExecutionStatus || !elements.terminalExecutionCopy) return;
        const terminalExecution = runtime?.terminal_execution || {};
        const ready = Boolean(terminalExecution.ready);
        const statusLabel = terminalExecution.status_label || (ready ? "Granted" : "Not granted");
        elements.terminalExecutionStatus.dataset.ready = String(ready);
        elements.terminalExecutionStatus.title = terminalExecution.message || "";
        elements.terminalExecutionStatus.setAttribute("aria-label", `Terminal permission: ${statusLabel}`);
        elements.terminalExecutionCopy.textContent = statusLabel;
        if (elements.terminalExecutionCheckmark) elements.terminalExecutionCheckmark.hidden = !ready;
    }

    function render(payload) {
        lastPayload = payload || {};
        const agent = lastPayload.agent || {};
        const readiness = readinessState(lastPayload);
        const running = Boolean(agent.running);
        const platformLabel = selectedPlatformLabel();
        syncExecutionChoices();
        syncPlatformState();
        bindCompletedAgentSession(agent);
        syncConversationLink(agent);

        const heading = document.querySelector("[data-agent-heading]");
        if (heading) heading.textContent = `${platformLabel} Web Agent`;
        if (elements.promptInput) {
            elements.promptInput.placeholder = "Do anything";
        }

        setChip(elements.phaseChip, agent.phase || "idle", agent.phase || "idle");
        const hasAgentResponse = renderAgentResponse(agent);
        if (elements.statusMessage) {
            const sessionMessage = remoteSessionHistoryLoading
                ? "Loading the selected ChatGPT session history…"
                : remoteSessionHistoryError;
            const statusCopy = sessionMessage || agent.message || readiness.message;
            if (elements.statusMessageCopy) elements.statusMessageCopy.textContent = statusCopy;
            else elements.statusMessage.textContent = statusCopy;
            if (elements.statusSpinner) elements.statusSpinner.hidden = !remoteSessionHistoryLoading;
            elements.statusMessage.hidden = hasAgentResponse;
        }
        if (elements.readiness) elements.readiness.dataset.ready = String(readiness.ready);
        if (elements.readinessMessage) elements.readinessMessage.textContent = readiness.message;
        renderTerminalExecution(lastPayload.runtime);
        renderActivity(agent.activity, running);
        updateSessionChoiceInputs();
        if (readiness.ready && !running) loadChatgptSources();

        if (elements.ask) {
            elements.ask.disabled = (!readiness.ready || !sessionChoiceReady()) && !running;
            elements.ask.classList.toggle("is-stop", running);
            elements.ask.dataset.agentAction = running ? "stop" : "ask";
            const label = running ? "Stop Agent task" : `Ask ${platformLabel} Web`;
            elements.ask.setAttribute("aria-label", label);
            elements.ask.setAttribute("title", label);
        }
        if (elements.projectChoose) elements.projectChoose.disabled = running;
        elements.comboboxTriggers.forEach((trigger) => {
            if (running) {
                const sessionSourceChoice = trigger.closest(".agent-session-mode-combobox");
                trigger.disabled = !sessionSourceChoice;
                return;
            }
            const isRuntimeChoice = trigger.closest(
                ".agent-platform-combobox, .agent-browser-combobox, .agent-model-combobox, .agent-session-mode-combobox"
            );
            if (isRuntimeChoice) trigger.disabled = false;
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
            if (elements.responseOutput && !responseHistory.length) elements.responseOutput.hidden = true;
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
        updateSessionChoiceInputs();
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
    window.addEventListener(
        "resize",
        () => positionAgentPaginationIndicator({immediate: true}),
        {passive: true},
    );
    elements.promptInput?.addEventListener("keydown", (event) => {
        if (event.key !== "Enter" || event.shiftKey || event.isComposing) return;
        event.preventDefault();
        if (!elements.ask?.disabled && !elements.ask?.classList.contains("is-stop")) promptForm.requestSubmit();
    });
    elements.projectPath?.addEventListener("change", () => {
        syncProjectPath(elements.projectPath.value);
        schedulePreferenceSave();
    });
    elements.conversationLink?.addEventListener("click", (event) => {
        event.preventDefault();
        requestJson("/api/agent/open-conversation", {
            method: "POST",
        }).catch((error) => {
            if (elements.statusMessage) {
                elements.statusMessage.hidden = false;
                elements.statusMessage.textContent = error.message;
            }
            setChip(elements.phaseChip, "failed", "failed");
        });
    });

    initializeComboboxes();
    initializeBrowserSessionStatus();
    syncPlatformState();
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
