"""Security helpers for exposing the local Agent control plane on a LAN."""

# Code version: v1.0.0-codex.1

from __future__ import annotations

import os
import secrets
from ipaddress import ip_address


AGENT_ACCESS_PASSWORD_ENV = "CACHELIKES_AGENT_PASSWORD"
DEFAULT_AGENT_ACCESS_PASSWORD = "195135"
AGENT_ACCESS_SESSION_KEY = "agent_access_granted"


def resolve_agent_access_password() -> str:
    """Return the configured Agent password, falling back to the requested default."""
    return str(os.environ.get(AGENT_ACCESS_PASSWORD_ENV, "")).strip() or DEFAULT_AGENT_ACCESS_PASSWORD


def validate_agent_access_password(presented_password: str | None) -> bool:
    """Compare one submitted password without exposing the configured value."""
    configured_password = resolve_agent_access_password()
    normalized_presented_password = str(presented_password or "").strip()
    return bool(normalized_presented_password) and secrets.compare_digest(
        normalized_presented_password,
        configured_password,
    )


def is_loopback_or_private_address(value: str | None) -> bool:
    """Return whether an address belongs to this host or a private network."""
    candidate = (value or "").strip().split("%", 1)[0]
    if not candidate:
        return False
    if candidate.lower() == "localhost":
        return True
    try:
        return ip_address(candidate).is_loopback or ip_address(candidate).is_private
    except ValueError:
        return False


def is_allowed_agent_network_request(remote_addr: str | None, host_name: str | None) -> bool:
    """Allow loopback and private-IP requests while rejecting public host rebinding."""
    return is_loopback_or_private_address(remote_addr) and is_loopback_or_private_address(host_name)
