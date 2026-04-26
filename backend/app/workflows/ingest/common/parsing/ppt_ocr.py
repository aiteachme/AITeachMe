"""OCR-first parser for slide decks.

The implementation converts PPT/PPTX files to PDF with LibreOffice when
available, then reuses the PDF page-to-image vision OCR path.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import tempfile
from pathlib import Path

from app.shared.infra.exceptions import FileParseError
from app.workflows.ingest.common.parsing.pdf import parse_pdf_with_pymupdf_ocr_vision
from app.workflows.ingest.common.parsing.types import ParserRunOptions


def _find_soffice() -> str | None:
    for candidate in ("soffice", "libreoffice"):
        path = shutil.which(candidate)
        if path:
            return path
    return None


PPT_OCR_VISION_AVAILABLE = _find_soffice() is not None


def _convert_ppt_to_pdf(path: Path, output_dir: Path) -> Path:
    soffice = _find_soffice()
    if not soffice:
        raise FileParseError(
            path.name,
            reason="OCR parsing PPT/PPTX requires LibreOffice/soffice on PATH.",
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            soffice,
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(output_dir),
            str(path),
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise FileParseError(path.name, reason=f"LibreOffice conversion failed: {detail}")

    expected = output_dir / f"{path.stem}.pdf"
    if expected.exists():
        return expected
    matches = sorted(output_dir.glob("*.pdf"))
    if matches:
        return matches[0]
    raise FileParseError(path.name, reason="LibreOffice conversion did not produce a PDF.")


async def parse_ppt_with_ocr_vision(
    file_path: str | Path,
    asset_dir: Path,
    options: ParserRunOptions,
) -> str:
    """Convert slides to PDF and parse rendered pages with LLM vision OCR."""

    path = Path(file_path)
    with tempfile.TemporaryDirectory(prefix="atm_ppt_ocr_") as tmp_dir:
        pdf_path = await asyncio.to_thread(
            _convert_ppt_to_pdf,
            path,
            Path(tmp_dir),
        )
        return await parse_pdf_with_pymupdf_ocr_vision(pdf_path, asset_dir, options)
