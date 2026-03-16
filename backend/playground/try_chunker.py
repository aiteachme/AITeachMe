"""手动验证 Markdown 切块效果。"""

from __future__ import annotations

import json
from pathlib import Path

from app.agents.digest.chunker import chunk_markdown


def main() -> None:
    input_dir = Path("playground/inputs")
    output_dir = Path("playground/outputs")
    output_dir.mkdir(parents=True, exist_ok=True)

    markdown_files = sorted(input_dir.glob("*.md"))
    if not markdown_files:
        print("playground/inputs/ 下没有 Markdown 文件。")
        return

    source = markdown_files[0]
    chunks = chunk_markdown(source.read_text(encoding="utf-8"))
    target = output_dir / f"{source.stem}.chunks.json"
    target.write_text(
        json.dumps([chunk.to_dict() for chunk in chunks], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"已输出到: {target}")


if __name__ == "__main__":
    main()
