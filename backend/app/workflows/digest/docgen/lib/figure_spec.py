"""Structured static figure specs and lecture-note HTML rendering."""

from __future__ import annotations

import html
import math
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

FigureType = Literal[
    "concept_map",
    "process_steps",
    "comparison_table",
    "formula_derivation",
    "problem_diagram",
    "mistake_card",
]

ShapeType = Literal[
    "ellipse",
    "circle",
    "rectangle",
    "triangle",
    "polygon",
    "angle",
    "arc",
    "region",
]

ElementKind = Literal[
    "axis",
    "curve",
    "point",
    "line",
    "vector",
    "shape",
    "label",
    "step",
    "formula",
    "table_row",
    "relation",
    "callout",
]


def _clean_text(value: Any, *, limit: int = 160) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _clean_list(value: Any, *, limit: int = 8, item_limit: int = 160) -> list[str]:
    items = value if isinstance(value, list) else ([] if value is None else [value])
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = _clean_text(item, limit=item_limit)
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(text)
        if len(cleaned) >= limit:
            break
    return cleaned


def _unit_coord(value: Any, *, default: float = 50.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(100.0, parsed))


def _positive_number(value: Any, *, default: float = 8.0, max_value: float = 80.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(max_value, parsed))


def _angle_degrees(value: Any, *, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return max(-360.0, min(360.0, parsed))


def _point_list(value: Any, *, limit: int = 8) -> list[list[float]]:
    if not isinstance(value, list):
        return []
    points: list[list[float]] = []
    for item in value[:limit]:
        if isinstance(item, dict):
            x = _unit_coord(item.get("x"))
            y = _unit_coord(item.get("y"))
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            x = _unit_coord(item[0])
            y = _unit_coord(item[1])
        else:
            continue
        points.append([x, y])
    return points


def _svg_escape(value: Any) -> str:
    return html.escape(_clean_text(value, limit=80), quote=True)


def _svg_escape_short(value: Any, *, limit: int = 54) -> str:
    return html.escape(_clean_text(value, limit=limit), quote=True)


_INLINE_FORMULA_MARK_RE = re.compile(r"([_^])(?:\{([^{}]{1,12})\}|([A-Za-z0-9+\-=]{1,12}))")
_CHINESE_PLACEHOLDER_SUFFIX_RE = re.compile(r"^(.+[\u4e00-\u9fff])[A-D]$")


def _svg_inline_formula_text(value: Any, *, limit: int = 54) -> str:
    text = _clean_text(value, limit=limit)
    if not text or not any(mark in text for mark in ("^", "_")):
        return html.escape(text, quote=True)

    parts: list[str] = []
    cursor = 0
    for match in _INLINE_FORMULA_MARK_RE.finditer(text):
        if match.start() > cursor:
            parts.append(html.escape(text[cursor:match.start()], quote=True))
        token = html.escape(match.group(2) or match.group(3) or "", quote=True)
        if token:
            shift = "super" if match.group(1) == "^" else "sub"
            parts.append(f'<tspan baseline-shift="{shift}" font-size="70%">{token}</tspan>')
        cursor = match.end()
    if cursor < len(text):
        parts.append(html.escape(text[cursor:], quote=True))
    return "".join(parts)


def _render_svg_text(
    *,
    x: float,
    y: float,
    text: Any,
    font_size: float,
    limit: int,
    text_anchor: str | None = None,
    font_weight: str | None = None,
) -> str:
    attrs = [f'x="{x:.1f}"', f'y="{y:.1f}"', f'font-size="{font_size:g}"']
    if text_anchor:
        attrs.append(f'text-anchor="{html.escape(text_anchor, quote=True)}"')
    if font_weight:
        attrs.append(f'font-weight="{html.escape(font_weight, quote=True)}"')
    return f'<text {" ".join(attrs)}>{_svg_inline_formula_text(text, limit=limit)}</text>'


def _html_escape(value: Any, *, limit: int = 240) -> str:
    return html.escape(_clean_text(value, limit=limit), quote=True)


class FigureElement(BaseModel):
    """One renderer-controlled primitive in a static teaching figure."""

    model_config = ConfigDict(extra="allow")

    kind: ElementKind = "label"
    id: str = ""
    label: str = ""
    text: str = ""
    from_id: str = ""
    to_id: str = ""
    x: float = 50
    y: float = 50
    x2: float = 50
    y2: float = 50
    r: float = 8
    rx: float = 0
    ry: float = 0
    shape_type: ShapeType = "ellipse"
    points: list[list[float]] = Field(default_factory=list)
    start_angle: float = 0
    end_angle: float = 90
    cells: list[str] = Field(default_factory=list)
    items: list[str] = Field(default_factory=list)
    style: Literal["solid", "dashed", "highlight", "muted"] = "solid"

    @field_validator("id", "label", "text", "from_id", "to_id", mode="before")
    @classmethod
    def _text(cls, value: Any) -> str:
        return _clean_text(value, limit=120)

    @field_validator("x", "y", "x2", "y2", mode="before")
    @classmethod
    def _coords(cls, value: Any) -> float:
        return _unit_coord(value)

    @field_validator("r", "rx", "ry", mode="before")
    @classmethod
    def _radius(cls, value: Any) -> float:
        return _positive_number(value)

    @field_validator("start_angle", "end_angle", mode="before")
    @classmethod
    def _angles(cls, value: Any) -> float:
        return _angle_degrees(value)

    @field_validator("points", mode="before")
    @classmethod
    def _points(cls, value: Any) -> list[list[float]]:
        return _point_list(value)

    @field_validator("cells", "items", mode="before")
    @classmethod
    def _string_lists(cls, value: Any) -> list[str]:
        return _clean_list(value, limit=8, item_limit=120)


class FigureSpec(BaseModel):
    """Model-produced figure intent; final HTML/SVG is rendered by code."""

    model_config = ConfigDict(extra="allow")

    type: FigureType = "concept_map"
    title: str = ""
    summary: str = ""
    elements: list[FigureElement] = Field(default_factory=list)
    annotations: list[str] = Field(default_factory=list)
    emphasis: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    layout: dict[str, Any] = Field(default_factory=dict)

    @field_validator("title", "summary", mode="before")
    @classmethod
    def _text(cls, value: Any) -> str:
        return _clean_text(value, limit=180)

    @field_validator("annotations", "emphasis", "source_refs", mode="before")
    @classmethod
    def _string_lists(cls, value: Any) -> list[str]:
        return _clean_list(value, limit=6, item_limit=180)

    @field_validator("elements", mode="before")
    @classmethod
    def _limit_elements(cls, value: Any) -> list[Any]:
        items = value if isinstance(value, list) else ([] if value is None else [value])
        return list(items[:18])

    @model_validator(mode="after")
    def _ensure_minimum_content(self) -> "FigureSpec":
        if not self.elements and self.annotations:
            self.elements = [
                FigureElement(kind="step", label=str(index), text=text)
                for index, text in enumerate(self.annotations[:5], start=1)
            ]
        return self


class FigureCandidate(BaseModel):
    section_id: str = ""
    section_title: str = ""
    score: int = 0
    figure_type: FigureType = "concept_map"
    reason: str = ""
    source_excerpt: str = ""


class RenderedFigure(BaseModel):
    asset_path: str = ""
    preview_url: str = ""
    markdown_embed: str = ""
    validation_report: dict[str, Any] = Field(default_factory=dict)


def _plain_context_lines(context: str, *, limit: int = 4) -> list[str]:
    text = re.sub(r"```.*?```", "", str(context or ""), flags=re.DOTALL)
    lines = [
        _clean_text(line, limit=160)
        for line in re.split(r"[\n。；;]+", text)
        if _clean_text(line, limit=160)
    ]
    return lines[:limit]


def _has_problem_diagram_geometry(elements: list[FigureElement]) -> bool:
    kinds = {item.kind for item in elements}
    return bool(
        {"axis", "curve"} & kinds
        or "shape" in kinds
        or ("point" in kinds and ({"line", "vector"} & kinds))
    )


def _has_visual_symbol_or_value(text: str) -> bool:
    value = str(text or "")
    return bool(
        re.search(r"\d|[=<>≤≥+\-*/^&]|\\(?:frac|sqrt|sum|int|cdot|times|leq|geq)|[A-Za-z_]\w*[_^]", value)
    )


def _has_structural_relation_graph(elements: list[FigureElement]) -> bool:
    """Allow cross-discipline diagrams that encode structure with nodes and edges."""

    shape_keys: set[str] = set()
    aliases: dict[str, str] = {}
    for index, item in enumerate(elements[:18], start=1):
        if item.kind != "shape" or item.shape_type not in {"rectangle", "ellipse", "circle", "triangle"}:
            continue
        key = item.id or item.label or f"node_{index}"
        shape_keys.add(key)
        for alias in (item.id, item.label, key):
            if alias:
                aliases.setdefault(alias, key)
                aliases.setdefault(alias.casefold(), key)

    edges: set[tuple[str, str]] = set()
    for item in elements[:18]:
        if item.kind not in {"line", "vector"} or not item.from_id or not item.to_id:
            continue
        start = aliases.get(item.from_id) or aliases.get(item.from_id.casefold())
        end = aliases.get(item.to_id) or aliases.get(item.to_id.casefold())
        if start and end and start != end:
            edges.add((start, end))

    return len(shape_keys) >= 3 and len(edges) >= 2


def _has_visual_value_beyond_text(elements: list[FigureElement]) -> bool:
    """Check renderer-level visual substance without judging teaching semantics."""

    items = elements[:18]
    if any(item.kind in {"axis", "curve"} for item in items):
        return True
    if any(item.kind == "shape" and item.shape_type in {"angle", "arc", "polygon", "region"} for item in items):
        return True
    if any(item.kind in {"line", "vector"} and not (item.from_id and item.to_id) for item in items):
        return True
    if any(_has_visual_symbol_or_value(item.label or item.text) for item in items):
        return True
    point_count = sum(1 for item in items if item.kind == "point")
    connection_count = sum(1 for item in items if item.kind in {"line", "vector"})
    return (
        point_count >= 3 and connection_count >= 2
    ) or _has_structural_relation_graph(items)


def is_renderable_problem_diagram(spec: FigureSpec) -> bool:
    """Return whether a spec contains actual visual geometry."""

    return (
        spec.type == "problem_diagram"
        and _has_problem_diagram_geometry(spec.elements)
        and _has_visual_value_beyond_text(spec.elements)
    )


def is_renderable_static_figure(spec: FigureSpec) -> bool:
    """Return whether a spec would render a meaningful teaching figure."""

    if spec.type == "problem_diagram":
        return is_renderable_problem_diagram(spec)
    return False


def assess_static_figure_layout(spec: FigureSpec) -> dict[str, Any]:
    """Check whether a static problem diagram is legible enough to publish.

    This is intentionally conservative: if the planned SVG would likely be
    crowded, overlapped, or made of long prose labels, DocGen should skip it
    instead of shipping a confusing sidecar.
    """

    issues: list[str] = []
    metrics: dict[str, Any] = {
        "element_count": len(spec.elements),
        "label_count": 0,
        "long_label_count": 0,
        "label_overlap_count": 0,
        "out_of_bounds_label_count": 0,
        "geometry_bbox": None,
        "geometry_coverage": 0.0,
    }

    if spec.type != "problem_diagram":
        texts = _static_figure_text_values(spec)
        metrics["label_count"] = len(texts)
        issues.append("text_only_static_figure")
        if len(texts) > 8:
            issues.append("too_many_text_items")
        max_units = 12 if spec.type == "concept_map" else 38
        long_text_count = sum(1 for text in texts if _visual_text_units(text) > max_units)
        metrics["long_label_count"] = long_text_count
        if long_text_count:
            issues.append("long_text_items")
        return {"ok": not issues, "issues": sorted(set(issues)), "metrics": metrics}

    if not _has_problem_diagram_geometry(spec.elements):
        issues.append("nonvisual_problem_diagram")
        return {"ok": False, "issues": issues, "metrics": metrics}
    if not _has_visual_value_beyond_text(spec.elements):
        issues.append("text_only_relation_diagram")
        return {"ok": False, "issues": issues, "metrics": metrics}

    layout_elements, _ = _auto_layout_relation_graph(spec.elements[:18])
    layout_spec = spec.model_copy(update={"elements": layout_elements})

    if not _has_teaching_relation(layout_elements):
        issues.append("missing_visual_relation")

    elements = layout_elements
    if len(elements) > 12:
        issues.append("too_many_elements")

    geometry_boxes = _problem_diagram_geometry_boxes(layout_spec)
    label_boxes = _problem_diagram_label_boxes(layout_spec)
    metrics["label_count"] = len(label_boxes)
    if len(label_boxes) > 10:
        issues.append("too_many_labels")

    long_label_count = sum(1 for box in label_boxes if _visual_text_units(box[4]) > 14)
    metrics["long_label_count"] = long_label_count
    if long_label_count:
        issues.append("long_label_text")

    out_of_bounds_count = sum(1 for box in label_boxes if _bbox_outside_canvas(box))
    metrics["out_of_bounds_label_count"] = out_of_bounds_count
    if out_of_bounds_count:
        issues.append("label_out_of_bounds")

    overlap_count = 0
    for index, current in enumerate(label_boxes):
        for other in label_boxes[index + 1 :]:
            if _bbox_overlap_ratio(current, other) >= 0.18:
                overlap_count += 1
    metrics["label_overlap_count"] = overlap_count
    if overlap_count:
        issues.append("label_overlap")

    if geometry_boxes:
        merged = _merge_bboxes(geometry_boxes)
        metrics["geometry_bbox"] = [round(value, 1) for value in merged]
        coverage = _bbox_area(merged) / (620.0 * 330.0)
        metrics["geometry_coverage"] = round(coverage, 4)
        width = merged[2] - merged[0]
        height = merged[3] - merged[1]
        if len(elements) >= 5 and (width < 190 or height < 70) and overlap_count:
            issues.append("crowded_compact_layout")

    if issues == ["label_overlap"] and overlap_count <= 3 and len(label_boxes) <= 8:
        issues = []

    return {"ok": not issues, "issues": sorted(set(issues)), "metrics": metrics}


def normalize_figure_spec(
    spec: FigureSpec,
    *,
    fallback_title: str,
    context: str,
    allow_fallback_elements: bool = False,
) -> tuple[FigureSpec, dict[str, Any]]:
    """Constrain a model spec to facts traceable to the current section."""

    report: dict[str, Any] = {"source_ref_replacements": 0, "warnings": []}
    title = spec.title or fallback_title
    figure_type = "concept_map" if spec.type == "comparison_table" else spec.type
    elements = spec.elements[:18]
    if spec.type == "comparison_table":
        elements = _comparison_table_visual_elements(elements)
        report["warnings"].append("comparison_table_coerced_to_concept_map")
    layout = dict(spec.layout or {})
    if figure_type == "problem_diagram" and layout.pop("template", None) is not None:
        report["warnings"].append("template_layout_ignored")
    source_refs = [
        ref for ref in spec.source_refs
        if ref and _compact(ref) in _compact(context)
    ]
    if not source_refs:
        source_refs = _plain_context_lines(context, limit=3)
        report["source_ref_replacements"] = 1
    if not source_refs:
        report["warnings"].append("empty_source_refs")

    if figure_type == "problem_diagram":
        elements = _prune_problem_diagram_elements(elements)
        elements, layout_changed = _auto_layout_relation_graph(elements)
        elements = _ground_problem_diagram_labels(elements, context)
        if layout_changed:
            report["warnings"].append("relation_graph_auto_layout")

    normalized = spec.model_copy(
        update={
            "title": _clean_text(title, limit=120),
            "type": figure_type,
            "summary": spec.summary or (source_refs[0] if source_refs else ""),
            "source_refs": source_refs,
            "annotations": spec.annotations[:6],
            "emphasis": spec.emphasis[:4],
            "elements": elements,
            "layout": layout,
        }
    )
    if allow_fallback_elements and not normalized.elements:
        normalized = build_fallback_figure_spec(
            title=normalized.title or fallback_title,
            figure_type=normalized.type,
            context=context,
            goal=normalized.summary,
        )
        report["warnings"].append("fallback_elements_used")
    return normalized, report


def build_fallback_figure_spec(
    *,
    title: str,
    figure_type: FigureType,
    context: str,
    goal: str = "",
) -> FigureSpec:
    lines = _plain_context_lines(context, limit=5)
    if figure_type == "comparison_table":
        rows = [
            FigureElement(kind="relation", label=f"要点 {index}", text=line)
            for index, line in enumerate(lines[:4], start=1)
        ]
        return FigureSpec(type="concept_map", title=title, summary=goal or (lines[0] if lines else ""), elements=rows, source_refs=lines[:3])
    if figure_type == "formula_derivation":
        rows = [FigureElement(kind="formula", label=f"({index})", text=line) for index, line in enumerate(lines[:4], start=1)]
        return FigureSpec(type=figure_type, title=title, summary=goal or "按步骤理解公式关系。", elements=rows, source_refs=lines[:3])
    if figure_type == "problem_diagram":
        return FigureSpec(
            type=figure_type,
            title=title,
            summary=goal or (lines[0] if lines else ""),
            elements=[],
            annotations=[],
            source_refs=lines[:3],
            layout={},
        )
    rows = [FigureElement(kind="step", label=str(index), text=line) for index, line in enumerate(lines[:5], start=1)]
    return FigureSpec(type=figure_type, title=title, summary=goal or (lines[0] if lines else ""), elements=rows, source_refs=lines[:3])


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "")).casefold()


