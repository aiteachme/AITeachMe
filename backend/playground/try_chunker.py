"""Manual playground for checking markdown chunk output."""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path

from app.workflows.digest.common.markdown_knowledge_anchors import extract_markdown_chapter_chunks


def main() -> None:
    input_dir = Path("playground/inputs")
    output_dir = Path("playground/outputs")
    output_dir.mkdir(parents=True, exist_ok=True)

    markdown_files = sorted(input_dir.glob("*.md"))
    if not markdown_files:
        print("No Markdown files found under playground/inputs/.")
        return

    source = markdown_files[0]
    chunks = extract_markdown_chapter_chunks(source.read_text(encoding="utf-8"), max_body_chars=None)
    target = output_dir / f"{source.stem}.chunks.json"
    target.write_text(
        json.dumps([asdict(chunk) for chunk in chunks], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Wrote chunk output to: {target}")


if __name__ == "__main__":
    main()
