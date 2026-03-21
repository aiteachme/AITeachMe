"""Generate Mermaid diagrams directly from compiled LangGraph workflows."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.workflows.common.graph_export import WorkflowGraphExport
from app.workflows.digest.exports import WORKFLOW_EXPORTS as DIGEST_WORKFLOW_EXPORTS
from app.workflows.ingest.exports import WORKFLOW_EXPORTS as INGEST_WORKFLOW_EXPORTS

DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / ".generated_workflow_diagrams"
WORKFLOW_REGISTRY = {
    export.key: export
    for export in (*INGEST_WORKFLOW_EXPORTS, *DIGEST_WORKFLOW_EXPORTS)
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate Mermaid diagrams from compiled LangGraph workflows.",
    )
    parser.add_argument(
        "--modules",
        nargs="*",
        default=["all"],
        help=f"Available modules: all, {', '.join(sorted(WORKFLOW_REGISTRY))}",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory where markdown diagrams will be written.",
    )
    return parser.parse_args()


def resolve_requested_modules(modules: list[str]) -> list[str]:
    if not modules or "all" in modules:
        return sorted(WORKFLOW_REGISTRY)

    invalid_modules = [module for module in modules if module not in WORKFLOW_REGISTRY]
    if invalid_modules:
        valid = ", ".join(sorted(WORKFLOW_REGISTRY))
        invalid = ", ".join(invalid_modules)
        raise ValueError(f"Unknown modules: {invalid}. Available values: all, {valid}")

    return modules


def render_mermaid(export: WorkflowGraphExport) -> str:
    compiled = export.build_graph().compile()
    graph_view = compiled.get_graph()
    draw_mermaid = getattr(graph_view, "draw_mermaid", None)
    if not callable(draw_mermaid):
        raise RuntimeError(
            "The compiled workflow graph does not expose draw_mermaid(). "
            "Install a LangGraph/LangChain graph version with Mermaid export support.",
        )

    mermaid = draw_mermaid()
    if isinstance(mermaid, bytes):
        mermaid = mermaid.decode("utf-8")
    return str(mermaid).strip()


def build_markdown(export: WorkflowGraphExport) -> str:
    description_block = f"{export.description}\n\n" if export.description else ""
    mermaid = render_mermaid(export)
    return (
        f"# {export.title}\n\n"
        f"{description_block}"
        "```mermaid\n"
        f"{mermaid}\n"
        "```\n"
    )


def write_diagrams(*, output_dir: Path, module_keys: list[str]) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    written_paths: list[Path] = []
    index_lines = [
        "# Workflow Diagrams",
        "",
        "Generated from compiled LangGraph workflows.",
        "",
    ]

    for module_key in module_keys:
        export = WORKFLOW_REGISTRY[module_key]
        output_path = output_dir / f"{module_key}.md"
        output_path.write_text(build_markdown(export), encoding="utf-8")
        written_paths.append(output_path)
        index_lines.append(f"- [{export.title}]({output_path.name})")

    readme_path = output_dir / "README.md"
    readme_path.write_text("\n".join(index_lines) + "\n", encoding="utf-8")
    written_paths.append(readme_path)
    return written_paths


def main() -> int:
    args = parse_args()
    try:
        module_keys = resolve_requested_modules(args.modules)
        written_paths = write_diagrams(output_dir=args.output_dir, module_keys=module_keys)
    except (RuntimeError, ValueError) as exc:
        print(str(exc))
        return 1

    print("Generated workflow diagram files:")
    for path in written_paths:
        print(f"- {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
