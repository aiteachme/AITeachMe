"""Manual playground script for generating an exam from markdown text."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from app.workflows.examine import generate_exam_from_text


async def main() -> None:
    playground_dir = Path(__file__).resolve().parent
    input_dir = playground_dir / "inputs"
    output_dir = playground_dir / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)

    text_files = sorted(input_dir.glob("*.md"))
    if not text_files:
        print("No Markdown files found under backend/playground/inputs.")
        return

    source = text_files[0]
    questions = await generate_exam_from_text(
        subject_name="manual-playground",
        knowledge_text=source.read_text(encoding="utf-8"),
        num_questions=5,
    )
    target = output_dir / f"{source.stem}.exam.json"
    target.write_text(
        json.dumps([question.model_dump() for question in questions], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Wrote exam JSON to: {target}")


if __name__ == "__main__":
    asyncio.run(main())
