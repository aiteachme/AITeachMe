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


def is_renderable_problem_diagram(spec: FigureSpec) -> bool:
    """Return whether a spec contains actual visual geometry."""

    return spec.type == "problem_diagram" and _has_problem_diagram_geometry(spec.elements)


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
    source_refs = [
        ref for ref in spec.source_refs
        if ref and _compact(ref) in _compact(context)
    ]
    if not source_refs:
        source_refs = _plain_context_lines(context, limit=3)
        report["source_ref_replacements"] = 1
    if not source_refs:
        report["warnings"].append("empty_source_refs")

    normalized = spec.model_copy(
        update={
            "title": _clean_text(title, limit=120),
            "type": figure_type,
            "summary": spec.summary or (source_refs[0] if source_refs else ""),
            "source_refs": source_refs,
            "annotations": spec.annotations[:6],
            "emphasis": spec.emphasis[:4],
            "elements": elements,
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
            annotations=lines[:2],
            source_refs=lines[:3],
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
      font-family: "Times New Roman", "SimSun", "宋体", serif;
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
            f'<text x="124" y="{y + box_height / 2 + 5:.1f}" text-anchor="middle" font-size="14">{_svg_escape_short(label, limit=6)}</text>'
        )
        markup.append(
            f'<text x="188" y="{y + box_height / 2 + 6:.1f}" font-size="17">{_svg_escape_short(text, limit=34)}</text>'
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
        labels = ["核心概念", "条件", "结论"]
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
    points = [item for item in spec.elements if item.kind == "point" and (item.id or item.label)]
    point_by_id = {item.id or item.label: item for item in points}
    primitives = [item for item in spec.elements if item.kind in {"axis", "curve", "line", "vector", "shape", "label", "callout"}]
    if not _has_problem_diagram_geometry(spec.elements):
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
            start = point_by_id.get(item.from_id)
            end = point_by_id.get(item.to_id)
            x1, y1 = _map_point(start.x, start.y) if start else _map_point(item.x, item.y)
            x2, y2 = _map_point(end.x, end.y) if end else _map_point(item.x2, item.y2)
            dash = ' stroke-dasharray="6 5"' if item.style in {"dashed", "muted"} else ""
            marker = ' marker-end="url(#arrow)"' if item.kind == "vector" else ""
            stroke = "#777" if item.style in {"dashed", "muted"} else "#111"
            markup.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{stroke}" stroke-width="2.2"{dash}{marker}/>')
            label = item.label or item.text
            if label:
                lx, ly = (x1 + x2) / 2 + 6, (y1 + y2) / 2 - 6
                markup.append(f'<text x="{lx:.1f}" y="{ly:.1f}" font-size="20" font-style="italic">{_svg_escape(label)}</text>')
        elif item.kind == "shape":
            markup.append(_render_shape_primitive(item))
        elif item.kind in {"label", "callout"} and (item.text or item.label):
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
        label_markup = f'<text x="{x:.1f}" y="{y - _shape_label_offset(item):.1f}" text-anchor="middle" font-size="18">{_svg_escape(item.label)}</text>'

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


def _shape_points(item: FigureElement) -> list[list[float]]:
    return item.points[:8]


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


def _shape_label_offset(item: FigureElement) -> float:
    if item.shape_type in {"triangle", "polygon", "region"}:
        return _shape_ry(item) + 12
    if item.shape_type == "circle":
        return _shape_radius(item) + 10
    return _shape_ry(item) + 10


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
    "build_fallback_figure_spec",
    "normalize_figure_spec",
    "render_figure_spec_html",
]
