"""Manual playground script for validating PDF parsing."""

from __future__ import annotations

import asyncio
from pathlib import Path

import structlog

from app.workflows.ingest.parsing.classifier import classify_file
from app.workflows.ingest.parsing.orchestrator import parse_file


logger = structlog.get_logger()


async def main() -> None:
    playground_dir = Path(__file__).resolve().parent
    input_dir = playground_dir / "inputs"
    output_dir = playground_dir / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(input_dir.glob("*"))
    logger.info("files_in_input_dir", files=[file.name for file in files])

    pdf_files = sorted(input_dir.glob("*.pdf"))
    if not pdf_files:
        print("No PDF files found under backend/playground/inputs.")
        return

    source = pdf_files[0]
    asset_dir = output_dir / f"{source.stem}_assets"
    classification = classify_file(source, source.suffix)
    result = await parse_file(source, asset_dir, classification=classification)

    target = output_dir / f"{source.stem}.md"
    target.write_text(result.markdown, encoding="utf-8")
    print(f"Wrote markdown to: {target}")
    print(f"Parser used: {result.parser_used}")


if __name__ == "__main__":
    asyncio.run(main())