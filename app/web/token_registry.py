"""Read the local CSS foundation token registry for the Style tokens page.

Code version: v0.3.0-codex.4
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
    excluded_groups = {
        "Color and status",
        "Layout and motion",
        "Product components",
        "Surfaces and effects",
        "Typography",
    }
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


def build_style_token_component_rows() -> list[dict[str, object]]:
    """Return explicit browser and table specimens for the Style tokens page."""
    registry = load_css_token_registry()

    def token_rows(names: tuple[str, ...]) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for name in names:
            definition = registry.get(name)
            if definition is None:
                continue
            rows.append(
                {
                    "name": definition.name,
                    "value": definition.value,
                    "line": definition.line,
                    "reference_count": definition.reference_count,
                }
            )
        return rows

    def component_row(
        *,
        row_id: str,
        name: str,
        sample_kind: str,
        token_names: tuple[str, ...],
        sample_title: str = "",
        sample_copy: str = "",
    ) -> dict[str, object]:
        return {
            "id": row_id,
            "name": name,
            "sample_kind": sample_kind,
            "sample_title": sample_title,
            "sample_copy": sample_copy,
            "tokens": token_rows(token_names),
            "related_styles": [],
        }

    return [
        component_row(
            row_id="secondary-button",
            name="Secondary button",
            sample_kind="secondary-button",
            sample_title="Refresh cache",
            sample_copy="The Local resources action keeps the shared secondary-button surface and states.",
            token_names=(
                "--glass-chip-background-strong",
                "--glass-chip-background-hover",
                "--glass-chip-border",
                "--glass-chip-shadow",
                "--glass-chip-shadow-hover",
                "--radius-pill",
                "--font-tooltip",
                "--font-weight-semibold",
            ),
        ),
        component_row(
            row_id="primary-button",
            name="Primary button",
            sample_kind="primary-button",
            sample_title="Start",
            sample_copy="The primary cache action uses a blue surface, white text, and explicit disabled-state tokens.",
            token_names=(
                "--sidebar-action-button-radius",
                "--sidebar-action-button-min-height",
                "--sidebar-action-button-padding-inline",
                "--sidebar-action-primary-background",
                "--sidebar-action-primary-background-hover",
                "--sidebar-action-primary-background-disabled",
                "--sidebar-action-primary-color",
                "--sidebar-action-primary-color-disabled",
                "--accent-focus-ring",
                "--font-form-control",
                "--font-weight-bold",
            ),
        ),
        component_row(
            row_id="global-theme-toggle",
            name="Global theme toggle",
            sample_kind="global-theme-toggle",
            sample_title="Appearance",
            sample_copy="The circular theme control keeps the current appearance visible and reverses its action label.",
            token_names=(
                "--settings-round-icon-button-size",
                "--settings-round-icon-button-icon-size",
                "--settings-round-icon-button-radius",
                "--settings-round-icon-button-border",
                "--settings-round-icon-button-background",
                "--settings-round-icon-button-background-hover",
                "--settings-round-icon-button-shadow",
                "--settings-round-icon-button-shadow-hover",
                "--settings-round-icon-button-shadow-active",
                "--settings-round-icon-button-color",
                "--settings-round-icon-button-color-hover",
                "--frosted-glass-blur",
                "--motion-standard",
                "--motion-press",
            ),
        ),
        component_row(
            row_id="shared-cache-settings-link",
            name="Shared cache settings link",
            sample_kind="shared-cache-settings-link",
            sample_title="Open shared cache settings",
            sample_copy="A compact utility link uses a white glass surface and blue text for shared settings navigation.",
            token_names=(
                "--glass-chip-background-strong",
                "--glass-chip-background-hover",
                "--glass-chip-border",
                "--glass-chip-shadow",
                "--glass-chip-shadow-hover",
                "--accent-text",
                "--accent-text-hover",
                "--control-compact-height",
                "--radius-pill",
                "--font-size-3",
                "--font-weight-semibold",
                "--motion-standard",
                "--motion-press",
            ),
        ),
        component_row(
            row_id="prompt-tag",
            name="Prompt tag",
            sample_kind="prompt-tag",
            sample_title="PS",
            sample_copy="Saved prompt remarks use a compact blue pill with a clear remove affordance.",
            token_names=(
                "--accent-border-strong",
                "--accent-surface-soft",
                "--accent-text",
                "--radius-pill",
                "--font-ui-xs",
            ),
        ),
        component_row(
            row_id="local-store-pagination",
            name="Local store pagination",
            sample_kind="local-store-pagination",
            sample_title="Sessions",
            sample_copy="The floating pager keeps the active page in a blue spatial indicator.",
            token_names=(
                "--radius-pill",
                "--accent-fill",
                "--accent-shadow-strong",
                "--theme-glass-highlight",
                "--frosted-glass-background",
                "--frosted-glass-border",
                "--frosted-glass-shadow",
                "--frosted-glass-blur",
                "--font-table-body",
                "--font-weight-medium",
                "--font-weight-bold",
                "--motion-duration-spatial",
                "--motion-bouncy",
            ),
        ),
        component_row(
            row_id="shared-select-filter",
            name="Shared select filter",
            sample_kind="shared-select-filter",
            sample_title="Sort cached text",
            sample_copy="The browser sort trigger uses the same accessible menu pattern as shared table filters.",
            token_names=(
                "--control-liquid-background",
                "--control-liquid-background-hover",
                "--control-liquid-border",
                "--control-liquid-shadow",
                "--control-liquid-shadow-focus",
                "--control-liquid-blur",
                "--browser-picker-chevron-image",
                "--radius-pill",
                "--control-form-height",
            ),
        ),
        component_row(
            row_id="agent-browser-selector",
            name="Agent browser selector",
            sample_kind="agent-browser-selector",
            sample_title="Browser",
            sample_copy="The Agent browser selector keeps the active Edge choice visible in a shared frosted menu.",
            token_names=(
                "--control-liquid-background",
                "--control-liquid-background-hover",
                "--control-liquid-border",
                "--control-liquid-shadow",
                "--control-liquid-shadow-focus",
                "--control-liquid-blur",
                "--browser-picker-chevron-image",
                "--theme-success-strong",
                "--theme-glass-highlight",
                "--radius-pill",
                "--font-table-body",
                "--font-weight-regular",
            ),
        ),
        component_row(
            row_id="scrollable-data-table",
            name="Scrollable data table",
            sample_kind="scrollable-data-table",
            sample_title="Transaction history",
            sample_copy="A sticky header, internally scrolling body, Type filter, and in-shell pagination stay synchronized.",
            token_names=(
                "--scrollable-data-table-header-padding",
                "--scrollable-data-table-cell-padding",
                "--scrollable-data-table-summary-line-height",
                "--scrollable-data-table-summary-padding",
                "--scrollable-data-table-header-height",
                "--scrollable-data-table-min-width",
                "--scrollable-data-table-header-color",
                "--scrollable-data-table-scrollbar-gutter",
                "--scrollable-data-table-row-background",
                "--scrollable-data-table-row-background-alt",
                "--scrollable-data-table-summary-background",
                "--scrollable-data-table-summary-border",
                "--scrollable-data-table-summary-shadow",
                "--scrollable-data-table-summary-blur",
            ),
        ),
    ]


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