def _comparison_table_visual_elements(elements: list[FigureElement]) -> list[FigureElement]:
    visual: list[FigureElement] = []
    for index, item in enumerate(elements[:6], start=1):
        if item.kind == "table_row" and item.cells:
            label = item.cells[0] or f"要点 {index}"
            text = "；".join(cell for cell in item.cells[1:3] if cell)
            visual.append(FigureElement(kind="relation", label=label, text=text or label))
            continue
        if item.text or item.label:
            visual.append(
                FigureElement(
                    kind="relation",
                    label=item.label or f"要点 {index}",
                    text=item.text or item.label,
                )
            )
    return visual


def _prune_problem_diagram_elements(elements: list[FigureElement]) -> list[FigureElement]:
    """Keep a static sidecar diagram legible by dropping prose-only extras."""

    items = list(elements[:18])
    if not items:
        return []

    visual_items = [item for item in items if item.kind not in {"label", "callout", "step", "formula", "table_row", "relation"}]
    if len(items) > 7 and len(visual_items) >= 4:
        items = visual_items

    if len(items) <= 10:
        return items

    shapes = [
        item
        for item in items
        if item.kind == "shape" and item.shape_type in {"rectangle", "ellipse", "circle", "triangle"}
    ]
    semantic_edges = [
        item
        for item in items
        if item.kind in {"line", "vector"} and item.from_id and item.to_id
    ]
    if len(shapes) >= 3 and len(semantic_edges) >= 2:
        kept_shapes = shapes[:6]
        aliases: set[str] = set()
        for shape in kept_shapes:
            for alias in (shape.id, shape.label):
                if alias:
                    aliases.add(alias)
                    aliases.add(alias.casefold())
        kept_edges = [
            edge
            for edge in semantic_edges
            if (edge.from_id in aliases or edge.from_id.casefold() in aliases)
            and (edge.to_id in aliases or edge.to_id.casefold() in aliases)
        ][: max(2, 10 - len(kept_shapes))]
        compact = [*kept_shapes, *kept_edges]
        if len(compact) >= 5:
            return compact[:10]

    core_priority = {"axis": 0, "curve": 1, "point": 2, "shape": 3, "line": 4, "vector": 5}
    core = [item for item in items if item.kind in core_priority]
    if len(core) >= 4:
        return sorted(core, key=lambda item: core_priority.get(item.kind, 99))[:10]
    return items[:10]


