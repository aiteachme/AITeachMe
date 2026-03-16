"""手动验证从知识文本直接出题。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from app.agents.examine.generator import generate_exam_from_text


async def main() -> None:
    input_dir = Path("playground/inputs")
    output_dir = Path("playground/outputs")
    output_dir.mkdir(parents=True, exist_ok=True)

    text_files = sorted(input_dir.glob("*.md"))
    if not text_files:
        print("playground/inputs/ 下没有 Markdown 文件。")
        return

    source = text_files[0]
    questions = await generate_exam_from_text(
        subject="manual-playground",
        knowledge_text=source.read_text(encoding="utf-8"),
        num_questions=5,
    )
    target = output_dir / f"{source.stem}.exam.json"
    target.write_text(
        json.dumps([question.model_dump() for question in questions], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"已输出到: {target}")


if __name__ == "__main__":
    asyncio.run(main())
