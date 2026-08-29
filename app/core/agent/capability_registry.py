"""One registry for Agent actions, page observations, and WebMCP tools.

Code version: v1.0.0-codex.1
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


CAPABILITY_REGISTRY_VERSION = "1.0.0"
AGENT_OPTIMIZATION_CONTRACT_VERSION = "1.0.0"
AGENT_OPTIMIZATION_PROFILE = "openai-site-tools-2026-08-28"


@dataclass(frozen=True, slots=True)
class CapabilityDefinition:
    """Describe one bounded capability at its authoritative application boundary."""

    key: str
    kind: str
    label: str
    description: str
    read_only: bool
    public: bool = False
    manifest_id: str = ""
    action_name: str = ""
    webmcp_name: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-safe internal registry record."""
        return asdict(self)

    def as_manifest_record(self) -> dict[str, str]:
        """Return the small public record accepted by the shared WebMCP runtime."""
        return {
            "id": self.manifest_id or self.key.replace(".", "_")[:64],
            "label": self.label,
            "description": self.description,
        }


@dataclass(frozen=True, slots=True)
class NavigationTarget:
    """Describe one same-origin human-page destination in the Site manifest."""

    id: str
    label: str
    description: str
    path: str

    def as_dict(self) -> dict[str, str]:
        """Return a JSON-safe navigation record."""
        return asdict(self)


def _action(
    name: str,
    label: str,
    description: str,
    *,
    read_only: bool,
    input_schema: dict[str, Any] | None = None,
) -> CapabilityDefinition:
    return CapabilityDefinition(
        key=f"agent.action.{name}",
        kind="agent_action",
        label=label,
        description=description,
        read_only=read_only,
        action_name=name,
        input_schema=input_schema or {},
    )


def _observation(key: str, label: str, description: str) -> CapabilityDefinition:
    return CapabilityDefinition(
        key=f"page.observe.{key}",
        kind="page_observation",
        label=label,
        description=description,
        read_only=True,
    )


def _webmcp(
    name: str,
    label: str,
    description: str,
    *,
    read_only: bool,
    input_schema: dict[str, Any] | None = None,
) -> CapabilityDefinition:
    return CapabilityDefinition(
        key=f"webmcp.{name}",
        kind="webmcp_tool",
        label=label,
        description=description,
        read_only=read_only,
        public=False,
        webmcp_name=name,
        input_schema=input_schema or {},
    )


