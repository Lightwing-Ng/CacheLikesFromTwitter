/* Code version: v1.0.0-codex.1 */

(() => {
    const operatingSystem = document.querySelector("[data-agent-settings-operating-system]");
    const authorizationButton = document.querySelector("[data-agent-terminal-authorization-button]");
    const authorizationStatus = document.querySelector("[data-agent-terminal-authorization-status]");
    if (!(operatingSystem instanceof HTMLSelectElement) || !(authorizationButton instanceof HTMLButtonElement)) return;

    function detectedHostOperatingSystem() {
        const serverValue = operatingSystem.dataset.agentHostOperatingSystem?.trim().toLowerCase();
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
        if (!target || operatingSystem.value === target) return;
        if (!Array.from(operatingSystem.options).some((option) => option.value === target)) return;
        operatingSystem.value = target;
        operatingSystem.dispatchEvent(new Event("change", {bubbles: true}));
    }

    authorizationButton.addEventListener("click", async () => {
        authorizationButton.disabled = true;
        if (authorizationStatus) {
            authorizationStatus.hidden = false;
            authorizationStatus.textContent = operatingSystem.value === "windows"
                ? "Opening PowerShell permissions…"
                : "Opening Terminal permissions…";
        }
        try {
            const response = await fetch("/api/agent/terminal-authorization", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({operating_system: operatingSystem.value}),
                credentials: "same-origin",
            });
            const payload = await response.json();
            if (!response.ok) throw new Error(payload.error || `Request failed with ${response.status}.`);
            if (authorizationStatus) authorizationStatus.textContent = payload.message || "Permissions opened.";
        } catch (error) {
            if (authorizationStatus) authorizationStatus.textContent = error.message;
        } finally {
            authorizationButton.disabled = false;
        }
    });

    autoSelectHostOperatingSystem();
})();
