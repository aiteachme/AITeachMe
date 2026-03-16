"""手动验证 PDF 解析效果。"""

from __future__ import annotations

import asyncio
from pathlib import Path
import structlog

logger = structlog.get_logger()

from app.agents.ingest.orchestrator import parse_file



async def main() -> None:
    input_dir = Path("../playground/inputs")
    output_dir = Path("../playground/outputs")
    output_dir.mkdir(parents=True, exist_ok=True)

    ls_files = sorted(input_dir.glob("*"))
    logger.info("files_in_input_dir", files=[f.name for f in ls_files])

    pdf_files = sorted(input_dir.glob("*.pdf"))
    if not pdf_files:
        print("playground/inputs/ 下没有 PDF 文件。")
        return

    source = pdf_files[0]
    markdown = await parse_file(source)
    target = output_dir / f"{source.stem}.md"
    target.write_text(markdown, encoding="utf-8")
    print(f"已输出到: {target}")


if __name__ == "__main__":
    asyncio.run(main())
