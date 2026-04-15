"""Manual playground for checking markdown chunk output."""

from __future__ import annotations

import json
from pathlib import Path

from app.workflows.digest.knowledge_graph.services.chunker import chunk_markdown


def main() -> None:
    input_dir = Path("playground/inputs")
    output_dir = Path("playground/outputs")
    output_dir.mkdir(parents=True, exist_ok=True)

    markdown_files = sorted(input_dir.glob("*.md"))
    if not markdown_files:
        print("No Markdown files found under playground/inputs/.")
        return

    source = markdown_files[0]
    chunks = chunk_markdown(source.read_text(encoding="utf-8"))
    target = output_dir / f"{source.stem}.chunks.json"
    target.write_text(
        json.dumps([chunk.to_dict() for chunk in chunks], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Wrote chunk output to: {target}")


if __name__ == "__main__":
    main()

