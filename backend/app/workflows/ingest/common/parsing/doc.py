"""Legacy DOC parsers that convert to DOCX and reuse the DOCX parser chain."""

from __future__ import annotations

import asyncio
import sys
import shutil
import subprocess
import tempfile
from collections.abc import Awaitable, Callable
from pathlib import Path

from app.shared.infra.exceptions import FileParseError
from app.workflows.ingest.common.parsing.docx import (
    parse_docx_with_markitdown,
    parse_docx_with_native,
)
from app.workflows.ingest.common.parsing.docx_mammoth import parse_docx_with_mammoth
from app.workflows.ingest.common.parsing.types import ParserRunOptions

try:
    import pythoncom
    import win32com.client
except ImportError:
    pythoncom = None
    win32com = None


DocxParser = Callable[[str | Path, Path, ParserRunOptions], Awaitable[str]]
_WORD_SAVE_AS_DOCX = 16


class _WordCOMUnavailableError(RuntimeError):
    """Raised when Microsoft Word COM automation cannot be used on this machine."""


def _find_soffice() -> str | None:
    for candidate in ("soffice", "libreoffice"):
        path = shutil.which(candidate)
        if path:
            return path
    return None


DOC_WORD_COM_AVAILABLE = bool(sys.platform.startswith("win") and pythoncom is not None and win32com is not None)
DOC_SOFFICE_AVAILABLE = _find_soffice() is not None
DOC_VIA_DOCX_AVAILABLE = DOC_WORD_COM_AVAILABLE or DOC_SOFFICE_AVAILABLE


def _convert_doc_with_word_com(path: Path, output_dir: Path) -> Path:
    if not DOC_WORD_COM_AVAILABLE:
        raise _WordCOMUnavailableError("Microsoft Word COM automation is not available.")

    output_dir.mkdir(parents=True, exist_ok=True)
    target_path = output_dir / f"{path.stem}.docx"

    pythoncom.CoInitialize()
    word_app = None
    document = None
    try:
        try:
            word_app = win32com.client.DispatchEx("Word.Application")
        except Exception as exc:
            raise _WordCOMUnavailableError(f"Microsoft Word is not installed or cannot be launched: {exc}") from exc

        word_app.Visible = False
        word_app.DisplayAlerts = 0

        try:
            document = word_app.Documents.Open(
                str(path.resolve()),
                ConfirmConversions=False,
                ReadOnly=True,
                AddToRecentFiles=False,
            )
            document.SaveAs2(
                str(target_path),
                FileFormat=_WORD_SAVE_AS_DOCX,
                AddToRecentFiles=False,
            )
        except Exception as exc:
            raise FileParseError(path.name, reason=f"Microsoft Word DOC->DOCX conversion failed: {exc}") from exc
    finally:
        if document is not None:
            try:
                document.Close(False)
            except Exception:
                pass
        if word_app is not None:
            try:
                word_app.Quit()
            except Exception:
                pass
        pythoncom.CoUninitialize()

    if target_path.exists():
        return target_path
    raise FileParseError(path.name, reason="Microsoft Word conversion did not produce a DOCX file.")


def _convert_doc_with_soffice(path: Path, output_dir: Path) -> Path:
    soffice = _find_soffice()
    if not soffice:
        raise FileParseError(path.name, reason="LibreOffice/soffice is not available.")

    output_dir.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            soffice,
            "--headless",
            "--convert-to",
            "docx",
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
        raise FileParseError(path.name, reason=f"LibreOffice DOC->DOCX conversion failed: {detail}")

    expected = output_dir / f"{path.stem}.docx"
    if expected.exists():
        return expected
    matches = sorted(output_dir.glob("*.docx"))
    if matches:
        return matches[0]
    raise FileParseError(path.name, reason="LibreOffice conversion did not produce a DOCX file.")


def _convert_doc_to_docx(path: Path, output_dir: Path) -> Path:
    if DOC_WORD_COM_AVAILABLE:
        try:
            return _convert_doc_with_word_com(path, output_dir)
        except _WordCOMUnavailableError:
            pass

    if DOC_SOFFICE_AVAILABLE:
        return _convert_doc_with_soffice(path, output_dir)

    raise FileParseError(
        path.name,
        reason="Local DOC parsing requires Microsoft Word (COM) or LibreOffice/soffice to convert the file to DOCX first.",
    )


async def _parse_doc_with_docx_parser(
    file_path: str | Path,
    asset_dir: Path,
    options: ParserRunOptions,
    *,
    parser: DocxParser,
) -> str:
    path = Path(file_path)
    with tempfile.TemporaryDirectory(prefix="atm_doc_local_") as tmp_dir:
        converted_docx = await asyncio.to_thread(
            _convert_doc_to_docx,
            path,
            Path(tmp_dir),
        )
        return await parser(converted_docx, asset_dir, options)


async def parse_doc_with_markitdown(
    file_path: str | Path,
    asset_dir: Path,
    options: ParserRunOptions,
) -> str:
    """Convert DOC to DOCX, then parse with the DOCX MarkItDown route."""

    return await _parse_doc_with_docx_parser(
        file_path,
        asset_dir,
        options,
        parser=parse_docx_with_markitdown,
    )


async def parse_doc_with_mammoth(
    file_path: str | Path,
    asset_dir: Path,
    options: ParserRunOptions,
) -> str:
    """Convert DOC to DOCX, then parse with Mammoth."""

    return await _parse_doc_with_docx_parser(
        file_path,
        asset_dir,
        options,
        parser=parse_docx_with_mammoth,
    )


async def parse_doc_with_native(
    file_path: str | Path,
    asset_dir: Path,
    options: ParserRunOptions,
) -> str:
    """Convert DOC to DOCX, then parse with the native DOCX route."""

    return await _parse_doc_with_docx_parser(
        file_path,
        asset_dir,
        options,
        parser=parse_docx_with_native,
    )
