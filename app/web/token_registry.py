"""Read the local CSS foundation token registry for the Style tokens page.

Code version: v0.2.0-codex.3
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import re


STYLE_CSS_PATH = Path(__file__).resolve().parent / "static" / "style.css"
_CSS_TOKEN_PATTERN = re.compile(
    r"(?P<name>--[A-Za-z0-9_-]+)\s*:\s*(?P<value>.*?);",
    re.DOTALL,
)
_CSS_REFERENCE_TEMPLATE = r"var\(\s*{name}(?:\s*[,)]|\s*$)"


@dataclass(frozen=True, slots=True)
class CssTokenDefinition:
    """A custom property declared in the stylesheet's root token block."""

    name: str
    value: str
    line: int
    reference_count: int
    category: str


def _extract_root_blocks(css_text: str) -> list[tuple[int, str]]:
    """Return every root block, including the compatibility layer overrides."""
    blocks: list[tuple[int, str]] = []
    for selector_match in re.finditer(r":root(?:[^\{]*)\{", css_text):
        block_start = selector_match.end() - 1
        depth = 0
        for index in range(block_start, len(css_text)):
            character = css_text[index]
            if character == "{":
                depth += 1
            elif character == "}":
                depth -= 1
                if depth == 0:
                    blocks.append((block_start + 1, css_text[block_start + 1:index]))
                    break
        else:
            raise ValueError("Could not find the closing brace for a root token block.")

    if not blocks:
        raise ValueError("Could not find a :root selector in the stylesheet.")
    return blocks


def _token_category(token_name: str) -> str:
    """Return a stable display group without duplicating a token catalog."""
    name = token_name.removeprefix("--")
    if name.startswith(("font-",)):
        return "Typography"
    if name.startswith(("theme-", "color-", "accent-")):
        return "Color and status"
    if name.startswith(("glass-", "frosted-", "liquid-", "tooltip-", "panel")):
        return "Surfaces and effects"
    if name.startswith(("control-", "text-input-", "settings-", "sidebar-action-", "mode-switch", "strategy-")):
        return "Controls"
    if name.startswith(("radius", "spacing", "page-", "global-", "responsive-", "sidebar-", "app-shell", "workspace-", "viewport-", "layer-", "motion-")):
        return "Layout and motion"
    if name.startswith(("browser-", "cache-", "local-store-", "scrollable-", "ticker-")):
        return "Product components"
    return "Foundation"


@lru_cache(maxsize=4)
def _load_cached_token_registry(css_path_text: str) -> dict[str, CssTokenDefinition]:
    css_path = Path(css_path_text)
    css_text = css_path.read_text(encoding="utf-8")
    registry: dict[str, CssTokenDefinition] = {}

    for root_content_start, root_content in _extract_root_blocks(css_text):
        for match in _CSS_TOKEN_PATTERN.finditer(root_content):
            token_name = match.group("name")
            if token_name in registry:
                continue
            token_value = match.group("value").strip()
            reference_pattern = re.compile(
                _CSS_REFERENCE_TEMPLATE.format(name=re.escape(token_name)),
                re.MULTILINE,
            )
            reference_count = len(reference_pattern.findall(css_text))
            absolute_start = root_content_start + match.start()
            line_number = css_text.count("\n", 0, absolute_start) + 1
            registry[token_name] = CssTokenDefinition(
                name=token_name,
                value=token_value,
                line=line_number,
                reference_count=reference_count,
                category=_token_category(token_name),
            )
    return registry


def load_css_token_registry(css_path: Path | None = None) -> dict[str, CssTokenDefinition]:
    """Load root token definitions and their stylesheet reference counts."""
    target_path = (css_path or STYLE_CSS_PATH).resolve()
    return dict(_load_cached_token_registry(str(target_path)))


def build_reused_style_token_groups(
    *,
    minimum_references: int = 2,
) -> list[dict[str, object]]:
    """Build the grouped rows shown by Settings → Style tokens."""
    grouped: dict[str, list[CssTokenDefinition]] = defaultdict(list)
    for definition in load_css_token_registry().values():
        if definition.reference_count >= minimum_references:
            grouped[definition.category].append(definition)

    category_order = (
        "Foundation",
        "Color and status",
        "Typography",
        "Surfaces and effects",
        "Controls",
        "Layout and motion",
        "Product components",
    )
    groups: list[dict[str, object]] = []
    for category in category_order:
        definitions = sorted(grouped.get(category, []), key=lambda item: item.name)
        if not definitions:
            continue
        groups.append(
            {
                "name": category,
                "tokens": [
                    {
                        "name": definition.name,
                        "value": definition.value,
                        "line": definition.line,
                        "reference_count": definition.reference_count,
                    }
                    for definition in definitions
                ],
            }
        )
    return groups


def build_reused_style_token_rows(
    *,
    minimum_references: int = 2,
) -> list[dict[str, object]]:
    """Adapt the live registry to cards with working project-component demos."""
    rows: list[dict[str, object]] = []
    excluded_groups = {"Color and status", "Layout and motion", "Product components"}
    for group in build_reused_style_token_groups(
        minimum_references=minimum_references,
    ):
        group_name = str(group["name"])
        if group_name in excluded_groups:
            continue
        tokens = list(group["tokens"])
        slug = re.sub(r"[^a-z0-9]+", "-", group_name.lower()).strip("-")
        total_references = sum(int(token["reference_count"]) for token in tokens)
        demo = _build_style_token_demo(
            group_name=group_name,
            token_count=len(tokens),
            total_references=total_references,
        )
        rows.append(
            {
                "id": f"style-token-{slug}",
                "name": group_name,
                **demo,
                "tokens": tokens,
                "related_styles": [],
            }
        )
    return rows


def _build_style_token_demo(
    *,
    group_name: str,
    token_count: int,
    total_references: int,
) -> dict[str, object]:
    """Return an interactive, representative component for one token category."""
    if group_name == "Foundation":
        return {
            "sample_kind": "metric-summary",
            "sample_title": "Foundation metrics",
            "sample_copy": "A live metric-card composition using the shared baseline.",
            "sample_metrics": [
                {"label": "Tokens", "value": f"{token_count:,}"},
                {"label": "References", "value": f"{total_references:,}"},
                {"label": "Scope", "value": "Root"},
            ],
        }
    if group_name == "Color and status":
        return {
            "sample_kind": "status-states",
            "sample_title": "Status feedback",
            "sample_copy": "Select a state to preview the status-chip language.",
        }
    if group_name == "Typography":
        return {
            "sample_kind": "type-specimen",
            "sample_title": "Readable hierarchy",
            "sample_copy": "UI, metadata, and code text share one type system.",
        }
    if group_name == "Surfaces and effects":
        return {
            "sample_kind": "glass-surface",
            "sample_title": "Layered surface",
            "sample_copy": "The frosted surface keeps content distinct without a hard edge.",
        }
    if group_name == "Controls":
        return {
            "sample_kind": "range-mode",
            "sample_title": "Interactive controls",
            "sample_copy": "Type, select, and switch state are all live in this preview.",
        }
    if group_name == "Layout and motion":
        return {
            "sample_kind": "workflow-card",
            "sample_title": "Responsive workspace",
            "sample_copy": "Refresh the preview to see shared action feedback.",
        }
    return {
        "sample_kind": "product-summary",
        "sample_title": "Local resources",
        "sample_copy": "A compact result summary uses shared product components.",
    }
