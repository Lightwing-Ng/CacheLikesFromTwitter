"""Read the local CSS foundation token registry for the Style tokens page.

Code version: v0.1.0-codex.1
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