CAPABILITY_REGISTRY: tuple[CapabilityDefinition, ...] = (
    CapabilityDefinition(
        key="site.cache_review",
        kind="site_capability",
        label="Cache review",
        description="Review source-specific cache status and controls through the existing human interface.",
        read_only=True,
        public=True,
        manifest_id="cache_review",
    ),
    CapabilityDefinition(
        key="site.local_resources",
        kind="site_capability",
        label="Local resources",
        description="Search and inspect locally cached media, messages, and saved prompts through the existing human interface.",
        read_only=True,
        public=True,
        manifest_id="local_resources",
    ),
    CapabilityDefinition(
        key="site.agent_workspace",
        kind="site_capability",
        label="Agent workspace",
        description="Configure and supervise the existing signed-in Web Agent workflow without granting Site tools direct task-execution authority.",
        read_only=False,
        public=True,
        manifest_id="agent_workspace",
    ),
    CapabilityDefinition(
        key="site.configuration",
        kind="site_capability",
        label="Configuration",
        description="Review local runtime, storage, browser, and Agent settings through the existing human interface.",
        read_only=True,
        public=True,
        manifest_id="configuration",
    ),
    CapabilityDefinition(
        key="agent.run",
        kind="agent_lifecycle",
        label="Agent run lifecycle",
        description="Start, observe, verify, and complete one bounded browser-mediated Agent run.",
        read_only=False,
    ),
    CapabilityDefinition(
        key="agent.recovery.doctor",
        kind="agent_recovery",
        label="Agent doctor recovery",
        description="Diagnose and explicitly reconcile local Agent runtime state without retrying an external prompt.",
        read_only=False,
    ),
    _action(
        "list",
        "List files",
        "List bounded, non-sensitive paths inside the selected Agent workspace.",
        read_only=True,
    ),
    _action(
        "read",
        "Read a file",
        "Read a bounded text range from one non-sensitive workspace file.",
        read_only=True,
    ),
    _action(
        "search",
        "Search files",
        "Search literal text inside the selected workspace with bounded results.",
        read_only=True,
    ),
    _action(
        "replace",
        "Replace text",
        "Replace one exact occurrence in an existing workspace file.",
        read_only=False,
    ),
    _action(
        "replace_base64",
        "Replace encoded text",
        "Replace one exact occurrence using base64 transport for quote-safe content.",
        read_only=False,
    ),
    _action(
        "write",
        "Write a file",
        "Create one new workspace file with bounded text content.",
        read_only=False,
    ),
    _action(
        "write_base64",
        "Write encoded file",
        "Create one new workspace file using base64 transport for quote-safe content.",
        read_only=False,
    ),
    _action(
        "run",
        "Run verification",
        "Run one approved, bounded inspection or verification command and fingerprint the workspace before and after it.",
        read_only=True,
    ),
    _action(
        "bodycheck",
        "Run bodycheck",
        "Check the current bounded diff and repository instruction files before final publication.",
        read_only=True,
    ),
    _action(
        "final",
        "Publish final",
        "Publish a final summary only after current verification and bodycheck evidence exists.",
        read_only=False,
    ),
    _observation(
        "provider_turn",
        "Provider turn observation",
        "Observe one bounded provider turn for controller parsing without persisting page content.",
    ),
    _observation(
        "browser_interruption",
        "Browser interruption observation",
        "Observe a bounded browser interruption and recovery state without resubmitting the turn.",
    ),
    _observation(
        "agent_status",
        "Agent status observation",
        "Expose bounded Agent lifecycle state to the local human interface and doctor diagnostics.",
    ),
    _observation(
        "browser_session",
        "Browser session observation",
        "Observe bounded browser/provider readiness metadata without reading page content.",
    ),
    _observation(
        "agent_response",
        "Agent response observation",
        "Observe a bounded local Agent response summary without adding raw provider transcript data to the event ledger.",
    ),
    _webmcp(
        "get_site_capabilities",
        "Discover site capabilities",
        "Read the trusted, bounded capability and navigation inventory for this local application.",
        read_only=True,
        input_schema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    ),
    _webmcp(
        "get_page_context",
        "Observe page context",
        "Read bounded metadata for the current top-level page without reading page content.",
        read_only=True,
        input_schema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    ),
    _webmcp(
        "navigate_to_site_target",
        "Navigate to a site target",
        "Navigate the current top-level tab to one allowlisted same-origin human page.",
        read_only=False,
        input_schema={
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "Stable identifier of an allowlisted destination.",
                },
            },
            "required": ["target"],
            "additionalProperties": False,
        },
    ),
)


CAPABILITIES_BY_KEY = {capability.key: capability for capability in CAPABILITY_REGISTRY}
AGENT_ACTIONS = {
    capability.action_name: capability
    for capability in CAPABILITY_REGISTRY
    if capability.kind == "agent_action" and capability.action_name
}
PAGE_OBSERVATIONS = {
    capability.key.removeprefix("page.observe."): capability
    for capability in CAPABILITY_REGISTRY
    if capability.kind == "page_observation"
}
WEBMCP_TOOLS = {
    capability.webmcp_name: capability
    for capability in CAPABILITY_REGISTRY
    if capability.kind == "webmcp_tool" and capability.webmcp_name
}


