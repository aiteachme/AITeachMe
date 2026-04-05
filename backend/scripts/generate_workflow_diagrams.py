"""Generate rich Mermaid architecture diagrams from compiled LangGraph workflows.

Instead of using LangGraph's built-in draw_mermaid() (which produces ugly output),
this script reads the compiled graph topology (nodes + edges) and builds clean,
human-readable Mermaid diagrams from scratch.

Output: one markdown file per engine module with all sub-workflows combined.
"""

from __future__ import annotations

import argparse
import re
import sys
import textwrap
from collections import defaultdict
from importlib import import_module
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.workflows.common.graph_export import WorkflowGraphExport

DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / ".generated_workflow_diagrams"
WORKFLOWS_DIR = BACKEND_DIR / "app" / "workflows"


# ── Module metadata ──────────────────────────────────────────────────────────

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

# ── Node display name mapping ────────────────────────────────────────────────


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
    return f'{node_id}["{label}"]'


def _node_class(node_id: str) -> str | None:
    """Return CSS class name for a node, or None."""
    if node_id == "__start__":
        return "startCls"
    if node_id == "__end__":
        return "endCls"
    if "fail" in node_id or "error" in node_id:
        return "failCls"
    return None


# ── Discovery ────────────────────────────────────────────────────────────────


def discover_workflow_exports() -> tuple[WorkflowGraphExport, ...]:
    exports: list[WorkflowGraphExport] = []
    for module_dir in sorted(WORKFLOWS_DIR.iterdir(), key=lambda p: p.name):
        if not module_dir.is_dir():
            continue
        if module_dir.name.startswith("_") or module_dir.name == "common":
            continue
        if not (module_dir / "exports.py").exists():
            continue
        module_name = f"app.workflows.{module_dir.name}.exports"
        try:
            module = import_module(module_name)
        except Exception as exc:
            raise RuntimeError(f"Failed to import {module_name}: {exc}") from exc
        module_exports = getattr(module, "WORKFLOW_EXPORTS", None)
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
        return sorted(REGISTRY)
    bad = [m for m in modules if m not in REGISTRY]
    if bad:
        raise ValueError(f"Unknown: {bad}. Available: {sorted(REGISTRY)}")
    return modules


# ── Mermaid builder (from scratch) ───────────────────────────────────────────


def build_mermaid(export: WorkflowGraphExport) -> str:
    """Build a clean Mermaid flowchart from the compiled graph topology."""

    compiled = export.build_graph().compile()
    graph = compiled.get_graph()

    # Extract topology
    node_ids = [n.id for n in graph.nodes.values()]
    edges = [(e.source, e.target, e.data) for e in graph.edges]

    # Also inject any extra_edges declared in the export (for Send fan-out)
    extra_edge_sources = set()
    if export.extra_edges:
        for edge_str in export.extra_edges:
            m = re.match(r"\s*(\w+)\s", edge_str)
            if m:
                extra_edge_sources.add(m.group(1))

    lines: list[str] = []

    # --- Header ---
    lines.append("flowchart TD")

    # --- Node declarations ---
    for nid in node_ids:
        label = _humanize(nid)
        decl = _node_shape(nid, label)
        lines.append(f"    {decl}")

    lines.append("")

    # --- Edges ---
    for src, tgt, label in edges:
        # Skip fake edges that are replaced by extra_edges
        if src in extra_edge_sources:
            continue

        if label:
            edge_label = str(label).strip()
            if "fail" in edge_label.lower() or "error" in edge_label.lower():
                lines.append(f"    {src} -. {edge_label} .-> {tgt}")
            else:
                lines.append(f'    {src} -->|"{edge_label}"| {tgt}')
        else:
            lines.append(f"    {src} --> {tgt}")

    # --- Extra edges (Send fan-out) ---
    if export.extra_edges:
        lines.append("")
        lines.append("    %% Fan-out / Send edges")
        for edge_str in export.extra_edges:
            lines.append(f"    {edge_str}")

    lines.append("")

    # --- Styling ---
    lines.append("    %% ── Styling ──")
    lines.append("    classDef startCls fill:#064e3b,stroke:#10b981,stroke-width:2px,color:#a7f3d0")
    lines.append("    classDef endCls fill:#7f1d1d,stroke:#ef4444,stroke-width:2px,color:#fecaca")
    lines.append("    classDef failCls fill:#4c0519,stroke:#f43f5e,stroke-width:2px,color:#fecdd3")
    lines.append("    classDef default fill:#1e293b,stroke:#475569,stroke-width:1px,color:#e2e8f0")

    # Assign classes
    for nid in node_ids:
        cls = _node_class(nid)
        if cls:
            lines.append(f"    class {nid} {cls}")

    # Link style for fail edges
    fail_edge_indices: list[int] = []
    edge_index = 0
    for src, tgt, label in edges:
        if src in extra_edge_sources:
            continue
        if label and ("fail" in str(label).lower() or "finish" in str(label).lower()):
            fail_edge_indices.append(edge_index)
        edge_index += 1

    if fail_edge_indices:
        idx_str = ",".join(str(i) for i in fail_edge_indices)
        lines.append(f"    linkStyle {idx_str} stroke:#f43f5e,stroke-dasharray:5")

    return "\n".join(lines)


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
        mermaid = build_mermaid(exp)

        parts.append(f"## {exp.title}")
        parts.append("")
        if exp.description:
            parts.append(f"> {exp.description}")
            parts.append("")
        parts.append("```mermaid")
        parts.append(mermaid)
        parts.append("```")
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
        parts.append("> 以下为本引擎在推理时注入大模型的核心提示词模板。点击展开查看完整内容。")
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
        "> 由 `scripts/generate_workflow_diagrams.py` 从已编译的 LangGraph 拓扑自动生成。",
        "> 运行 `conda run -n atm python scripts/generate_workflow_diagrams.py` 可重新生成。",
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
        print(f"  ✓ {p.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
