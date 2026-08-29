"""Computer-use Agent boundary for access, source discovery, and execution."""

# Code version: v1.4.0-codex.1

from ..agent_access_security import (
    AGENT_ACCESS_SESSION_KEY,
    is_allowed_agent_network_request,
    validate_agent_access_password,
)
from ..agent_session_sources import (
    list_agent_project_sessions,
    list_agent_sources,
    normalize_agent_source_catalog_payload,
    normalize_agent_project_url,
    probe_and_collect_claude_sources,
    probe_and_collect_grok_sources,
)
from ..agent_source_cache import AgentSourceCache
from .capability_registry import (
    AGENT_ACTIONS,
    CAPABILITY_REGISTRY,
    CAPABILITY_REGISTRY_VERSION,
    PAGE_OBSERVATIONS,
    WEBMCP_TOOLS,
    build_agent_optimization_manifest,
    capability_for_action,
    capability_for_observation,
    capability_registry_snapshot,
)
from ..computer_use_agent import (
    AGENT_MODEL_OPTIONS_BY_PLATFORM,
    AGENT_PLATFORM_OPTIONS,
    OPERATING_SYSTEM_OPTIONS,
    ComputerUseAgentService,
    ComputerUseSettingsStore,
    browser_options_for_host,
    default_model_for_platform,
    is_loopback_address,
    launch_terminal_authorization,
    open_agent_in_browser,
    validate_computer_use_settings,
)

__all__ = [
    "AGENT_ACCESS_SESSION_KEY",
    "AGENT_ACTIONS",
    "AGENT_MODEL_OPTIONS_BY_PLATFORM",
    "AGENT_PLATFORM_OPTIONS",
    "AgentSourceCache",
    "CAPABILITY_REGISTRY",
    "CAPABILITY_REGISTRY_VERSION",
    "ComputerUseAgentService",
    "ComputerUseSettingsStore",
    "OPERATING_SYSTEM_OPTIONS",
    "PAGE_OBSERVATIONS",
    "WEBMCP_TOOLS",
    "browser_options_for_host",
    "build_agent_optimization_manifest",
    "capability_for_action",
    "capability_for_observation",
    "capability_registry_snapshot",
    "default_model_for_platform",
    "is_allowed_agent_network_request",
    "is_loopback_address",
    "launch_terminal_authorization",
    "list_agent_project_sessions",
    "list_agent_sources",
    "normalize_agent_source_catalog_payload",
    "normalize_agent_project_url",
    "open_agent_in_browser",
    "probe_and_collect_claude_sources",
    "probe_and_collect_grok_sources",
    "validate_agent_access_password",
    "validate_computer_use_settings",
]
