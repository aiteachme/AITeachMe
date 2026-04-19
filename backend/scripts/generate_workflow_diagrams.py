"""Generate rich Mermaid architecture diagrams from compiled LangGraph workflows.

Builds Mermaid from scratch using the graph topology (nodes + edges) rather
than LangGraph's built-in draw_mermaid(). Produces one markdown file per
engine module with sub-workflow diagrams, auto-generated node reference
tables, and collected prompt fingerprints.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

try:
    # Preferred import path after workflow infra consolidation.
    from app.shared.infra.workflow import WorkflowGraphExport
except ImportError:
    # Backward compatibility for older branches.
    from app.shared.infra.workflow.graph_export import WorkflowGraphExport

DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / ".generated_workflow_diagrams"
WORKFLOWS_DIR = BACKEND_DIR / "app" / "workflows"


# ── Module metadata (fallback to auto-generated if missing) ──────────────────

MODULE_META: dict[str, dict[str, str]] = {
    "ingest": {
        "title": "Ingest Engine · 摄入引擎",
        "desc": "文件上传 → 快速传统解析 → 后台深度 OCR 增强，为下游 Digest 提供高质量文本素材。",
        "icon": "📥",
    },
    "digest": {
        "title": "Digest Engine · 消化引擎",
        "desc": "三车道并行：知识图谱构建 · 教案文档生成 · 课程大纲推导，把原始文本转化为结构化学习资产。",
        "icon": "🧬",
    },
    "interact": {
        "title": "Interact Engine · 伴读引擎",
        "desc": "基于用户画像的个性化教学对话引擎，融合检索增强、教学策略选择与流式回答。",
        "icon": "💬",
    },
    "examine": {
        "title": "Examine Engine · 诊断引擎",
        "desc": "智能出卷 → AI 判卷 → 错因归类 → 掌握度更新 → 复习调度，形成完整的考试闭环。",
        "icon": "📝",
    },
    "profile": {
        "title": "Profile Engine · 显影引擎",
        "desc": "掌握度计算 → 遗忘曲线复习排期 → 弱势排行 → 学习报告生成，驱动用户能力雷达图。",
        "icon": "📊",
    },
}


# ── Node display helpers ─────────────────────────────────────────────────────


def _humanize(node_id: str) -> str:
    """Convert a snake_case node ID into a readable label."""
    if node_id == "__start__":
        return "START"
    if node_id == "__end__":
        return "END"
    return node_id.replace("_", " ").title()


def _node_shape(node_id: str, label: str) -> str:
    """Return Mermaid node declaration with shape based on node type."""
    if node_id == "__start__":
        return f'{node_id}(["▶ {label}"])'
    if node_id == "__end__":
        return f'{node_id}(["⏹ {label}"])'
    if "fail" in node_id or "error" in node_id:
        return f'{node_id}["⚠ {label}"]'
    if "finalize" in node_id or "publish" in node_id or "cleanup" in node_id:
        return f'{node_id}(["{label}"])'  # stadium / pill shape for terminal-like
    return f'{node_id}["{label}"]'


def _node_class(node_id: str) -> str | None:
    """Return CSS class name for a node, or None."""
    if node_id == "__start__":
        return "startCls"
    if node_id == "__end__":
        return "endCls"
    if "fail" in node_id or "error" in node_id:
        return "failCls"
    if "finalize" in node_id or "publish" in node_id or "cleanup" in node_id:
        return "termCls"
    return None


def _classify_edge_label(label: str | None) -> str:
    """Classify an edge label for styling purposes."""
    if not label:
        return "normal"
    s = str(label).lower().strip()
    if s in ("fail", "error"):
        return "fail"
    if s in ("finish",):
        return "abort"  # early exit, typically error handling
    if s in ("continue",):
        return "happy"
    return "normal"


def _render_edge_label(label: str | None) -> str | None:
    """Make edge labels more readable."""
    if not label:
        return None
    s = str(label).strip()
    mapping = {
        "continue": "✓",
        "finish": "✗ err",
        "fail": "✗ fail",
    }
    return mapping.get(s.lower(), s)


@dataclass(frozen=True, slots=True)
class DisplayEdge:
    source: str
    target: str
    label: str | None = None
    dashed: bool = False


def _parse_extra_edge(edge_str: str) -> DisplayEdge:
    """Parse a manually-declared display edge."""

    dashed_match = re.fullmatch(r"\s*(\S+)\s+-\.\s*(.*?)\s*\.\->\s*(\S+)\s*", edge_str)
    if dashed_match:
        src, label, tgt = dashed_match.groups()
        return DisplayEdge(source=src, target=tgt, label=label.strip() or None, dashed=True)

    plain_match = re.fullmatch(r"\s*(\S+)\s+-->\s*(\S+)\s*", edge_str)
    if plain_match:
        src, tgt = plain_match.groups()
        return DisplayEdge(source=src, target=tgt)

    raise ValueError(f"Unsupported extra edge format: {edge_str!r}")


def _merge_display_edges(
    raw_edges: list[DisplayEdge],
    extra_edges: tuple[str, ...],
) -> list[DisplayEdge]:
    """Merge compiled edges with explicit display overrides."""

    parsed_extra = [_parse_extra_edge(edge_str) for edge_str in extra_edges]
    extra_by_pair = {(edge.source, edge.target): edge for edge in parsed_extra}
    raw_pairs = {(edge.source, edge.target) for edge in raw_edges}

    merged: list[DisplayEdge] = []
    emitted_extra_pairs: set[tuple[str, str]] = set()

    for edge in raw_edges:
        pair = (edge.source, edge.target)
        replacement = extra_by_pair.get(pair)
        if replacement is not None:
            merged.append(replacement)
            emitted_extra_pairs.add(pair)
            continue
        merged.append(edge)

    for edge in parsed_extra:
        pair = (edge.source, edge.target)
        if pair in raw_pairs or pair in emitted_extra_pairs:
            continue
        merged.append(edge)

    return merged


# ── Discovery ────────────────────────────────────────────────────────────────


def discover_workflow_exports() -> tuple[WorkflowGraphExport, ...]:
    exports: list[WorkflowGraphExport] = []
    for module_dir in sorted(WORKFLOWS_DIR.iterdir(), key=lambda p: p.name):
        if not module_dir.is_dir():
            continue
        if module_dir.name.startswith("_") or module_dir.name == "common":
            continue

        module_name = f"app.workflows.{module_dir.name}"
        try:
            module = import_module(module_name)
        except Exception as exc:
            raise RuntimeError(f"Failed to import {module_name}: {exc}") from exc
        module_exports = getattr(module, "WORKFLOW_EXPORTS", None)
        if module_exports is None and (module_dir / "exports.py").exists():
            exports_module_name = f"{module_name}.exports"
            try:
                exports_module = import_module(exports_module_name)
            except Exception as exc:
                raise RuntimeError(f"Failed to import {exports_module_name}: {exc}") from exc
            module_exports = getattr(exports_module, "WORKFLOW_EXPORTS", None)
        if module_exports:
            exports.extend(module_exports)
    return tuple(exports)


DISCOVERED = discover_workflow_exports()
REGISTRY = {e.key: e for e in DISCOVERED}


def _module_of(key: str) -> str:
    return key.split("_")[0]


def group_by_module(keys: list[str]) -> dict[str, list[WorkflowGraphExport]]:
    grouped: dict[str, list[WorkflowGraphExport]] = defaultdict(list)
    for k in keys:
        grouped[_module_of(k)].append(REGISTRY[k])
    return dict(grouped)


# ── CLI ──────────────────────────────────────────────────────────────────────


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate workflow architecture diagrams.")
    p.add_argument("--modules", nargs="*", default=["all"])
    p.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return p.parse_args()


def resolve_keys(modules: list[str]) -> list[str]:
    if not modules or "all" in modules:
        return list(REGISTRY)
    bad = [m for m in modules if m not in REGISTRY]
    if bad:
        raise ValueError(f"Unknown: {bad}. Available: {sorted(REGISTRY)}")
    return modules


# ── Graph analysis ───────────────────────────────────────────────────────────


def _trace_happy_path(out_edges: dict[str, list[DisplayEdge]], node_ids: list[str]) -> list[str]:
    """Walk the graph from __start__ following only 'continue'/unlabeled edges.

    Returns an ordered list of node IDs on the primary success path.
    """
    path: list[str] = []
    visited: set[str] = set()
    current = "__start__"

    while current and current not in visited:
        visited.add(current)
        if current not in ("__start__", "__end__"):
            path.append(current)

        # Pick the next node: prefer 'continue' edge, then unlabeled, skip fail
        outs = out_edges.get(current, [])
        next_node = None
        for edge in outs:
            lbl = str(edge.label).lower().strip() if edge.label else ""
            if lbl == "continue":
                next_node = edge.target
                break
        if not next_node:
            for edge in outs:
                lbl = str(edge.label).lower().strip() if edge.label else ""
                if not lbl and edge.target != "__end__":
                    next_node = edge.target
                    break
        if not next_node:
            for edge in outs:
                lbl = str(edge.label).lower().strip() if edge.label else ""
                if lbl not in ("fail", "error", "finish") and edge.target != "__end__":
                    next_node = edge.target
                    break
        current = next_node

    return path


def _analyze_graph(export: WorkflowGraphExport) -> dict:
    """Compile graph and extract rich topology + metadata for rendering."""

    compiled = export.build_graph().compile()
    graph = compiled.get_graph()

    node_ids = [n.id for n in graph.nodes.values()]
    raw_edges = [
        DisplayEdge(source=e.source, target=e.target, label=e.data)
        for e in graph.edges
    ]
    edges = _merge_display_edges(raw_edges, export.extra_edges)

    # Build adjacency info
    out_edges: dict[str, list[DisplayEdge]] = defaultdict(list)
    in_edges: dict[str, list[DisplayEdge]] = defaultdict(list)
    for edge in edges:
        out_edges[edge.source].append(edge)
        in_edges[edge.target].append(edge)

    # Trace the happy path (main success flow)
    happy_path = _trace_happy_path(out_edges, node_ids)
    happy_step: dict[str, int] = {nid: i + 1 for i, nid in enumerate(happy_path)}

    # Identify error/fail nodes
    fail_nodes = [n for n in node_ids if n not in ("__start__", "__end__")
                  and ("fail" in n or "error" in n)]

    # Classify each node's role
    node_roles: dict[str, str] = {}
    for nid in node_ids:
        if nid == "__start__":
            node_roles[nid] = "入口"
        elif nid == "__end__":
            node_roles[nid] = "出口"
        elif nid in fail_nodes:
            node_roles[nid] = "❌ 错误处理"
        elif len(out_edges[nid]) > 1:
            labels = [edge.label for edge in out_edges[nid] if edge.label]
            if labels:
                node_roles[nid] = "🔀 条件路由"
            else:
                node_roles[nid] = "🔀 分支"
        elif "finalize" in nid or "publish" in nid or "cleanup" in nid:
            node_roles[nid] = "✅ 终结节点"
        else:
            node_roles[nid] = "⚙ 处理节点"

    # Detect if graph is mostly linear (for layout direction)
    process_nodes = [n for n in node_ids if n not in ("__start__", "__end__")]
    max_out = max((len(out_edges[n]) for n in process_nodes), default=0)
    is_linear = max_out <= 2 and len(process_nodes) <= 8

    return {
        "node_ids": node_ids,
        "edges": edges,
        "out_edges": out_edges,
        "in_edges": in_edges,
        "node_labels": dict(export.node_labels or {}),
        "node_roles": node_roles,
        "happy_step": happy_step,
        "fail_nodes": fail_nodes,
        "is_linear": is_linear,
        "process_node_count": len(process_nodes),
        "edge_count": len(edges),
        "has_fan_out": bool(export.extra_edges),
    }


# ── Mermaid builder ──────────────────────────────────────────────────────────

_STEP_ICONS = ["❶", "❷", "❸", "❹", "❺", "❻", "❼", "❽", "❾", "❿",
               "⓫", "⓬", "⓭", "⓮", "⓯", "⓰", "⓱", "⓲", "⓳", "⓴"]


def build_mermaid(export: WorkflowGraphExport, analysis: dict) -> str:
    """Build a clean Mermaid flowchart from the analyzed graph topology."""

    node_ids = analysis["node_ids"]
    edges = analysis["edges"]
    is_linear = analysis["is_linear"]
    happy_step = analysis["happy_step"]
    fail_nodes = analysis["fail_nodes"]
    node_labels = analysis["node_labels"]

    lines: list[str] = []

    # Always use top-down layout
    lines.append("flowchart TD")

    # --- Node declarations (non-fail nodes) ---
    for nid in node_ids:
        if nid in fail_nodes:
            continue  # declared inside subgraph below
        label = node_labels.get(nid) or _humanize(nid)
        # Add step number for happy-path nodes
        step = happy_step.get(nid)
        if step and step <= len(_STEP_ICONS):
            label = f"{_STEP_ICONS[step - 1]} {label}"
        decl = _node_shape(nid, label)
        lines.append(f"    {decl}")

    lines.append("")

    # --- Error handling subgraph ---
    if fail_nodes:
        lines.append('    subgraph error_zone ["⚠ 错误处理"]')
        lines.append("    direction TB")
        for nid in fail_nodes:
            label = node_labels.get(nid) or _humanize(nid)
            decl = _node_shape(nid, label)
            lines.append(f"        {decl}")
        lines.append("    end")
        lines.append("")

    # --- Edges ---
    edge_index = 0
    fail_indices: list[int] = []

    for edge in edges:
        rendered = _render_edge_label(edge.label)
        edge_type = _classify_edge_label(edge.label)
        is_dashed = edge.dashed or edge_type in ("fail", "abort")

        if is_dashed:
            if rendered:
                lines.append(f"    {edge.source} -. \"{rendered}\" .-> {edge.target}")
            else:
                lines.append(f"    {edge.source} -.-> {edge.target}")
            if edge_type in ("fail", "abort"):
                fail_indices.append(edge_index)
        elif rendered:
            lines.append(f'    {edge.source} -->|"{rendered}"| {edge.target}')
        else:
            lines.append(f"    {edge.source} --> {edge.target}")

        edge_index += 1

    lines.append("")

    # --- Styling ---
    lines.append("    %% ── Styling ──")
    lines.append("    classDef startCls fill:#064e3b,stroke:#10b981,stroke-width:2px,color:#a7f3d0")
    lines.append("    classDef endCls fill:#7f1d1d,stroke:#ef4444,stroke-width:2px,color:#fecaca")
    lines.append("    classDef failCls fill:#4c0519,stroke:#f43f5e,stroke-width:2px,color:#fecdd3")
    lines.append("    classDef termCls fill:#1e3a5f,stroke:#3b82f6,stroke-width:2px,color:#93c5fd")
    lines.append("    classDef default fill:#1e293b,stroke:#475569,stroke-width:1px,color:#e2e8f0")
    if fail_nodes:
        lines.append("    style error_zone fill:#1a0a0e,stroke:#f43f5e,stroke-width:1px,color:#fecdd3,stroke-dasharray:5")

    # Assign classes
    for nid in node_ids:
        cls = _node_class(nid)
        if cls:
            lines.append(f"    class {nid} {cls}")

    # Red dashed links for fail edges
    if fail_indices:
        idx_str = ",".join(str(i) for i in fail_indices)
        lines.append(f"    linkStyle {idx_str} stroke:#f43f5e,stroke-dasharray:5")

    return "\n".join(lines)


# ── Node reference table builder ─────────────────────────────────────────────


def build_node_table(analysis: dict) -> str:
    """Auto-generate a node reference table from graph analysis."""

    node_ids = analysis["node_ids"]
    node_roles = analysis["node_roles"]
    out_edges = analysis["out_edges"]
    node_labels = analysis["node_labels"]

    rows = []
    for nid in node_ids:
        if nid in ("__start__", "__end__"):
            continue

        role = node_roles.get(nid, "⚙ 处理节点")
        label = node_labels.get(nid) or _humanize(nid)

        # Determine routing behavior from out-edges
        outs = out_edges.get(nid, [])
        route_desc = ""
        if len(outs) > 1:
            labels = [str(edge.label) for edge in outs if edge.label]
            if labels:
                route_desc = " / ".join(
                    f"`{edge.label}` -> {'END' if edge.target == '__end__' else node_labels.get(edge.target) or _humanize(edge.target)}"
                    if edge.label
                    else f"-> {'END' if edge.target == '__end__' else _humanize(edge.target)}"
                    for edge in outs
                )
                labels = None
            if labels is not None and labels:
                route_desc = " → ".join(f"`{l}`" for l in labels)
            elif labels is not None:
                targets = [node_labels.get(edge.target) or _humanize(edge.target) for edge in outs]
                route_desc = " / ".join(targets)
        elif len(outs) == 1:
            edge = outs[0]
            tgt = edge.target
            lbl = edge.label
            target_label = "END" if tgt == "__end__" else node_labels.get(tgt) or _humanize(tgt)
            if lbl:
                route_desc = f"`{lbl}` -> {target_label}"
                lbl = None
            elif edge.target == "__end__":
                route_desc = "→ END"
            else:
                route_desc = f"→ {node_labels.get(tgt) or _humanize(tgt)}"

        rows.append(f"| {label} | {role} | {route_desc} |")

    if not rows:
        return ""

    header = "| 节点 | 角色 | 路由 |\n|------|------|------|\n"
    return header + "\n".join(rows)


# ── Markdown assembly ────────────────────────────────────────────────────────


def build_module_md(module: str, exports: list[WorkflowGraphExport]) -> str:
    meta = MODULE_META.get(module, {"title": module.title(), "desc": "", "icon": "⚙"})
    parts: list[str] = []

    # Header
    parts.append(f"# {meta['icon']} {meta['title']}")
    parts.append("")
    if meta["desc"]:
        parts.append(f"> {meta['desc']}")
        parts.append("")

    # Table of contents for sub-workflows
    if len(exports) > 1:
        parts.append("**本模块包含以下子工作流：**")
        parts.append("")
        for i, exp in enumerate(exports, 1):
            parts.append(f"{i}. [{exp.title}](#{exp.key.replace('_', '-')})")
        parts.append("")
        parts.append("---")
        parts.append("")

    # Each sub-workflow
    for exp in exports:
        analysis = _analyze_graph(exp)
        mermaid = build_mermaid(exp, analysis)
        node_table = build_node_table(analysis)

        parts.append(f"## {exp.title}")
        parts.append("")
        if exp.description:
            parts.append(f"> {exp.description}")
            parts.append("")

        # Stats badge line
        stats = (
            f"📊 **{analysis['process_node_count']}** 个处理节点 · "
            f"**{analysis['edge_count']}** 条边"
        )
        if analysis["has_fan_out"]:
            stats += " · 🔄 含 Fan-out 并行"
        parts.append(stats)
        parts.append("")

        # Diagram
        parts.append("```mermaid")
        parts.append(mermaid)
        parts.append("```")
        parts.append("")

        # Node reference table
        if node_table:
            parts.append("**节点参考：**")
            parts.append("")
            parts.append(node_table)
            parts.append("")

    # Prompts section (deduplicated)
    all_prompts: dict[str, str] = {}
    for exp in exports:
        if exp.prompts:
            for k, v in exp.prompts.items():
                if k not in all_prompts:
                    all_prompts[k] = v

    if all_prompts:
        parts.append("---")
        parts.append("")
        parts.append("## 🧬 核心 Prompt 指纹")
        parts.append("")
        parts.append(f"> 本引擎共使用 **{len(all_prompts)}** 个核心提示词模板。点击展开查看完整内容。")
        parts.append("")

        for key, prompt in all_prompts.items():
            display = key.replace("_", " ").title()
            parts.append(f"<details>")
            parts.append(f"<summary><b>{display}</b> (<code>{key}</code>)</summary>")
            parts.append("")
            parts.append("```")
            parts.append(prompt.strip())
            parts.append("```")
            parts.append("")
            parts.append("</details>")
            parts.append("")

    return "\n".join(parts)


# ── File writing ─────────────────────────────────────────────────────────────


def write_all(*, output_dir: Path, keys: list[str]) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    grouped = group_by_module(keys)
    written: list[Path] = []

    # Clean old files
    for old in output_dir.glob("*.md"):
        old.unlink()

    readme_rows: list[str] = []

    for module in sorted(grouped):
        exports = grouped[module]
        meta = MODULE_META.get(module, {"title": module.title(), "icon": "⚙"})
        fname = f"{module}.md"
        path = output_dir / fname

        content = build_module_md(module, exports)
        path.write_text(content, encoding="utf-8")
        written.append(path)

        sub = " / ".join(e.title for e in exports)
        readme_rows.append(f"| {meta['icon']} {meta['title']} | [{fname}]({fname}) | {sub} |")

    # README
    readme = "\n".join([
        "# AITeachMe 工作流架构图",
        "",
        "> 由 `backend/scripts/generate_workflow_diagrams.py` 从已编译的 LangGraph 拓扑自动生成。",
        "> 运行 `conda activate atm && python backend/scripts/generate_workflow_diagrams.py` 可重新生成。",
        "",
        "## 图例说明",
        "",
        "| 元素 | 含义 |",
        "|------|------|",
        "| `▶ START` (绿色) | 工作流入口 |",
        "| `⏹ END` (红色) | 工作流出口 |",
        "| `⚠ Fail xxx` (深红) | 错误处理节点 |",
        "| 药丸形节点 (蓝色) | 终结/收尾节点 |",
        "| 方形节点 (深灰) | 普通处理节点 |",
        "| `✓` 实线箭头 | 正常流转（Happy Path） |",
        "| `✗ err/fail` 红色虚线 | 错误/中断路径 |",
        "| `Send xN` 虚线 | Fan-out 并行分发 |",
        "",
        "## 模块索引",
        "",
        "| 模块 | 文件 | 包含的子工作流 |",
        "|------|------|----------------|",
        *readme_rows,
        "",
    ])
    readme_path = output_dir / "README.md"
    readme_path.write_text(readme, encoding="utf-8")
    written.append(readme_path)

    return written


# ── Main ─────────────────────────────────────────────────────────────────────


def main() -> int:
    args = parse_args()
    try:
        keys = resolve_keys(args.modules)
        paths = write_all(output_dir=args.output_dir, keys=keys)
    except (RuntimeError, ValueError) as exc:
        print(f"Error: {exc}")
        return 1

    print(f"Generated {len(paths)} files:")
    for p in paths:
        print(f"  - {p.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
