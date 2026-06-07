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

ElementKind = Literal[
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


def _svg_escape(value: Any) -> str:
    return html.escape(_clean_text(value, limit=80), quote=True)


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

    @field_validator("r", mode="before")
    @classmethod
    def _radius(cls, value: Any) -> float:
        return _positive_number(value)

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


def normalize_figure_spec(
    spec: FigureSpec,
    *,
    fallback_title: str,
    context: str,
) -> tuple[FigureSpec, dict[str, Any]]:
    """Constrain a model spec to facts traceable to the current section."""

    report: dict[str, Any] = {"source_ref_replacements": 0, "warnings": []}
    title = spec.title or fallback_title
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
            "summary": spec.summary or (source_refs[0] if source_refs else ""),
            "source_refs": source_refs,
            "annotations": spec.annotations[:6],
            "emphasis": spec.emphasis[:4],
            "elements": spec.elements[:18],
        }
    )
    if not normalized.elements:
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
            FigureElement(kind="table_row", cells=[f"要点 {index}", line])
            for index, line in enumerate(lines[:4], start=1)
        ]
        return FigureSpec(type=figure_type, title=title, summary=goal or (lines[0] if lines else ""), elements=rows, source_refs=lines[:3])
    if figure_type == "formula_derivation":
        rows = [FigureElement(kind="formula", label=f"({index})", text=line) for index, line in enumerate(lines[:4], start=1)]
        return FigureSpec(type=figure_type, title=title, summary=goal or "按步骤理解公式关系。", elements=rows, source_refs=lines[:3])
    if figure_type == "problem_diagram":
        return FigureSpec(
            type=figure_type,
            title=title,
            summary=goal or (lines[0] if lines else ""),
            elements=[
                FigureElement(kind="point", id="start", label="条件", x=18, y=72),
                FigureElement(kind="point", id="middle", label="关系", x=48, y=40),
                FigureElement(kind="point", id="end", label="结论", x=78, y=72),
                FigureElement(kind="line", from_id="start", to_id="middle"),
                FigureElement(kind="line", from_id="middle", to_id="end"),
                FigureElement(kind="vector", from_id="start", to_id="end", label="推得"),
            ],
            annotations=lines[:2],
            source_refs=lines[:3],
        )
    rows = [FigureElement(kind="step", label=str(index), text=line) for index, line in enumerate(lines[:5], start=1)]
    return FigureSpec(type=figure_type, title=title, summary=goal or (lines[0] if lines else ""), elements=rows, source_refs=lines[:3])


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "")).casefold()


def render_figure_spec_html(spec: FigureSpec, *, title: str) -> str:
    """Render a spec as a single-file HTML lecture-note figure."""

    figure_title = spec.title or title
    body = _render_body(spec)
    source_line = _render_source_line(spec)
    emphasis = _render_emphasis(spec)
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
      width: min(760px, calc(100vw - 20px));
      margin: 14px auto;
      padding: 8px 2px 16px;
      background: #fff;
    }}
    .atm-topic {{
      display: inline;
      padding: 2px 4px;
      background: #18d8d4;
      color: #000;
      font-size: 20px;
      line-height: 1.75;
    }}
    .atm-summary {{
      margin: 16px 0 10px;
      font-size: 19px;
    }}
    .atm-figure-main {{
      margin: 8px auto 4px;
      width: min(640px, 100%);
    }}
    .atm-caption {{
      margin: 6px 0 12px;
      text-align: center;
      font-size: 18px;
    }}
    .atm-note {{
      width: min(620px, 100%);
      margin: 10px auto 0;
      border: 1px solid #222;
      background: #eee;
      padding: 8px 12px;
      font-size: 18px;
    }}
    .atm-source {{
      width: min(620px, 100%);
      margin: 8px auto 0;
      color: #444;
      font-size: 15px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      margin: 10px auto;
      font-size: 18px;
    }}
    th, td {{
      border: 1px solid #222;
      padding: 7px 9px;
      vertical-align: top;
      text-align: left;
    }}
    th {{ background: #eee; font-weight: 700; }}
    svg {{ display: block; width: 100%; height: auto; }}
    @media (max-width: 520px) {{
      .atm-topic, .atm-summary, .atm-caption, .atm-note, table {{ font-size: 16px; }}
      .atm-source {{ font-size: 13px; }}
    }}
  </style>
</head>
<body>
  <main class="atm-figure">
    <p><span class="atm-topic">{_html_escape(figure_title)}</span></p>
    {_render_summary(spec)}
    <div class="atm-figure-main">{body}</div>
    {emphasis}
    {source_line}
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
        return _render_comparison_table(spec)
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
    items = "".join(
        f"<tr><td>{_html_escape(item.label or str(index))}</td><td>{_html_escape(item.text or item.label, limit=220)}</td></tr>"
        for index, item in enumerate(rows[:8], start=1)
    )
    return f"<table><tbody>{items}</tbody></table>"


def _render_process_steps(spec: FigureSpec) -> str:
    rows = [item for item in spec.elements if item.kind in {"step", "formula", "label", "callout"} and (item.text or item.label)]
    if not rows:
        rows = [FigureElement(kind="step", label=str(index), text=text) for index, text in enumerate(spec.annotations[:5], start=1)]
    items = "".join(
        f"<tr><td>{index}</td><td>{_html_escape(item.text or item.label, limit=220)}</td></tr>"
        for index, item in enumerate(rows[:7], start=1)
    )
    return f"<table><tbody>{items}</tbody></table>"


def _render_mistake_card(spec: FigureSpec) -> str:
    rows = [item.text or item.label for item in spec.elements if item.text or item.label]
    rows.extend(spec.annotations)
    rows = _clean_list(rows, limit=5, item_limit=180)
    if not rows:
        return ""
    content = "<br/>".join(f"{index}. {_html_escape(text, limit=180)}" for index, text in enumerate(rows, start=1))
    return f'<div class="atm-note">{content}</div>'


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
    primitives = [item for item in spec.elements if item.kind in {"line", "vector", "shape", "label", "callout"}]
    if not points or not any(item.kind in {"line", "vector", "shape"} for item in primitives):
        return _render_concept_map(spec)

    markup: list[str] = []
    for item in primitives:
        if item.kind in {"line", "vector"}:
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
            x, y = _map_point(item.x, item.y)
            r = max(8.0, item.r * 2.2)
            markup.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" fill="none" stroke="#111" stroke-width="1.8"/>')
        elif item.kind in {"label", "callout"} and (item.text or item.label):
            x, y = _map_point(item.x, item.y)
            markup.append(f'<text x="{x:.1f}" y="{y:.1f}" font-size="19">{_svg_escape(item.text or item.label)}</text>')

    for point in points:
        x, y = _map_point(point.x, point.y)
        label = point.label or point.id
        markup.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.8" fill="#111"/>')
        markup.append(f'<text x="{x+8:.1f}" y="{y-8:.1f}" font-size="21" font-style="italic">{_svg_escape(label)}</text>')
    return _svg_shell("".join(markup), caption=spec.annotations[0] if spec.annotations else "题图示意")


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
<p class="atm-caption">{_html_escape(caption, limit=120)}</p>
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