def _ground_problem_diagram_labels(elements: list[FigureElement], context: str) -> list[FigureElement]:
    grounded: list[FigureElement] = []
    compact_context = _compact(context)
    for item in elements:
        updates: dict[str, str] = {}
        for field_name in ("label", "text"):
            value = getattr(item, field_name)
            match = _CHINESE_PLACEHOLDER_SUFFIX_RE.match(value)
            if not match:
                continue
            base = match.group(1).strip()
            if _compact(value) not in compact_context and _compact(base) in compact_context:
                updates[field_name] = base
        grounded.append(item.model_copy(update=updates) if updates else item)
    return grounded


def _static_figure_text_values(spec: FigureSpec) -> list[str]:
    values: list[str] = []
    if spec.type == "comparison_table":
        for item in spec.elements[:8]:
            values.extend(item.cells[:4])
    elif spec.type == "concept_map":
        for item in spec.elements[:8]:
            if item.kind in {"label", "step", "relation", "callout"}:
                values.append(item.label or item.text)
    elif spec.type in {"process_steps", "formula_derivation"}:
        for item in spec.elements[:8]:
            if item.kind in {"step", "formula", "relation", "label", "callout"}:
                values.append(item.text or item.label)
    elif spec.type == "mistake_card":
        for item in spec.elements[:8]:
            values.append(item.text or item.label)
    values.extend(spec.annotations[:4])
    return _clean_list(values, limit=10, item_limit=120)