NAVIGATION_TARGETS: tuple[NavigationTarget, ...] = (
    NavigationTarget(
        "x_cache",
        "X cache",
        "Open the X Likes cache overview without starting or stopping a cache job.",
        "/cache/x",
    ),
    NavigationTarget(
        "grok_cache",
        "Grok cache",
        "Open the Grok cache overview without starting or stopping a cache job.",
        "/cache/grok",
    ),
    NavigationTarget(
        "chatgpt_cache",
        "ChatGPT cache",
        "Open the ChatGPT cache overview without starting or stopping a cache job.",
        "/cache/chatgpt",
    ),
    NavigationTarget(
        "gemini_cache",
        "Gemini cache",
        "Open the Gemini cache overview without starting or stopping a cache job.",
        "/cache/gemini",
    ),
    NavigationTarget(
        "local_resources",
        "Local resources",
        "Open the local cached-resource browser without deleting, restoring, or exporting data.",
        "/browser",
    ),
    NavigationTarget(
        "agent_workspace",
        "Agent workspace",
        "Open the Agent workspace without submitting a prompt or authorizing a terminal command.",
        "/agent",
    ),
    NavigationTarget(
        "settings",
        "Settings",
        "Open Settings without changing persisted configuration.",
        "/settings",
    ),
)


def capability_for_action(action_name: str) -> CapabilityDefinition | None:
    """Return the registered Agent Action for one protocol action name."""
    return AGENT_ACTIONS.get(str(action_name or "").strip().lower())


def capability_for_observation(observation_name: str) -> CapabilityDefinition | None:
    """Return the registered page observation by its stable short name."""
    return PAGE_OBSERVATIONS.get(str(observation_name or "").strip().lower())


def public_manifest_capabilities() -> list[dict[str, str]]:
    """Return bounded public groups derived from the detailed registry."""
    records = [
        capability.as_manifest_record()
        for capability in CAPABILITY_REGISTRY
        if capability.public
    ]
    records.extend(
        [
            {
                "id": "agent_actions",
                "label": "Agent actions",
                "description": (
                    f"The bounded local Agent Action protocol ({len(AGENT_ACTIONS)} registered actions) "
                    "for reading, editing, verification, bodycheck, and final publication."
                ),
            },
            {
                "id": "page_observation",
                "label": "Page observation",
                "description": (
                    f"The bounded page-observation layer ({len(PAGE_OBSERVATIONS)} registered observations) "
                    "used to inspect provider, browser, and Agent state without persisting page content."
                ),
            },
            {
                "id": "webmcp_tools",
                "label": "WebMCP tools",
                "description": (
                    f"The shared WebMCP surface ({len(WEBMCP_TOOLS)} registered tools) for capability discovery, "
                    "bounded page context, and allowlisted same-origin navigation."
                ),
            },
        ]
    )
    return records


def build_agent_optimization_manifest() -> dict[str, Any]:
    """Build the project-owned manifest from the single capability registry."""
    return {
        "contractVersion": AGENT_OPTIMIZATION_CONTRACT_VERSION,
        "profile": AGENT_OPTIMIZATION_PROFILE,
        "status": "project-convention",
        "site": {
            "id": "cache-likes-from-twitter",
            "name": "CacheLikesFromTwitter",
            "description": (
                "A local console for reviewing cached X, Grok, ChatGPT, and Gemini resources "
                "and supervising browser-backed Agent workflows."
            ),
            "privacyBoundary": (
                "Local cached content, settings, authenticated sessions, and Agent context remain "
                "behind the existing application routes and are not returned by the v1 Site tools."
            ),
        },
        "capabilities": public_manifest_capabilities(),
        "navigation": [target.as_dict() for target in NAVIGATION_TARGETS],
    }


def capability_registry_snapshot() -> dict[str, Any]:
    """Return the internal registry for local diagnostics and tests."""
    return {
        "version": CAPABILITY_REGISTRY_VERSION,
        "capabilities": [capability.as_dict() for capability in CAPABILITY_REGISTRY],
        "navigation": [target.as_dict() for target in NAVIGATION_TARGETS],
    }
