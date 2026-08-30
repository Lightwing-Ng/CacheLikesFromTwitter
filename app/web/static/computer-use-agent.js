/* Code version: v3.24.1-codex.1 */

(() => {
    const BOOTSTRAPPED_SOURCE_PLATFORMS = new Set(["chatgpt", "grok", "claude"]);
    const runtimeForm = document.getElementById("agent_runtime_form");
    const promptForm = document.getElementById("agent_prompt_form");
    if (!runtimeForm || !promptForm) return;

    const elements = {
        agentPage: document.querySelector("[data-agent-route-prefix]"),
        phaseChip: document.getElementById("agent_phase_chip"),
        statusMessage: document.getElementById("agent_empty_response"),
        statusMessageCopy: document.querySelector("[data-agent-empty-response-copy]"),
        statusSpinner: document.querySelector("[data-agent-session-history-spinner]"),
        errorRecord: document.getElementById("agent_error_record"),
        errorRecordContent: document.querySelector("[data-agent-error-record-content]"),
        doctorPanel: document.getElementById("agent_doctor_panel"),
        doctorStatus: document.getElementById("agent_doctor_status"),
        doctorSummary: document.getElementById("agent_doctor_summary"),
        doctorChecks: document.getElementById("agent_doctor_checks"),
        doctorActions: document.getElementById("agent_doctor_actions"),
        responseOutput: document.getElementById("agent_response_output"),
        responseQuestion: document.querySelector("[data-agent-response-question]"),
        responseAnswer: document.querySelector("[data-agent-response-answer]"),
        responseAnswerContent: document.querySelector("[data-agent-response-answer-content]"),
        responsePagination: document.querySelector("[data-agent-response-pagination]"),
        conversationLink: document.getElementById("agent_conversation_link"),
        conversationLinkLabel: document.querySelector("[data-agent-conversation-link-label]"),
        ask: document.getElementById("agent_ask_button"),
        resume: document.getElementById("agent_resume_button"),
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
        promptOverflowToggle: promptForm.querySelector("[data-agent-composer-overflow-toggle]"),
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
    let sourcePlatform = "";
    let sourcesLoaded = false;
    let sourcesLoading = false;
    let sourceRequestId = 0;
    let catalogState = "idle";
    let catalogError = "";
    let catalogAbort = null;
    let appliedBootstrapSignature = "";
    const CATALOG_TIMEOUT_MS = 15000;
    let projectSessionRequestId = 0;
    let agentSources = {recent_sessions: [], projects: []};
    let projectSessions = [];
    let sessionTitleOverride = "";
    let boundAgentSessionSignature = "";
    let lastRenderedAgentRunning = null;
    let responseHistory = [];
    let responseHistoryPage = 1;
    let responseHistorySignature = "";
    let remoteSessionHistory = [];
    let remoteSessionHistoryUrl = "";
    let remoteSessionHistoryBrowser = "";
    let remoteSessionHistoryLoading = false;
    let remoteSessionHistoryError = "";
    let remoteSessionHistoryRequestId = 0;
    let doctorPayload = null;
    let doctorLoading = false;
    let doctorRequestId = 0;
    let agentPaginationRangeCloseTimer = 0;
    let agentPaginationRangeEventsBound = false;
    let agentPaginationRangePinnedPicker = null;
    let agentPaginationRangeFocusRestore = null;
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

    function normalizeAgentSelection() {
        if (selectedPlatform() === "chatgpt" || selectedBrowser() !== "safari") return;
        const browserCombobox = document.querySelector(".agent-browser-combobox");
        const edgeOption = browserCombobox?.querySelector('[data-agent-combobox-option="edge"]');
        const browserInput = browserCombobox?.querySelector("[data-agent-combobox-input]");
        if (!(browserInput instanceof HTMLInputElement) || !edgeOption) return;
        browserInput.value = "edge";
        syncComboboxTriggerFromOption(browserCombobox, edgeOption);
    }

    function selectedModel() {
        return selectedValue(".agent-model-combobox", "");
    }

    function selectedPlatformLabel() {
        return document.querySelector(".agent-platform-combobox [data-agent-combobox-selected-label]")?.textContent?.trim() || "Web AI";
    }

    function syncAgentRoute() {
        const routePrefix = String(elements.agentPage?.dataset.agentRoutePrefix || "/agent").replace(/\/$/, "");
        const nextPath = `${routePrefix}/${encodeURIComponent(selectedBrowser())}/${encodeURIComponent(selectedPlatform())}`;
        const currentPath = `${window.location.pathname}${window.location.search}${window.location.hash}`;
        if (currentPath === nextPath) return;
        window.history.replaceState({}, "", nextPath);
        window.dispatchEvent(new Event("popstate"));
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

    function agentSnapshotMatchesSelection(agent) {
        const platform = String(agent?.platform || "").trim().toLowerCase();
        const browser = String(agent?.browser || "").trim().toLowerCase();
        return Boolean(platform && browser)
            && platform === selectedPlatform()
            && browser === selectedBrowser();
    }

    function selectedSessionMode() {
        return elements.sessionMode?.value || "new";
    }

    function selectedConversationUrl() {
        if (selectedSessionMode() === "recent") return elements.recentSessionUrl?.value || "";
        if (selectedSessionMode() === "project") return elements.projectSessionUrl?.value === "new" ? "" : elements.projectSessionUrl?.value || "";
        return "";
    }

    function isChatgptConversationUrl(value) {
        return /^https:\/\/chatgpt\.com\/(?:g\/[^/]+\/)?c\/[^/]+\/?$/i.test(String(value || "").trim());
    }

    function isAgentConversationUrl(platform, value) {
        const candidate = String(value || "").trim();
        if (platform === "chatgpt") return isChatgptConversationUrl(candidate);
        if (platform === "gemini") return /^https:\/\/gemini\.google\.com\/app\/[A-Za-z0-9_-]+\/?$/i.test(candidate);
        if (platform === "grok") {
            return /^https:\/\/(?:www\.)?grok\.com\/(?:c\/[A-Za-z0-9_-]+\/?|project\/[A-Za-z0-9_-]+\/?\?chat=[A-Za-z0-9_-]+)$/i.test(candidate);
        }
        if (platform === "claude") {
            return /^https:\/\/claude\.ai\/(?:chat\/[A-Za-z0-9_-]+|project\/[A-Za-z0-9_-]+\/(?:chat|c)\/[A-Za-z0-9_-]+)\/?$/i.test(candidate);
        }
        return false;
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
        if (!selectedOption) {
            selectedOption = visibleOptions.reduce((strongest, option) => {
                if (!strongest) return option;
                const optionStrength = Number(option.dataset.agentModelStrength || 0);
                const strongestStrength = Number(strongest.dataset.agentModelStrength || 0);
                if (optionStrength !== strongestStrength) {
                    return optionStrength > strongestStrength ? option : strongest;
                }
                return String(option.dataset.agentComboboxOption || "")
                    > String(strongest.dataset.agentComboboxOption || "")
                    ? option
                    : strongest;
            }, null);
        }
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
        const sessionLabel = elements.sessionSource?.querySelector("[data-agent-session-platform-label]");
        if (sessionLabel) sessionLabel.textContent = "Session source";
        const sessionModeMenu = elements.sessionModeCombobox?.querySelector("[data-agent-combobox-menu]");
        Array.from(sessionModeMenu?.querySelectorAll("[data-agent-combobox-option]") || []).forEach((option) => {
        const supportedPlatforms = String(option.dataset.agentSessionPlatforms || "chatgpt,gemini,grok,claude")
                .split(",")
                .map((item) => item.trim())
                .filter(Boolean);
            option.hidden = !supportedPlatforms.includes(platform);
        });
        const recentMenu = elements.recentSessionCombobox?.querySelector("[data-agent-combobox-menu]");
        recentMenu?.setAttribute("aria-label", "Choose a recent session");
        const projectMenu = elements.projectCombobox?.querySelector("[data-agent-combobox-menu]");
        projectMenu?.setAttribute("aria-label", "Choose a recent project");
        const projectSessionMenu = elements.projectSessionCombobox?.querySelector("[data-agent-combobox-menu]");
        projectSessionMenu?.setAttribute("aria-label", "Choose a session in this project");
        const sessionSourceMenu = elements.sessionModeCombobox?.querySelector("[data-agent-combobox-menu]");
        sessionSourceMenu?.setAttribute("aria-label", "Choose a session source");
        if (elements.sessionSource) elements.sessionSource.hidden = false;
        browserStatusController?.setPlatform?.(platform);
    }

    function syncConversationLink(agent) {
        if (!elements.conversationLink) return;
        const recordedUrl = String(agent?.conversation_url || "").trim();
        const agentPlatform = String(agent?.platform || selectedPlatform()).trim().toLowerCase();
        const agentBrowser = String(agent?.browser || selectedBrowser()).trim().toLowerCase();
        const currentPlatform = selectedPlatform();
        const samePlatform = agentPlatform === currentPlatform;
        const targetUrl = samePlatform && (recordedUrl.startsWith("https://chatgpt.com/")
            || recordedUrl.startsWith("https://gemini.google.com/")
            || recordedUrl.startsWith("https://grok.com/")
            || recordedUrl.startsWith("https://claude.ai/")
            ) ? recordedUrl
            : selectedPlatformHomeUrl();
        const hasRecordedTarget = samePlatform && isAgentConversationUrl(agentPlatform, recordedUrl);
        const platformLabel = selectedPlatformLabel();
        const browserLabel = agentBrowser === selectedBrowser()
            ? selectedBrowserLabel()
            : ({safari: "Safari", edge: "Edge", chrome: "Chrome"}[agentBrowser] || "selected browser");
        const traditionalHandoff = Boolean(
            samePlatform
            && agent?.phase === "failed"
            && agent?.traditional_handoff_available,
        );
        const handoffLabel = agent?.traditional_handoff_opened
            ? `Continue in ${browserLabel}`
            : `Open in ${browserLabel}`;
        elements.conversationLink.href = targetUrl;
        elements.conversationLink.dataset.agentBrowser = agentBrowser;
        elements.conversationLink.classList.toggle("is-traditional-handoff", traditionalHandoff);
        if (elements.conversationLinkLabel) {
            elements.conversationLinkLabel.hidden = !traditionalHandoff;
            elements.conversationLinkLabel.textContent = handoffLabel;
        }
        elements.conversationLink.setAttribute(
            "aria-label",
            traditionalHandoff
                ? `${handoffLabel}: failed ${platformLabel} Agent task`
                : (hasRecordedTarget
                    ? `Open ${platformLabel} conversation in ${browserLabel}`
                    : `Open ${platformLabel} in ${browserLabel}`),
        );
        elements.conversationLink.title = elements.conversationLink.getAttribute("aria-label") || "";
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
        if (input instanceof HTMLInputElement) input.value = value || "";
        const menu = combobox.querySelector("[data-agent-combobox-menu]");
        Array.from(menu?.querySelectorAll("[data-agent-combobox-option]") || []).forEach((option) => {
            const isSelected = Boolean(value) && option.dataset.agentComboboxOption === value;
            option.classList.toggle("is-selected", isSelected);
            option.classList.toggle("is-active", isSelected);
            option.setAttribute("aria-selected", String(isSelected));
        });
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
        const mode = selectedSessionMode();
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
        const state = combobox.querySelector("[data-agent-session-list-state]");
        const stateCopy = combobox.querySelector("[data-agent-session-list-state-copy]");
        if (spinner) spinner.hidden = !loading;
        if (state) {
            state.hidden = !loading;
            state.setAttribute("aria-busy", String(loading));
        }
        if (stateCopy && loading) stateCopy.textContent = "Loading recent sessions…";
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
        const state = combobox.querySelector("[data-agent-session-list-state]");
        const stateCopy = combobox.querySelector("[data-agent-session-list-state-copy]");
        const isDirectList = combobox.dataset.agentDirectList === "true";
        if (!menu || (!trigger && !isDirectList)) return;
        const selectedValue = input instanceof HTMLInputElement ? input.value : "";
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
            if (isDirectList) option.tabIndex = 0;
            option.dataset.agentSourceId = item.id || "";
            option.dataset.agentSourceUpdatedAt = item.updated_at || "";
            if (selectedValue && itemValue === selectedValue) selectedOption = option;
            menu.append(option);
        });
        const readyLabel = combobox.dataset.agentSessionList === "projects"
            ? "Choose a recent project"
            : "Choose a recent session";
        const hasOptions = Boolean(menu.querySelector("[data-agent-combobox-option]"));
        if (hasOptions) {
            if (trigger) trigger.disabled = false;
            if (selectedOption) {
                if (input instanceof HTMLInputElement) input.value = selectedValue;
                syncComboboxTriggerFromOption(combobox, selectedOption);
                if (combobox === elements.recentSessionCombobox && selectedSessionMode() === "recent") {
                    sessionTitleOverride = selectedOption.dataset.agentComboboxLabel || "";
                }
            } else {
                if (selectedValue && combobox === elements.recentSessionCombobox) {
                    sessionTitleOverride = selectedSessionMode() === "recent" ? "" : sessionTitleOverride;
                }
                setComboboxValue(combobox, "", readyLabel, icon);
            }
        } else {
            if (trigger) trigger.disabled = true;
            setComboboxValue(combobox, "", emptyLabel, icon);
        }
        if (state) {
            state.hidden = true;
            state.setAttribute("aria-busy", "false");
            if (stateCopy) stateCopy.textContent = hasOptions ? "" : emptyLabel;
        }
        if (isDirectList) menu.hidden = false;
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
        if (selectedOption) {
            if (input instanceof HTMLInputElement) input.value = selectedValue;
            syncComboboxTriggerFromOption(elements.projectSessionCombobox, selectedOption);
            sessionTitleOverride = selectedValue === "new" || selectedSessionMode() !== "project"
                ? (selectedSessionMode() === "project" ? "" : sessionTitleOverride)
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
        const option = Array.from(menu.querySelectorAll("[data-agent-combobox-option]")).find(
            (candidate) => candidate.dataset.agentComboboxOption === value,
        );
        if (!option) return;
        input.value = value;
        if (label) {
            option.dataset.agentComboboxLabel = label;
            const text = option.querySelector(".trade-strategy-dropdown-text");
            if (text) text.textContent = label;
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
            if (menu && combobox.dataset.agentDirectList !== "true") menu.hidden = true;
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
            const isDirectList = combobox.dataset.agentDirectList === "true";
            if (!(input instanceof HTMLInputElement) || (!trigger && !isDirectList) || !menu) return;
            const closeComboboxForSelection = () => {
                if (!isDirectList) closeCombobox(combobox);
            };
            trigger?.addEventListener("click", () => {
                if (
                    catalogState === "error"
                    && (combobox === elements.recentSessionCombobox || combobox === elements.projectCombobox)
                ) {
                    loadAgentSources({forceRefresh: true});
                }
                toggleCombobox(combobox);
            });
            const selectOption = (option) => {
                const previousValue = input.value;
                input.value = option.dataset.agentComboboxOption || "";
                syncComboboxTriggerFromOption(combobox, option);
                closeComboboxForSelection();
                normalizeAgentSelection();
                syncExecutionChoices();
                const isRouteSelection = combobox.classList.contains("agent-platform-combobox")
                    || combobox.classList.contains("agent-browser-combobox");
                if (
                    isRouteSelection
                    && previousValue !== input.value
                    && elements.promptInput instanceof HTMLTextAreaElement
                ) {
                    elements.promptInput.value = "";
                    resizePrompt();
                }
                if (combobox.classList.contains("agent-platform-combobox")) {
                    sessionTitleOverride = "";
                    resetRemoteSessionHistory();
                    sourceBrowser = "";
                    sourcesLoaded = false;
                    sourceRequestId += 1;
                    appliedBootstrapSignature = "";
                    projectSessionRequestId += 1;
                    agentSources = {recent_sessions: [], projects: []};
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
                    appliedBootstrapSignature = "";
                    projectSessionRequestId += 1;
                    agentSources = {recent_sessions: [], projects: []};
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
                if (isRouteSelection) syncAgentRoute();
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
                        if (!sourcesLoaded) loadAgentSources();
                    } else if (input.value === "project") {
                        if (elements.recentSessionUrl instanceof HTMLInputElement) elements.recentSessionUrl.value = "";
                        if (elements.projectSessionUrl instanceof HTMLInputElement) elements.projectSessionUrl.value = "new";
                        setComboboxValue(elements.recentSessionCombobox, "", "Choose a recent session");
                        clearProjectSessionChoice();
                        if (!sourcesLoaded) loadAgentSources();
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
                schedulePreferenceSave();
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
            const query = new URLSearchParams({
                platform: selectedPlatform(),
                browser: selectedBrowser(),
                project_url: projectUrl,
            });
            const payload = await requestJson(`/api/agent/project-sessions?${query.toString()}`);
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

    function applyAgentSources(payload) {
        const sourcePayload = payload && typeof payload === "object"
            ? payload
            : {recent_sessions: [], projects: []};
        agentSources = sourcePayload;
        catalogState = "ready";
        catalogError = "";
        populateListCombobox(
            elements.recentSessionCombobox,
            sourcePayload.recent_sessions,
            "No recent sessions found",
        );
        populateListCombobox(
            elements.projectCombobox,
            sourcePayload.projects,
            "No recent projects found",
        );
        sourcesLoaded = true;
        clearCatalogLoadingState();
    }

    function applyAgentSourcesError(message) {
        agentSources = {recent_sessions: [], projects: []};
        catalogState = "error";
        catalogError = message || "Could not load Recent sessions";
        setComboboxValue(
            elements.recentSessionCombobox,
            "",
            catalogError,
        );
        setComboboxValue(
            elements.projectCombobox,
            "",
            "Recent projects are unavailable",
        );
        sourcesLoaded = true;
        clearCatalogLoadingState();
        if (elements.recentSessionCombobox?.dataset.agentDirectList === "true") {
            const state = elements.recentSessionCombobox.querySelector("[data-agent-session-list-state]");
            const stateCopy = elements.recentSessionCombobox.querySelector("[data-agent-session-list-state-copy]");
            const spinner = elements.recentSessionCombobox.querySelector("[data-agent-combobox-spinner]");
            if (state) state.hidden = false;
            if (stateCopy) stateCopy.textContent = catalogError;
            if (spinner) spinner.hidden = true;
        }
    }

    function setCatalogControlsLoading(loading) {
        [elements.recentSessionCombobox, elements.projectCombobox].forEach((combobox) => {
            if (!combobox) return;
            const trigger = combobox.querySelector("[data-agent-combobox-trigger]");
            if (trigger && loading) trigger.disabled = true;
            setComboboxLoading(combobox, loading);
        });
    }

    function clearCatalogLoadingState() {
        sourcesLoading = false;
        setCatalogControlsLoading(false);
        [elements.recentSessionCombobox, elements.projectCombobox].forEach((combobox) => {
            const trigger = combobox?.querySelector("[data-agent-combobox-trigger]");
            const hasOptions = Boolean(combobox?.querySelector("[data-agent-combobox-option]"));
            if (trigger && (catalogState === "error" || catalogState === "ready" || hasOptions)) {
                trigger.disabled = catalogState === "error" ? false : trigger.disabled && !hasOptions;
                if (catalogState === "error") trigger.disabled = false;
                if (catalogState === "ready" && hasOptions) trigger.disabled = false;
            }
        });
    }

    async function loadAgentSources(options = {}) {
        const forceRefresh = Boolean(options.forceRefresh);
        if (!lastBrowserStatus?.can_download || !selectedBrowser()) return;
        const browserName = selectedBrowser();
        const platform = selectedPlatform();
        const platformLabel = selectedPlatformLabel();
        const bootstrappedSources = lastBrowserStatus?.agent_sources;
        const bootstrappedError = lastBrowserStatus?.agent_sources_error;
        const supportsBootstrap = BOOTSTRAPPED_SOURCE_PLATFORMS.has(platform);
        if (!forceRefresh && supportsBootstrap && (bootstrappedSources || bootstrappedError)) {
            const bootstrapKind = bootstrappedSources ? "sources" : "error";
            const bootstrapValue = bootstrappedSources || String(bootstrappedError || "");
            const bootstrapSignature = `${browserName}|${platform}|${bootstrapKind}|${JSON.stringify(bootstrapValue)}`;
            if (bootstrapSignature !== appliedBootstrapSignature) {
                if (catalogAbort) {
                    catalogAbort.abort();
                    catalogAbort = null;
                }
                sourceRequestId += 1;
                sourceBrowser = browserName;
                sourcePlatform = platform;
                appliedBootstrapSignature = bootstrapSignature;
                if (bootstrappedSources) applyAgentSources(bootstrappedSources);
                else applyAgentSourcesError(String(bootstrappedError));
            }
            return;
        }
        if (
            !forceRefresh
            && sourcesLoading
            && sourceBrowser === browserName
            && sourcePlatform === platform
        ) return;
        if (
            !forceRefresh
            && sourcesLoaded
            && sourceBrowser === browserName
            && sourcePlatform === platform
        ) return;
        sourceBrowser = browserName;
        sourcePlatform = platform;
        if (catalogAbort) catalogAbort.abort();
        catalogAbort = new AbortController();
        const requestId = ++sourceRequestId;
        catalogState = "loading";
        catalogError = "";
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
        const timeoutId = window.setTimeout(() => catalogAbort.abort(), CATALOG_TIMEOUT_MS);
        try {
            const query = new URLSearchParams({platform, browser: browserName});
            if (forceRefresh) query.set("refresh", "1");
            const response = await fetch(`/api/agent/sources?${query.toString()}`, {
                cache: "no-store",
                signal: catalogAbort.signal,
                headers: {"Content-Type": "application/json", "Accept": "application/json"},
            });
            if (
                requestId !== sourceRequestId
                || browserName !== selectedBrowser()
                || platform !== selectedPlatform()
            ) {
                return;
            }
            let payload;
            try {
                payload = await response.json();
            } catch (_jsonError) {
                throw new Error("The server returned a malformed catalog response.");
            }
            if (!response.ok) {
                throw new Error(payload.error || `Could not load ${platformLabel} sessions`);
            }
            applyAgentSources(payload);
        } catch (error) {
            if (requestId !== sourceRequestId) {
                return;
            }
            if (error && error.name === "AbortError") {
                applyAgentSourcesError("Recent sessions timed out after 15 seconds.");
            } else {
                applyAgentSourcesError(error.message || `Could not load ${platformLabel} sessions`);
            }
        } finally {
            window.clearTimeout(timeoutId);
            if (requestId === sourceRequestId) clearCatalogLoadingState();
        }
    }

    function bindCompletedAgentSession(agent, completedTransition) {
        const platform = String(agent?.platform || selectedPlatform()).trim().toLowerCase();
        if (!completedTransition || platform !== selectedPlatform() || agent?.running) return;
        const conversationUrl = String(agent?.conversation_url || "").trim();
        if (!isAgentConversationUrl(platform, conversationUrl)) return;
        const signature = `${agent.started_at || ""}|${agent.finished_at || ""}|${conversationUrl}`;
        if (!agent.finished_at || signature === boundAgentSessionSignature) return;
        boundAgentSessionSignature = signature;
        loadAgentSources({forceRefresh: true});
    }

    function readinessState(payload) {
        const platformLabel = selectedPlatformLabel();
        const runtime = payload.runtime || {};
        const hostOperatingSystem = runtime.host_operating_system || "";
        if (hostOperatingSystem && selectedOs() !== hostOperatingSystem) {
            const hostLabel = hostOperatingSystem === "macos" ? "this macOS host" : "this Windows host";
            return {ready: false, message: `The selected operating system is not available on ${hostLabel}.`};
        }
        if (!runtime.ready) {
            return {
                ready: false,
                message: runtime.message || "Computer Use is not ready on this host.",
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

    function renderErrorRecord(agent) {
        if (!elements.errorRecord || !elements.errorRecordContent) return;
        const errorText = String(agent?.error_traceback || agent?.last_error || "");
        const changed = elements.errorRecordContent.textContent !== errorText;
        if (changed) {
            elements.errorRecordContent.textContent = errorText;
            if (errorText) elements.errorRecord.open = true;
        }
        elements.errorRecord.hidden = !errorText;
    }

    function renderDoctor(payload = doctorPayload) {
        if (!elements.doctorPanel) return;
        if (!payload) {
            elements.doctorPanel.hidden = true;
            return;
        }
        const status = String(payload.status || "attention");
        const statusLabel = status === "healthy"
            ? "Healthy"
            : status === "blocked"
                ? "Blocked"
                : "Needs attention";
        elements.doctorPanel.hidden = status === "healthy";
        elements.doctorPanel.dataset.status = status;
        if (elements.doctorStatus) elements.doctorStatus.textContent = statusLabel;
        if (elements.doctorSummary) {
            elements.doctorSummary.textContent = String(
                payload.summary || "Agent diagnostics are unavailable.",
            );
        }
        if (elements.doctorChecks) {
            const checks = Array.isArray(payload.checks) ? payload.checks : [];
            elements.doctorChecks.replaceChildren(...checks.map((check) => {
                const item = document.createElement("li");
                item.dataset.status = String(check.status || "info");
                const label = document.createElement("strong");
                label.textContent = String(check.label || "Diagnostic");
                const detail = document.createElement("span");
                detail.textContent = String(check.detail || "");
                item.append(label, detail);
                return item;
            }));
        }
        if (elements.doctorActions) {
            const actions = Array.isArray(payload.actions)
                ? payload.actions.filter((action) => action && action.enabled)
                : [];
            elements.doctorActions.replaceChildren(...actions.map((action) => {
                const button = document.createElement("button");
                button.type = "button";
                button.className = "secondary-button agent-doctor-action";
                button.dataset.agentDoctorAction = String(action.id || "");
                button.textContent = String(action.label || "Recover");
                button.title = String(action.description || "");
                return button;
            }));
        }
        if (status !== "healthy") elements.doctorPanel.open = true;
    }

    async function loadDoctor() {
        if (doctorLoading) return;
        doctorLoading = true;
        const requestId = ++doctorRequestId;
        try {
            const payload = await requestJson("/api/agent/doctor");
            if (requestId !== doctorRequestId) return;
            doctorPayload = payload;
            renderDoctor(payload);
        } catch (error) {
            if (requestId !== doctorRequestId) return;
            doctorPayload = {
                status: "attention",
                summary: error.message || "Agent diagnostics could not be loaded.",
                checks: [],
                actions: [],
            };
            renderDoctor(doctorPayload);
        } finally {
            doctorLoading = false;
        }
    }

    function agentNeedsDoctor(agent) {
        return ["failed", "interrupted"].includes(String(agent?.phase || ""))
            || Boolean(agent?.paused)
            || ["invalid", "degraded"].includes(String(agent?.event_chain_state || ""))
            || (Boolean(agent?.context_file) && !agent?.running);
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
            items.push({
                kind: "ellipsis",
                position: "leading",
                firstPage: 1,
                lastPage: startPage - 1,
            });
        }
        for (let page = startPage; page <= endPage; page += 1) {
            items.push({kind: "page", page, isActive: page === currentPage});
        }
        if (endPage < totalPages) {
            items.push({
                kind: "ellipsis",
                position: "trailing",
                firstPage: endPage + 1,
                lastPage: totalPages,
            });
            items.push({kind: "page", page: totalPages});
            items.push({kind: "next", page: endPage + 1});
        }
        return items;
    }

    function buildAgentPaginationRanges(firstPage, lastPage, chunkSize = 5) {
        if (firstPage > lastPage) return [];
        const ranges = [];
        for (let startPage = firstPage; startPage <= lastPage; startPage += chunkSize) {
            ranges.push([startPage, Math.min(startPage + chunkSize - 1, lastPage)]);
        }
        const lastRange = ranges[ranges.length - 1];
        if (
            ranges.length > 1
            && lastRange[1] - lastRange[0] + 1 < chunkSize
        ) {
            ranges[ranges.length - 2][1] = lastRange[1];
            ranges.pop();
        }
        return ranges;
    }

    function agentPaginationRangeElements(picker) {
        return {
            trigger: picker?.querySelector("[data-pagination-range-trigger]") || null,
            menu: picker?.querySelector("[data-pagination-range-menu]") || null,
        };
    }

    function agentPaginationRangePickers() {
        return elements.responsePagination
            ? Array.from(elements.responsePagination.querySelectorAll(".browser-pagination-range-picker"))
            : [];
    }

    function positionAgentPaginationRangeMenu(picker) {
        const {menu} = agentPaginationRangeElements(picker);
        if (!menu || !picker.classList.contains("is-open")) return;
        menu.classList.remove("is-below");
        menu.style.removeProperty("--pagination-range-menu-shift-x");
        menu.style.removeProperty("--pagination-range-menu-max-height");
        const pickerRect = picker.getBoundingClientRect();
        const viewportInset = 12;
        const menuGap = 8;
        const spaceAbove = Math.max(96, pickerRect.top - viewportInset - menuGap);
        const spaceBelow = Math.max(96, window.innerHeight - pickerRect.bottom - viewportInset - menuGap);
        const grid = menu.querySelector(".browser-pagination-range-grid");
        const style = window.getComputedStyle(menu);
        const paddingTop = Number.parseFloat(style.paddingTop) || 0;
        const paddingBottom = Number.parseFloat(style.paddingBottom) || 0;
        const naturalMenuHeight = (grid?.scrollHeight || 0) + paddingTop + paddingBottom;
        if (naturalMenuHeight > spaceAbove && spaceBelow > spaceAbove) menu.classList.add("is-below");
        const availableHeight = menu.classList.contains("is-below") ? spaceBelow : spaceAbove;
        menu.style.setProperty("--pagination-range-menu-max-height", `${availableHeight}px`);
        menu.classList.toggle("is-scrollable", naturalMenuHeight > menu.clientHeight + 1);
        const menuWidth = menu.offsetWidth;
        const idealMenuLeft = pickerRect.left + (pickerRect.width / 2) - (menuWidth / 2);
        let horizontalShift = 0;
        if (idealMenuLeft < viewportInset) {
            horizontalShift = viewportInset - idealMenuLeft;
        } else if (idealMenuLeft + menuWidth > window.innerWidth - viewportInset) {
            horizontalShift = window.innerWidth - viewportInset - idealMenuLeft - menuWidth;
        }
        menu.style.setProperty("--pagination-range-menu-shift-x", `${horizontalShift}px`);
    }

    function setAgentPaginationRangePickerOpen(picker, shouldOpen, {focusFirst = false} = {}) {
        if (!picker) return;
        const {trigger, menu} = agentPaginationRangeElements(picker);
        picker.classList.toggle("is-open", shouldOpen);
        trigger?.setAttribute("aria-expanded", shouldOpen ? "true" : "false");
        menu?.setAttribute("aria-hidden", shouldOpen ? "false" : "true");
        if (!shouldOpen) {
            menu?.classList.remove("is-below", "is-scrollable");
            menu?.style.removeProperty("--pagination-range-menu-shift-x");
            menu?.style.removeProperty("--pagination-range-menu-max-height");
            return;
        }
        agentPaginationRangePickers().forEach((otherPicker) => {
            if (otherPicker !== picker) setAgentPaginationRangePickerOpen(otherPicker, false);
        });
        window.requestAnimationFrame(() => {
            positionAgentPaginationRangeMenu(picker);
            if (focusFirst) menu?.querySelector(".browser-pagination-range-option")?.focus();
        });
    }

    function cancelAgentPaginationRangeClose() {
        if (!agentPaginationRangeCloseTimer) return;
        window.clearTimeout(agentPaginationRangeCloseTimer);
        agentPaginationRangeCloseTimer = 0;
    }

    function scheduleAgentPaginationRangeClose(picker) {
        cancelAgentPaginationRangeClose();
        if (agentPaginationRangePinnedPicker === picker) return;
        agentPaginationRangeCloseTimer = window.setTimeout(() => {
            agentPaginationRangeCloseTimer = 0;
            if (!picker.matches(":hover") && !picker.contains(document.activeElement)) {
                setAgentPaginationRangePickerOpen(picker, false);
            }
        }, 140);
    }

    function bindAgentPaginationRangeInteractions() {
        const pickers = agentPaginationRangePickers();
        pickers.forEach((picker) => {
            const {trigger, menu} = agentPaginationRangeElements(picker);
            picker.addEventListener("pointerenter", () => {
                cancelAgentPaginationRangeClose();
                setAgentPaginationRangePickerOpen(picker, true);
            });
            picker.addEventListener("pointerleave", () => scheduleAgentPaginationRangeClose(picker));
            picker.addEventListener("focusin", () => {
                cancelAgentPaginationRangeClose();
                if (agentPaginationRangeFocusRestore === picker) {
                    agentPaginationRangeFocusRestore = null;
                    return;
                }
                setAgentPaginationRangePickerOpen(picker, true);
            });
            picker.addEventListener("focusout", () => scheduleAgentPaginationRangeClose(picker));
            trigger?.addEventListener("click", () => {
                cancelAgentPaginationRangeClose();
                const shouldPin = agentPaginationRangePinnedPicker !== picker;
                if (agentPaginationRangePinnedPicker && agentPaginationRangePinnedPicker !== picker) {
                    setAgentPaginationRangePickerOpen(agentPaginationRangePinnedPicker, false);
                }
                agentPaginationRangePinnedPicker = shouldPin ? picker : null;
                setAgentPaginationRangePickerOpen(picker, shouldPin || picker.matches(":hover"));
            });
            trigger?.addEventListener("keydown", (event) => {
                if (event.key !== "ArrowDown") return;
                event.preventDefault();
                agentPaginationRangePinnedPicker = picker;
                setAgentPaginationRangePickerOpen(picker, true, {focusFirst: true});
            });
            menu?.addEventListener("keydown", (event) => {
                const options = Array.from(menu.querySelectorAll(".browser-pagination-range-option"));
                const currentIndex = options.indexOf(document.activeElement);
                let nextIndex = currentIndex;
                if (event.key === "ArrowDown" || event.key === "ArrowRight") nextIndex = Math.min(options.length - 1, currentIndex + 1);
                else if (event.key === "ArrowUp" || event.key === "ArrowLeft") nextIndex = Math.max(0, currentIndex - 1);
                else if (event.key === "Home") nextIndex = 0;
                else if (event.key === "End") nextIndex = options.length - 1;
                else return;
                event.preventDefault();
                options[nextIndex]?.focus();
            });
        });
        if (agentPaginationRangeEventsBound) return;
        agentPaginationRangeEventsBound = true;
        document.addEventListener("pointerdown", (event) => {
            const pagination = elements.responsePagination;
            if (pagination?.contains(event.target)) return;
            agentPaginationRangePinnedPicker = null;
            agentPaginationRangePickers().forEach((picker) => setAgentPaginationRangePickerOpen(picker, false));
        });
        document.addEventListener("keydown", (event) => {
            if (event.key !== "Escape") return;
            const openPicker = agentPaginationRangePickers().find((picker) => picker.classList.contains("is-open"));
            if (!openPicker) return;
            event.preventDefault();
            agentPaginationRangePinnedPicker = null;
            const trigger = agentPaginationRangeElements(openPicker).trigger;
            const shouldRestoreFocus = document.activeElement !== trigger;
            setAgentPaginationRangePickerOpen(openPicker, false);
            if (shouldRestoreFocus && trigger) {
                agentPaginationRangeFocusRestore = openPicker;
                trigger.focus();
            } else {
                agentPaginationRangeFocusRestore = null;
            }
        });
        window.addEventListener("resize", () => {
            agentPaginationRangePickers().forEach(positionAgentPaginationRangeMenu);
        }, {passive: true});
    }

    function createAgentPaginationRangePicker(item, pagination) {
        const picker = document.createElement("span");
        picker.className = "local-store-page-ellipsis browser-pagination-range-picker";
        picker.dataset.paginationEllipsis = item.position;

        const direction = item.position === "leading" ? "earlier" : "later";
        const trigger = document.createElement("button");
        trigger.type = "button";
        trigger.className = "browser-pagination-range-trigger";
        trigger.setAttribute("aria-label", `Show ${direction} conversation pages`);
        trigger.setAttribute("aria-haspopup", "menu");
        trigger.setAttribute("aria-expanded", "false");
        trigger.dataset.paginationRangeTrigger = "";
        const menuId = `agent_response_pagination_ranges_${item.position}`;
        trigger.setAttribute("aria-controls", menuId);
        const dots = document.createElement("span");
        dots.className = "local-store-page-ellipsis-dots";
        dots.setAttribute("aria-hidden", "true");
        trigger.append(dots);

        const menu = document.createElement("span");
        menu.id = menuId;
        menu.className = "browser-pagination-range-menu";
        menu.setAttribute("role", "menu");
        menu.setAttribute("aria-label", `${direction[0].toUpperCase()}${direction.slice(1)} conversation pages`);
        menu.setAttribute("aria-hidden", "true");
        menu.dataset.paginationRangeMenu = "";
        const grid = document.createElement("span");
        grid.className = "browser-pagination-range-grid";
        buildAgentPaginationRanges(item.firstPage, item.lastPage).forEach(([rangeStart, rangeEnd]) => {
            const option = document.createElement("button");
            option.type = "button";
            option.className = "browser-pagination-range-option";
            option.setAttribute("role", "menuitem");
            option.dataset.paginationRangeStart = String(rangeStart);
            option.dataset.paginationRangeEnd = String(rangeEnd);
            option.setAttribute("aria-label", `Conversation pages ${rangeStart} through ${rangeEnd}`);
            option.textContent = `${rangeStart}-${rangeEnd}`;
            option.addEventListener("click", () => {
                const targetPage = Number(option.dataset.paginationRangeStart);
                const nextAnimationState = paginationMotion?.capturePaginationAnimation(pagination, targetPage);
                agentPaginationRangePinnedPicker = null;
                setAgentPaginationRangePickerOpen(picker, false);
                responseHistoryPage = targetPage;
                renderAgentResponsePage({animationState: nextAnimationState});
            });
            grid.append(option);
        });
        menu.append(grid);
        picker.append(trigger, menu);
        return picker;
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
        agentPaginationRangePinnedPicker = null;
        agentPaginationRangeFocusRestore = null;
        cancelAgentPaginationRangeClose();
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
                return createAgentPaginationRangePicker(item, pagination);
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
        bindAgentPaginationRangeInteractions();
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
        const persistedAgent = lastPayload.agent || {};
        const readiness = readinessState(lastPayload);
        const running = Boolean(persistedAgent.running);
        const agent = running || agentSnapshotMatchesSelection(persistedAgent)
            ? persistedAgent
            : {};
        const paused = Boolean(agent.paused);
        const platformLabel = selectedPlatformLabel();
        const completedTransition = lastRenderedAgentRunning === true && !running;
        syncExecutionChoices();
        syncPlatformState();
        bindCompletedAgentSession(persistedAgent, completedTransition);
        lastRenderedAgentRunning = running;
        syncConversationLink(agent);

        const heading = document.querySelector("[data-agent-heading]");
        if (heading) heading.textContent = `${platformLabel} Web Agent`;
        if (elements.promptInput) {
            elements.promptInput.placeholder = "Do anything";
        }

        setChip(elements.phaseChip, agent.phase || "idle", agent.phase || "idle");
        const hasAgentResponse = renderAgentResponse(agent);
        renderErrorRecord(agent);
        if (agentNeedsDoctor(persistedAgent)) {
            if (!doctorPayload) loadDoctor();
            else renderDoctor();
        } else if (doctorPayload) {
            doctorPayload = null;
            doctorRequestId += 1;
            renderDoctor(null);
        }
        if (elements.statusMessage) {
            const sessionMessage = remoteSessionHistoryLoading
                ? "Loading the selected ChatGPT session history…"
                : remoteSessionHistoryError;
            const pauseCopy = paused
                ? (agent.pause_reason || agent.message || "The Web Agent is paused.")
                : "";
            const statusCopy = sessionMessage || pauseCopy || agent.message || readiness.message;
            if (elements.statusMessageCopy) elements.statusMessageCopy.textContent = statusCopy;
            else elements.statusMessage.textContent = statusCopy;
            if (elements.statusSpinner) elements.statusSpinner.hidden = !remoteSessionHistoryLoading;
            elements.statusMessage.hidden = hasAgentResponse && agent.phase !== "failed";
        }
        if (elements.readiness) elements.readiness.dataset.ready = String(readiness.ready);
        if (elements.readinessMessage) elements.readinessMessage.textContent = readiness.message;
        renderTerminalExecution(lastPayload.runtime);
        renderActivity(agent.activity, running);
        updateSessionChoiceInputs();
        if (readiness.ready && !running) loadAgentSources();

        if (elements.resume) {
            elements.resume.hidden = !paused;
            elements.resume.disabled = !paused;
        }
        if (elements.ask) {
            elements.ask.disabled = ((!readiness.ready || !sessionChoiceReady()) && !running);
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
            const response = await requestJson(url, {
                method: "POST",
                body: JSON.stringify(payload),
            });
            if (response.doctor) doctorPayload = response.doctor;
            render(response);
        } catch (error) {
            if (elements.statusMessage) {
                elements.statusMessage.hidden = false;
                elements.statusMessage.textContent = error.message;
            }
            if (elements.errorRecord && elements.errorRecordContent) {
                elements.errorRecordContent.textContent = error.message;
                elements.errorRecord.hidden = false;
                elements.errorRecord.open = true;
            }
            if (elements.responseOutput && !responseHistory.length) elements.responseOutput.hidden = true;
            setChip(elements.phaseChip, "failed", "failed");
        }
    }

    function promptCollapsedHeight() {
        if (!(elements.promptInput instanceof HTMLTextAreaElement)) return 0;
        const styles = window.getComputedStyle(elements.promptInput);
        const lineHeight = Number.parseFloat(styles.lineHeight) || 24;
        const paddingBlock = (Number.parseFloat(styles.paddingTop) || 0)
            + (Number.parseFloat(styles.paddingBottom) || 0);
        const borderBlock = (Number.parseFloat(styles.borderTopWidth) || 0)
            + (Number.parseFloat(styles.borderBottomWidth) || 0);
        return Math.ceil((lineHeight * 2) + paddingBlock + borderBlock);
    }

    function isPromptExpanded() {
        return elements.promptOverflowToggle?.getAttribute("aria-expanded") === "true";
    }

    function resizePrompt() {
        if (!(elements.promptInput instanceof HTMLTextAreaElement)) return;
        const collapsedHeight = promptCollapsedHeight();
        elements.promptInput.style.height = "auto";
        if (!isPromptExpanded()) {
            elements.promptInput.style.height = `${collapsedHeight}px`;
            return;
        }
        const expandedHeightLimit = Math.min(
            360,
            Math.max(collapsedHeight, Math.round(window.innerHeight * 0.45)),
        );
        const expandedHeight = Math.min(
            expandedHeightLimit,
            Math.max(collapsedHeight, elements.promptInput.scrollHeight),
        );
        elements.promptInput.style.height = `${expandedHeight}px`;
    }

    function setPromptExpanded(expanded) {
        if (!(elements.promptInput instanceof HTMLTextAreaElement)) return;
        elements.promptInput.classList.toggle("is-expanded", expanded);
        elements.promptOverflowToggle?.setAttribute("aria-expanded", String(expanded));
        const label = expanded ? "Collapse question or task" : "Expand question or task";
        elements.promptOverflowToggle?.setAttribute("aria-label", label);
        elements.promptOverflowToggle?.setAttribute("title", label);
        if (!expanded) elements.promptInput.scrollTop = 0;
        resizePrompt();
    }

    promptForm.addEventListener("submit", (event) => {
        event.preventDefault();
        if (elements.ask?.disabled || lastPayload.agent?.running || elements.ask?.classList.contains("is-stop")) return;
        updateSessionChoiceInputs();
        schedulePreferenceSave();
        mutate("/api/agent/ask", formPayload(promptForm));
    });
    elements.resume?.addEventListener("click", () => {
        mutate("/api/agent/resume");
    });
    elements.ask?.addEventListener("click", () => {
        if (elements.ask?.classList.contains("is-stop")) {
            mutate("/api/agent/stop");
            return;
        }
        if (!elements.ask.disabled) promptForm.requestSubmit();
    });
    elements.promptInput?.addEventListener("input", resizePrompt);
    elements.promptOverflowToggle?.addEventListener("click", () => {
        setPromptExpanded(!isPromptExpanded());
        elements.promptInput?.focus();
    });
    window.addEventListener(
        "resize",
        () => {
            resizePrompt();
            positionAgentPaginationIndicator({immediate: true});
        },
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
    elements.doctorPanel?.addEventListener("click", (event) => {
        const target = event.target instanceof Element ? event.target : null;
        const button = target?.closest("[data-agent-doctor-action]");
        if (!button) return;
        const action = button.dataset.agentDoctorAction;
        if (action === "new_task") {
            elements.doctorPanel.open = false;
            elements.promptInput?.focus();
            return;
        }
        if (action === "open_conversation") {
            elements.conversationLink?.click();
            return;
        }
        button.disabled = true;
        mutate("/api/agent/doctor/recover", {action}).finally(() => {
            button.disabled = false;
        });
    });

    initializeComboboxes();
    initializeBrowserSessionStatus();
    syncPlatformState();
    updateSessionChoiceInputs();
    syncProjectPath(elements.projectPath?.value || elements.workspacePath?.value || "");
    syncExecutionChoices();
    syncAgentRoute();
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