def _comparison_table_as_concept_map(spec: FigureSpec) -> FigureSpec:
    return spec.model_copy(update={"type": "concept_map", "elements": _comparison_table_visual_elements(spec.elements)})


def render_figure_spec_html(spec: FigureSpec, *, title: str) -> str:
    """Render a spec as a single-file HTML/SVG figure.

    The generated asset is a figure only. Explanatory prose belongs to the
    Markdown document, not to the image sidecar.
    """

    figure_title = spec.title or title
    body = _render_body(spec)
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{_html_escape(figure_title)}</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: #fff;
      color: #111;
      font-family: Inter, "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", Arial, sans-serif;
      line-height: 1.58;
    }}
    .atm-figure {{
      width: min(760px, 100vw);
      margin: 0 auto;
      padding: 0;
      background: #fff;
    }}
    .atm-figure-main {{
      margin: 0 auto;
      width: min(700px, 100%);
    }}
    svg {{ display: block; width: 100%; height: auto; }}
  </style>
</head>
<body>
  <main class="atm-figure">
    <div class="atm-figure-main">{body}</div>
  </main>
</body>
</html>
"""


def _render_summary(spec: FigureSpec) -> str:
    if not spec.summary:
        return ""
    return f'<p class="atm-summary">{_html_escape(spec.summary, limit=220)}</p>'


def _render_emphasis(spec: FigureSpec) -> str:
    items = [_html_escape(item, limit=180) for item in spec.emphasis if item]
    if not items:
        return ""
    text = "；".join(items[:2])
    return f'<div class="atm-note">记忆：{text}</div>'


def _render_source_line(spec: FigureSpec) -> str:
    if not spec.source_refs:
        return ""
    ref = _html_escape(spec.source_refs[0], limit=160)
    return f'<p class="atm-source">对应正文：{ref}</p>'


def _render_body(spec: FigureSpec) -> str:
    if spec.type == "comparison_table":
        return _render_concept_map(_comparison_table_as_concept_map(spec))
    if spec.type == "formula_derivation":
        return _render_formula_derivation(spec)
    if spec.type == "problem_diagram":
        return _render_problem_diagram(spec)
    if spec.type == "mistake_card":
        return _render_mistake_card(spec)
    if spec.type == "process_steps":
        return _render_process_steps(spec)
    return _render_concept_map(spec)


def _render_comparison_table(spec: FigureSpec) -> str:
    rows = [item for item in spec.elements if item.kind == "table_row" and item.cells]
    if not rows:
        rows = [FigureElement(kind="table_row", cells=[item.label or str(index), item.text]) for index, item in enumerate(spec.elements[:5], start=1)]
    max_cols = max((len(row.cells) for row in rows), default=2)
    headers = ["项目", "说明", "要点", "易错点"][:max_cols]
    header_html = "".join(f"<th>{_html_escape(cell)}</th>" for cell in headers)
    row_html = []
    for row in rows[:8]:
        cells = [*row.cells, *[""] * max(0, max_cols - len(row.cells))][:max_cols]
        row_html.append("<tr>" + "".join(f"<td>{_html_escape(cell, limit=180)}</td>" for cell in cells) + "</tr>")
    return f"<table><thead><tr>{header_html}</tr></thead><tbody>{''.join(row_html)}</tbody></table>"


def _render_formula_derivation(spec: FigureSpec) -> str:
    rows = [item for item in spec.elements if item.kind in {"formula", "step", "relation", "label"} and (item.text or item.label)]
    if not rows:
        return _render_process_steps(spec)
    return _render_vertical_flow_svg(
        rows[:5],
        caption=spec.annotations[0] if spec.annotations else "公式关系图",
        label_prefix="式",
    )


def _render_process_steps(spec: FigureSpec) -> str:
    rows = [item for item in spec.elements if item.kind in {"step", "formula", "label", "callout"} and (item.text or item.label)]
    if not rows:
        rows = [FigureElement(kind="step", label=str(index), text=text) for index, text in enumerate(spec.annotations[:5], start=1)]
    return _render_vertical_flow_svg(
        rows[:5],
        caption=spec.annotations[0] if spec.annotations else "流程示意图",
        label_prefix="步",
    )


def _render_mistake_card(spec: FigureSpec) -> str:
    rows = [item.text or item.label for item in spec.elements if item.text or item.label]
    rows.extend(spec.annotations)
    rows = _clean_list(rows, limit=5, item_limit=180)
    if not rows:
        return ""
    elements = [
        FigureElement(kind="step", label=f"{index}", text=text)
        for index, text in enumerate(rows, start=1)
    ]
    return _render_vertical_flow_svg(elements, caption="易错辨析图", label_prefix="点")


def _render_vertical_flow_svg(
    elements: list[FigureElement],
    *,
    caption: str,
    label_prefix: str,
) -> str:
    items = [item for item in elements if item.text or item.label]
    if not items:
        return ""
    top = 34
    row_gap = 56
    box_height = 36
    markup: list[str] = []
    for index, item in enumerate(items[:5], start=1):
        y = top + (index - 1) * row_gap
        label = item.label or f"{label_prefix}{index}"
        text = item.text or item.label
        markup.append(
            f'<rect x="58" y="{y}" width="504" height="{box_height}" rx="4" fill="#fff" stroke="#111" stroke-width="1.8"/>'
        )
        markup.append(
            f'<rect x="76" y="{y + 6}" width="96" height="24" rx="12" fill="#eee" stroke="#111" stroke-width="1.4"/>'
        )
        markup.append(
            _render_svg_text(
                x=124,
                y=y + box_height / 2 + 5,
                text=label,
                font_size=14,
                limit=6,
                text_anchor="middle",
            )
        )
        markup.append(
            _render_svg_text(
                x=188,
                y=y + box_height / 2 + 6,
                text=text,
                font_size=17,
                limit=34,
            )
        )
        if index < min(len(items), 5):
            x = 310
            y1 = y + box_height + 5
            y2 = y + row_gap - 8
            markup.append(
                f'<line x1="{x}" y1="{y1:.1f}" x2="{x}" y2="{y2:.1f}" stroke="#111" stroke-width="1.7" marker-end="url(#arrow)"/>'
            )
    return _svg_shell("".join(markup), caption=caption)


def _render_concept_map(spec: FigureSpec) -> str:
    labels = [item.label or item.text for item in spec.elements if item.kind in {"label", "step", "relation", "callout"} and (item.label or item.text)]
    labels.extend(spec.annotations)
    labels = _clean_list(labels, limit=6, item_limit=60)
    if not labels:
        return ""
    center_x, center_y = 310.0, 170.0
    radius_x, radius_y = 210.0, 105.0
    nodes: list[tuple[float, float, str]] = []
    for index, label in enumerate(labels):
        angle = (2 * math.pi * index / max(1, len(labels))) - math.pi / 2
        nodes.append((center_x + math.cos(angle) * radius_x, center_y + math.sin(angle) * radius_y, label))
    node_markup = []
    edge_markup = []
    for index, (x, y, label) in enumerate(nodes):
        if index > 0:
            edge_markup.append(f'<line x1="{center_x:.1f}" y1="{center_y:.1f}" x2="{x:.1f}" y2="{y:.1f}" stroke="#111" stroke-width="1.8" marker-end="url(#arrow)"/>')
        node_markup.append(f'<rect x="{x-58:.1f}" y="{y-18:.1f}" width="116" height="36" fill="#fff" stroke="#111" stroke-width="1.6"/>')
        node_markup.append(f'<text x="{x:.1f}" y="{y+6:.1f}" text-anchor="middle" font-size="17">{_svg_escape(label)}</text>')
    center_label = _svg_escape(spec.title or "核心")
    return _svg_shell(f"""
      {''.join(edge_markup)}
      <rect x="250" y="148" width="120" height="44" fill="#eee" stroke="#111" stroke-width="1.8"/>
      <text x="310" y="176" text-anchor="middle" font-size="18" font-weight="700">{center_label}</text>
      {''.join(node_markup)}
    """, caption="概念关系图")


def _render_problem_diagram(spec: FigureSpec) -> str:
    elements, _ = _auto_layout_relation_graph(spec.elements[:18])
    points = [item for item in elements if item.kind == "point" and (item.id or item.label)]
    element_by_id = _diagram_element_map(elements)
    label_like_kinds = {"label", "callout", "relation", "formula", "step"}
    primitives = [item for item in elements if item.kind in {"axis", "curve", "line", "vector", "shape", *label_like_kinds}]
    if not _has_problem_diagram_geometry(elements):
        return _render_concept_map(spec)

    markup: list[str] = []
    for item in primitives:
        if item.kind == "axis":
            x1, y1 = _map_point(item.x, item.y)
            x2, y2 = _map_point(item.x2, item.y2)
            markup.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="#111" stroke-width="1.8" marker-end="url(#arrow)"/>')
            if item.label:
                markup.append(f'<text x="{x2 + 8:.1f}" y="{y2 + 5:.1f}" font-size="18" font-style="italic">{_svg_escape(item.label)}</text>')
        elif item.kind == "curve":
            x1, y1 = _map_point(item.x, item.y)
            x2, y2 = _map_point(item.x2, item.y2)
            c1x = x1 + (x2 - x1) * 0.28
            c2x = x1 + (x2 - x1) * 0.68
            c1y = y1 + 18
            c2y = y2 - 52
            stroke = "#111" if item.style != "muted" else "#777"
            markup.append(f'<path d="M{x1:.1f},{y1:.1f} C{c1x:.1f},{c1y:.1f} {c2x:.1f},{c2y:.1f} {x2:.1f},{y2:.1f}" fill="none" stroke="{stroke}" stroke-width="2.4"/>')
            if item.label:
                markup.append(f'<text x="{x2 - 32:.1f}" y="{y2 - 8:.1f}" font-size="18" font-style="italic">{_svg_escape(item.label)}</text>')
        elif item.kind in {"line", "vector"}:
            x1, y1, x2, y2 = _diagram_line_endpoints(item, element_by_id)
            dash = ' stroke-dasharray="6 5"' if item.style in {"dashed", "muted"} else ""
            marker = ' marker-end="url(#arrow)"' if item.kind == "vector" else ""
            stroke = "#777" if item.style in {"dashed", "muted"} else "#111"
            markup.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{stroke}" stroke-width="2.2"{dash}{marker}/>')
            label = item.label or item.text
            if label:
                lx, ly = _edge_label_anchor(
                    x1,
                    y1,
                    x2,
                    y2,
                    prefer_above=bool(item.from_id and item.to_id),
                )
                markup.append(_render_edge_label(label, lx, ly))
        elif item.kind == "shape":
            markup.append(_render_shape_primitive(item))
        elif item.kind in label_like_kinds and (item.text or item.label):
            x, y = _map_point(item.x, item.y)
            markup.append(f'<text x="{x:.1f}" y="{y:.1f}" font-size="19">{_svg_escape(item.text or item.label)}</text>')

    for point in points:
        x, y = _map_point(point.x, point.y)
        label = point.label or point.id
        markup.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.8" fill="#111"/>')
        markup.append(f'<text x="{x+8:.1f}" y="{y-8:.1f}" font-size="21" font-style="italic">{_svg_escape(label)}</text>')
    return _svg_shell("".join(markup), caption=spec.annotations[0] if spec.annotations else "题图示意")


def _render_shape_primitive(item: FigureElement) -> str:
    x, y = _map_point(item.x, item.y)
    stroke = "#777" if item.style in {"dashed", "muted"} else "#111"
    dash = ' stroke-dasharray="6 5"' if item.style in {"dashed", "muted"} else ""
    fill = "#f4f4f4" if item.shape_type == "region" or item.style == "highlight" else "none"
    fill_opacity = ' fill-opacity="0.45"' if fill != "none" else ""

    label_markup = ""
    if item.label and item.shape_type not in {"angle", "arc"}:
        lx, ly = _shape_label_anchor(item)
        label_markup = (
            f'<text x="{lx:.1f}" y="{ly + 6:.1f}" text-anchor="middle" '
            f'font-size="18">{_svg_escape_short(item.label, limit=12)}</text>'
        )

    if item.shape_type == "circle":
        r = _shape_radius(item)
        return (
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" fill="{fill}"{fill_opacity} '
            f'stroke="{stroke}" stroke-width="1.8"{dash}/>{label_markup}'
        )
    if item.shape_type == "rectangle":
        rx = _shape_rx(item)
        ry = _shape_ry(item)
        return (
            f'<rect x="{x-rx:.1f}" y="{y-ry:.1f}" width="{rx*2:.1f}" height="{ry*2:.1f}" '
            f'fill="{fill}"{fill_opacity} stroke="{stroke}" stroke-width="1.8"{dash}/>{label_markup}'
        )
    if item.shape_type in {"triangle", "polygon", "region"}:
        points = _shape_points(item)
        if len(points) < 3:
            points = _default_triangle_points(item)
        mapped = " ".join(f"{px:.1f},{py:.1f}" for px, py in (_map_point(px, py) for px, py in points[:8]))
        return (
            f'<polygon points="{mapped}" fill="{fill}"{fill_opacity} '
            f'stroke="{stroke}" stroke-width="1.8"{dash}/>{label_markup}'
        )
    if item.shape_type in {"angle", "arc"}:
        return _render_arc_shape(item)

    rx = _shape_rx(item)
    ry = _shape_ry(item)
    return (
        f'<ellipse cx="{x:.1f}" cy="{y:.1f}" rx="{rx:.1f}" ry="{ry:.1f}" fill="{fill}"{fill_opacity} '
        f'stroke="{stroke}" stroke-width="1.8"{dash}/>{label_markup}'
    )


def _render_edge_label(label: str, x: float, y: float) -> str:
    width = _text_width(label, font_size=20)
    return (
        f'<rect x="{x - width / 2 - 3:.1f}" y="{y - 20:.1f}" width="{width + 6:.1f}" '
        f'height="26.0" rx="4.0" fill="#fff" fill-opacity="0.9"/>'
        f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="middle" font-size="20" '
        f'font-style="italic">{_svg_escape(label)}</text>'
    )


def _edge_label_anchor(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    *,
    prefer_above: bool,
) -> tuple[float, float]:
    if prefer_above:
        return (x1 + x2) / 2 + 6, (y1 + y2) / 2 - 6
    dx = x2 - x1
    dy = y2 - y1
    length = math.hypot(dx, dy)
    if length < 0.01:
        return (x1 + x2) / 2 + 6, (y1 + y2) / 2 - 6
    nx = -dy / length
    ny = dx / length
    if ny < 0:
        nx = -nx
        ny = -ny
    offset = 28.0
    return (x1 + x2) / 2 + nx * offset, (y1 + y2) / 2 + ny * offset


def _shape_points(item: FigureElement) -> list[list[float]]:
    return item.points[:8]


def _has_teaching_relation(elements: list[FigureElement]) -> bool:
    """Reject decorative node piles that do not encode a learnable relation."""

    for item in elements[:18]:
        if item.kind in {"axis", "curve", "line", "vector"}:
            return True
        if item.kind == "shape" and item.shape_type in {"angle", "arc", "region"}:
            return True
        if item.kind == "shape" and len(item.points) >= 3:
            return True
    labeled_shapes = [
        item
        for item in elements[:18]
        if item.kind == "shape"
        and item.shape_type in {"rectangle", "circle", "ellipse", "triangle", "polygon"}
        and item.label
    ]
    return len(labeled_shapes) >= 3 and any(
        item.kind in {"label", "callout"} and (item.text or item.label)
        for item in elements[:18]
    )


def _auto_layout_relation_graph(elements: list[FigureElement]) -> tuple[list[FigureElement], bool]:
    """Lay out model-planned relation graphs from semantic edges.

    LLMs are useful at deciding which entities are connected, but their raw
    coordinates are brittle. When a diagram is a pure shape-and-edge graph, use
    the semantic from_id/to_id links as the source of truth and compute a clean
    layered layout before SVG rendering.
    """

    items = list(elements[:18])
    if any(item.kind in {"axis", "curve", "point"} for item in items):
        return items, False
    if any(item.kind == "shape" and item.shape_type in {"angle", "arc", "polygon", "region"} for item in items):
        return items, False

    shapes = [
        item
        for item in items
        if item.kind == "shape" and item.shape_type in {"rectangle", "ellipse", "circle", "triangle"}
    ]
    if not 2 <= len(shapes) <= 8:
        return items, False

    shape_keys: dict[str, str] = {}
    node_by_key: dict[str, FigureElement] = {}
    node_order: list[str] = []
    for index, shape in enumerate(shapes, start=1):
        key = shape.id or shape.label or f"node_{index}"
        if key in node_by_key:
            key = f"{key}_{index}"
        node_by_key[key] = shape
        node_order.append(key)
        for alias in (shape.id, shape.label, key):
            if alias:
                shape_keys.setdefault(alias, key)
                shape_keys.setdefault(alias.casefold(), key)

    def resolve(ref: str) -> str:
        return shape_keys.get(ref) or shape_keys.get(ref.casefold(), "")

    edges: list[tuple[FigureElement, str, str]] = []
    for item in items:
        if item.kind not in {"line", "vector"} or not item.from_id or not item.to_id:
            continue
        start = resolve(item.from_id)
        end = resolve(item.to_id)
        if start and end and start != end:
            edges.append((item, start, end))
    if not edges:
        return items, False

    if len(edges) > 10:
        return items, False

    levels = _relation_graph_levels(node_order, [(start, end) for _, start, end in edges])
    placed_shapes = _place_relation_graph_shapes(node_by_key, node_order, levels)
    updated: list[FigureElement] = []
    shape_index = 0
    edge_ids = {id(edge) for edge, _, _ in edges}
    for item in items:
        if item.kind == "shape" and shape_index < len(placed_shapes):
            updated.append(placed_shapes[shape_index])
            shape_index += 1
        elif id(item) in edge_ids:
            updated.append(
                item.model_copy(
                    update={
                        "x": 50,
                        "y": 50,
                        "x2": 50,
                        "y2": 50,
                    }
                )
            )
        else:
            updated.append(item)
    return updated, True


def _relation_graph_levels(node_order: list[str], edges: list[tuple[str, str]]) -> dict[str, int]:
    indegree = {node: 0 for node in node_order}
    adjacency = {node: [] for node in node_order}
    for start, end in edges:
        adjacency.setdefault(start, []).append(end)
        indegree[end] = indegree.get(end, 0) + 1
        indegree.setdefault(start, indegree.get(start, 0))

    roots = [node for node in node_order if indegree.get(node, 0) == 0]
    if not roots and node_order:
        roots = [node_order[0]]
    levels = {node: 0 for node in roots}
    queue = list(roots)
    while queue:
        current = queue.pop(0)
        for child in adjacency.get(current, []):
            next_level = levels[current] + 1
            if next_level > levels.get(child, -1):
                levels[child] = next_level
                queue.append(child)

    for index, node in enumerate(node_order):
        levels.setdefault(node, index)
    if len(set(levels.values())) == 1 and len(node_order) > 1:
        levels = {node: index for index, node in enumerate(node_order)}
    return levels


def _place_relation_graph_shapes(
    node_by_key: dict[str, FigureElement],
    node_order: list[str],
    levels: dict[str, int],
) -> list[FigureElement]:
    grouped: dict[int, list[str]] = {}
    for node in node_order:
        grouped.setdefault(levels.get(node, 0), []).append(node)
    ordered_levels = sorted(grouped)
    max_index = max(1, len(ordered_levels) - 1)
    x_by_level = {
        level: 18 + (64 * index / max_index if max_index else 0)
        for index, level in enumerate(ordered_levels)
    }

    placed_by_key: dict[str, FigureElement] = {}
    for level in ordered_levels:
        nodes = grouped[level]
        spacing = 0.0 if len(nodes) == 1 else min(23.0, 62.0 / max(1, len(nodes) - 1))
        for index, node in enumerate(nodes):
            shape = node_by_key[node]
            label = shape.label or shape.id or node
            y = 50 + (index - (len(nodes) - 1) / 2) * spacing
            shape_type = shape.shape_type
            if shape_type in {"circle", "ellipse"} and _visual_text_units(label) > 3.2:
                shape_type = "rectangle"
            rx = max(shape.rx, min(18.0, max(8.0, 4.8 + _visual_text_units(label) * 0.75)))
            ry = max(shape.ry, 7.0)
            placed_by_key[node] = shape.model_copy(
                update={
                    "x": max(12.0, min(88.0, x_by_level[level])),
                    "y": max(18.0, min(82.0, y)),
                    "rx": rx,
                    "ry": ry,
                    "shape_type": shape_type,
                }
            )
    return [placed_by_key[node] for node in node_order]


def _diagram_element_map(elements: list[FigureElement]) -> dict[str, FigureElement]:
    refs: dict[str, FigureElement] = {}
    for item in elements[:18]:
        keys = [key for key in (item.id, item.label) if key]
        for key in keys:
            refs.setdefault(key, item)
    return refs


def _diagram_anchor(item: FigureElement | None, *, fallback: tuple[float, float]) -> tuple[float, float]:
    if item is None:
        return fallback
    if item.kind == "shape" and item.shape_type in {"triangle", "polygon", "region"}:
        return _shape_label_anchor(item)
    return _map_point(item.x, item.y)


def _diagram_line_endpoints(
    item: FigureElement,
    element_by_id: dict[str, FigureElement],
) -> tuple[float, float, float, float]:
    fallback_start = _map_point(item.x, item.y)
    fallback_end = _map_point(item.x2, item.y2)
    start_item = element_by_id.get(item.from_id)
    end_item = element_by_id.get(item.to_id)
    start = _diagram_anchor(start_item, fallback=fallback_start)
    end = _diagram_anchor(end_item, fallback=fallback_end)
    if start_item is not None:
        start = _shape_boundary_anchor(start_item, toward=end)
    if end_item is not None:
        end = _shape_boundary_anchor(end_item, toward=start)
    return start[0], start[1], end[0], end[1]


def _shape_boundary_anchor(item: FigureElement, *, toward: tuple[float, float]) -> tuple[float, float]:
    center = _diagram_anchor(item, fallback=_map_point(item.x, item.y))
    if item.kind != "shape":
        return center
    dx = toward[0] - center[0]
    dy = toward[1] - center[1]
    if abs(dx) < 0.01 and abs(dy) < 0.01:
        return center
    if item.shape_type == "circle":
        radius = _shape_radius(item)
        length = math.hypot(dx, dy) or 1.0
        return center[0] + dx / length * radius, center[1] + dy / length * radius
    if item.shape_type in {"rectangle", "ellipse"}:
        rx = _shape_rx(item)
        ry = _shape_ry(item)
        scale_candidates = []
        if abs(dx) >= 0.01:
            scale_candidates.append(rx / abs(dx))
        if abs(dy) >= 0.01:
            scale_candidates.append(ry / abs(dy))
        scale = min(scale_candidates or [0.0])
        return center[0] + dx * scale, center[1] + dy * scale
    if item.shape_type in {"triangle", "polygon", "region"}:
        bbox = _shape_bbox(item)
        rx = max(1.0, (bbox[2] - bbox[0]) / 2)
        ry = max(1.0, (bbox[3] - bbox[1]) / 2)
        scale_candidates = []
        if abs(dx) >= 0.01:
            scale_candidates.append(rx / abs(dx))
        if abs(dy) >= 0.01:
            scale_candidates.append(ry / abs(dy))
        scale = min(scale_candidates or [0.0])
        return center[0] + dx * scale, center[1] + dy * scale
    return center


def _default_triangle_points(item: FigureElement) -> list[list[float]]:
    radius = max(8.0, item.r)
    return [
        [_unit_coord(item.x), _unit_coord(item.y - radius)],
        [_unit_coord(item.x - radius * 1.15), _unit_coord(item.y + radius * 0.85)],
        [_unit_coord(item.x + radius * 1.15), _unit_coord(item.y + radius * 0.85)],
    ]


def _shape_radius(item: FigureElement) -> float:
    return max(8.0, (item.r or 8.0) * 2.2)


def _shape_rx(item: FigureElement) -> float:
    if item.rx:
        return max(8.0, item.rx * 5.16)
    return max(14.0, (item.r or 8.0) * 2.8)


def _shape_ry(item: FigureElement) -> float:
    if item.ry:
        return max(8.0, item.ry * 2.46)
    return max(10.0, (item.r or 8.0) * 1.8)


def _shape_label_anchor(item: FigureElement) -> tuple[float, float]:
    if item.shape_type in {"triangle", "polygon", "region"}:
        points = _shape_points(item)
        if len(points) < 3:
            points = _default_triangle_points(item)
        mapped = [_map_point(px, py) for px, py in points[:8]]
        return (
            sum(point[0] for point in mapped) / len(mapped),
            sum(point[1] for point in mapped) / len(mapped),
        )
    return _map_point(item.x, item.y)


def _render_arc_shape(item: FigureElement) -> str:
    center_x, center_y = _map_point(item.x, item.y)
    radius = max(10.0, (item.r or 8.0) * 2.0)
    start = math.radians(item.start_angle)
    end = math.radians(item.end_angle)
    x1 = center_x + math.cos(start) * radius
    y1 = center_y - math.sin(start) * radius
    x2 = center_x + math.cos(end) * radius
    y2 = center_y - math.sin(end) * radius
    delta = abs((item.end_angle - item.start_angle) % 360)
    large_arc = 1 if delta > 180 else 0
    sweep = 0 if item.end_angle < item.start_angle else 1
    stroke = "#777" if item.style in {"dashed", "muted"} else "#111"
    dash = ' stroke-dasharray="5 4"' if item.style in {"dashed", "muted"} else ""
    label = item.label or item.text
    label_markup = ""
    if label:
        mid = math.radians((item.start_angle + item.end_angle) / 2)
        lx = center_x + math.cos(mid) * (radius + 14)
        ly = center_y - math.sin(mid) * (radius + 14)
        label_markup = f'<text x="{lx:.1f}" y="{ly:.1f}" font-size="18" text-anchor="middle">{_svg_escape(label)}</text>'
    return (
        f'<path d="M{x1:.1f},{y1:.1f} A{radius:.1f},{radius:.1f} 0 {large_arc} {sweep} {x2:.1f},{y2:.1f}" '
        f'fill="none" stroke="{stroke}" stroke-width="1.8"{dash}/>{label_markup}'
    )


def _problem_diagram_geometry_boxes(spec: FigureSpec) -> list[tuple[float, float, float, float]]:
    element_by_id = _diagram_element_map(spec.elements)
    boxes: list[tuple[float, float, float, float]] = []
    for item in spec.elements[:18]:
        if item.kind == "axis":
            boxes.append(_line_bbox(_map_point(item.x, item.y), _map_point(item.x2, item.y2), pad=6))
        elif item.kind == "curve":
            x1, y1 = _map_point(item.x, item.y)
            x2, y2 = _map_point(item.x2, item.y2)
            c1x = x1 + (x2 - x1) * 0.28
            c2x = x1 + (x2 - x1) * 0.68
            boxes.append(_points_bbox([(x1, y1), (c1x, y1 + 18), (c2x, y2 - 52), (x2, y2)], pad=8))
        elif item.kind in {"line", "vector"}:
            x1, y1, x2, y2 = _diagram_line_endpoints(item, element_by_id)
            p1 = (x1, y1)
            p2 = (x2, y2)
            boxes.append(_line_bbox(p1, p2, pad=6))
        elif item.kind == "shape":
            boxes.append(_shape_bbox(item))
        elif item.kind in {"label", "callout", "relation", "formula", "step"} and (item.text or item.label):
            boxes.append(_text_bbox_left(*_map_point(item.x, item.y), item.text or item.label, font_size=19))
        elif item.kind == "point" and (item.id or item.label):
            x, y = _map_point(item.x, item.y)
            boxes.append((x - 5, y - 5, x + 5, y + 5))
    return boxes


def _problem_diagram_label_boxes(spec: FigureSpec) -> list[tuple[float, float, float, float, str]]:
    element_by_id = _diagram_element_map(spec.elements)
    boxes: list[tuple[float, float, float, float, str]] = []
    for item in spec.elements[:18]:
        label = item.label or item.text
        if not label:
            continue
        if item.kind == "axis":
            x2, y2 = _map_point(item.x2, item.y2)
            boxes.append((*_text_bbox_left(x2 + 8, y2 + 5, label, font_size=18), label))
        elif item.kind == "curve":
            x2, y2 = _map_point(item.x2, item.y2)
            boxes.append((*_text_bbox_left(x2 - 32, y2 - 8, label, font_size=18), label))
        elif item.kind in {"line", "vector"}:
            x1, y1, x2, y2 = _diagram_line_endpoints(item, element_by_id)
            lx, ly = _edge_label_anchor(
                x1,
                y1,
                x2,
                y2,
                prefer_above=bool(item.from_id and item.to_id),
            )
            boxes.append((*_text_bbox_center(lx, ly, label, font_size=20), label))
        elif item.kind == "shape" and item.shape_type not in {"angle", "arc"}:
            x, y = _shape_label_anchor(item)
            boxes.append((*_text_bbox_center(x, y + 6, label, font_size=18), label))
        elif item.kind == "shape" and item.shape_type in {"angle", "arc"}:
            x, y = _arc_label_anchor(item)
            boxes.append((*_text_bbox_center(x, y, label, font_size=18), label))
        elif item.kind in {"label", "callout", "relation", "formula", "step"}:
            x, y = _map_point(item.x, item.y)
            boxes.append((*_text_bbox_left(x, y, label, font_size=19), label))
        elif item.kind == "point":
            x, y = _map_point(item.x, item.y)
            boxes.append((*_text_bbox_left(x + 8, y - 8, label, font_size=21), label))
    return boxes


def _visual_text_units(text: str) -> float:
    units = 0.0
    for char in str(text or ""):
        units += 1.0 if ord(char) > 127 else 0.58
    return units


def _text_width(text: str, *, font_size: float) -> float:
    return max(16.0, min(150.0, _visual_text_units(text) * font_size * 0.62 + 10))


def _text_bbox_left(x: float, y: float, text: str, *, font_size: float) -> tuple[float, float, float, float]:
    width = _text_width(text, font_size=font_size)
    return x, y - font_size, x + width, y + 6


def _text_bbox_center(x: float, y: float, text: str, *, font_size: float) -> tuple[float, float, float, float]:
    width = _text_width(text, font_size=font_size)
    return x - width / 2, y - font_size, x + width / 2, y + 6


def _line_bbox(
    p1: tuple[float, float],
    p2: tuple[float, float],
    *,
    pad: float,
) -> tuple[float, float, float, float]:
    return (
        min(p1[0], p2[0]) - pad,
        min(p1[1], p2[1]) - pad,
        max(p1[0], p2[0]) + pad,
        max(p1[1], p2[1]) + pad,
    )


def _points_bbox(points: list[tuple[float, float]], *, pad: float) -> tuple[float, float, float, float]:
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad


def _shape_bbox(item: FigureElement) -> tuple[float, float, float, float]:
    x, y = _map_point(item.x, item.y)
    if item.shape_type == "circle":
        radius = _shape_radius(item)
        return x - radius, y - radius, x + radius, y + radius
    if item.shape_type == "rectangle":
        rx = _shape_rx(item)
        ry = _shape_ry(item)
        return x - rx, y - ry, x + rx, y + ry
    if item.shape_type in {"triangle", "polygon", "region"}:
        points = _shape_points(item)
        if len(points) < 3:
            points = _default_triangle_points(item)
        return _points_bbox([_map_point(px, py) for px, py in points[:8]], pad=4)
    if item.shape_type in {"angle", "arc"}:
        radius = max(10.0, (item.r or 8.0) * 2.0) + 18
        return x - radius, y - radius, x + radius, y + radius
    rx = _shape_rx(item)
    ry = _shape_ry(item)
    return x - rx, y - ry, x + rx, y + ry


def _arc_label_anchor(item: FigureElement) -> tuple[float, float]:
    center_x, center_y = _map_point(item.x, item.y)
    radius = max(10.0, (item.r or 8.0) * 2.0)
    mid = math.radians((item.start_angle + item.end_angle) / 2)
    return center_x + math.cos(mid) * (radius + 14), center_y - math.sin(mid) * (radius + 14)


def _merge_bboxes(boxes: list[tuple[float, float, float, float]]) -> tuple[float, float, float, float]:
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )


def _bbox_area(box: tuple[float, float, float, float] | tuple[float, float, float, float, str]) -> float:
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def _bbox_overlap_ratio(
    a: tuple[float, float, float, float, str],
    b: tuple[float, float, float, float, str],
) -> float:
    x1 = max(a[0], b[0])
    y1 = max(a[1], b[1])
    x2 = min(a[2], b[2])
    y2 = min(a[3], b[3])
    overlap = _bbox_area((x1, y1, x2, y2))
    if overlap <= 0:
        return 0.0
    return overlap / max(1.0, min(_bbox_area(a), _bbox_area(b)))


def _bbox_outside_canvas(box: tuple[float, float, float, float, str]) -> bool:
    return box[0] < 12 or box[1] < 12 or box[2] > 608 or box[3] > 318


def _map_point(x: float, y: float) -> tuple[float, float]:
    return 52 + _unit_coord(x) * 5.16, 34 + _unit_coord(y) * 2.46


def _svg_shell(inner: str, *, caption: str) -> str:
    return f"""
<svg viewBox="0 0 620 330" role="img" aria-label="{_html_escape(caption)}">
  <defs>
    <marker id="arrow" markerWidth="10" markerHeight="10" refX="8" refY="5" orient="auto" markerUnits="strokeWidth">
      <path d="M1,1 L9,5 L1,9" fill="none" stroke="#111" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>
    </marker>
  </defs>
  <rect x="8" y="8" width="604" height="314" fill="#fff"/>
  {inner}
</svg>
"""


__all__ = [
    "FigureCandidate",
    "FigureElement",
    "FigureSpec",
    "FigureType",
    "RenderedFigure",
    "assess_static_figure_layout",
    "build_fallback_figure_spec",
    "is_renderable_static_figure",
    "normalize_figure_spec",
    "render_figure_spec_html",
]
