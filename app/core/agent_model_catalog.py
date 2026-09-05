"""Build bounded ChatGPT choices from the provider's rendered model menu.

Code version: v1.0.0-codex.1
"""

from __future__ import annotations

import re
from typing import Any


LATEST_CHATGPT_MODEL = "latest_available"
LIVE_MODEL_PREFIX = "live:"
_MODEL_LABEL = re.compile(r"GPT[- ]?\d+(?:\.\d+)*(?:[ -][A-Za-z0-9]+)*", re.IGNORECASE)


def live_model_option(label: str) -> dict[str, Any] | None:
    """Accept a short model label, never arbitrary page text or instructions."""
    label = " ".join(str(label or "").split())
    if len(label) > 80 or (label.casefold() != "latest" and not _MODEL_LABEL.fullmatch(label)):
        return None
    return {
        "key": LIVE_MODEL_PREFIX + label.casefold(),
        "label": label,
        "ui_label": label,
        "remote_label": label,
        "remote_labels": (label,),
        "remote_model_labels": (label,),
    }


def chatgpt_live_catalog(values: list[str]) -> list[dict[str, Any]]:
    """Prefer the provider's Latest alias, then the newest full GPT family.

    Version order is a selection policy, not a benchmark claim. Lightweight
    variants are excluded from the automatic choice even when they are newer.
    """
    options = {}
    for value in values[:64]:
        option = live_model_option(value)
        if option and not re.search(
            r"\b(?:mini|nano|lite|instant|luna|terra|spark)\b", option["label"], re.IGNORECASE
        ):
            options.setdefault(option["key"], option)

    def rank(option: dict[str, Any]) -> tuple:
        label = option["label"].casefold()
        if label == "latest":
            return True, (), False
        version = tuple(int(part) for part in re.search(r"\d+(?:\.\d+)*", label)[0].split("."))
        return False, version, bool(re.search(r"\bpro\b", label))

    return sorted(options.values(), key=rank, reverse=True)
