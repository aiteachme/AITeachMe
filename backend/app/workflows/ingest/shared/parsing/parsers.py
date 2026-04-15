"""Named parser registry and capability helpers for ingest workflows."""

from __future__ import annotations

import structlog

from collections.abc import Awaitable, Callable
from pathlib import Path

from app.workflows.ingest.shared.parsing.audio import (
    AUDIO_NATIVE_AVAILABLE,
    is_audio_transcription_available,
    parse_audio_with_transcription,
)
from app.workflows.ingest.shared.parsing.docx import (
    DOCX_MARKITDOWN_AVAILABLE,
    DOCX_NATIVE_AVAILABLE,
    parse_docx_with_markitdown,
    parse_docx_with_native,
)
from app.workflows.ingest.shared.parsing.docx_mammoth import (
    DOCX_MAMMOTH_AVAILABLE,
    parse_docx_with_mammoth,
)
from app.workflows.ingest.shared.parsing.formats import AUDIO_EXTENSIONS, MARKITDOWN_GENERIC_EXTENSIONS, TEXT_EXTENSIONS, normalize_extension
from app.workflows.ingest.shared.parsing.generic import (
    GENERIC_MARKITDOWN_AVAILABLE,
    parse_with_markitdown_generic,
)
from app.workflows.ingest.shared.parsing.image import parse_image_with_llm_vision
from app.workflows.ingest.shared.parsing.pdf import (
    PDF_MARKITDOWN_AVAILABLE,
    PDF_PYMUPDF_OCR_VISION_AVAILABLE,
    PDF_PYMUPDF4LLM_AVAILABLE,
    PDF_PYMUPDF_NATIVE_AVAILABLE,
    parse_pdf_with_markitdown,
    parse_pdf_with_pymupdf_ocr_vision,
    parse_pdf_with_pymupdf4llm,
    parse_pdf_with_pymupdf_native,
)
from app.workflows.ingest.shared.parsing.pdf_pdfplumber import (
    PDF_PDFPLUMBER_AVAILABLE,
    parse_pdf_with_pdfplumber,
)
from app.workflows.ingest.shared.parsing.pptx import (
    PPTX_MARKITDOWN_AVAILABLE,
    PPTX_NATIVE_AVAILABLE,
    parse_pptx_with_markitdown,
    parse_pptx_with_python_pptx,
)
from app.workflows.ingest.shared.parsing.text import (
    TEXT_FALLBACK_EXTENSION,
    TEXT_NATIVE_AVAILABLE,
    is_probably_text_file,
    parse_text_with_native,
)
from app.workflows.ingest.shared.parsing.types import ParserRunOptions

Parser = Callable[[str | Path, Path, ParserRunOptions], Awaitable[str]]


def _build_text_parser_mapping() -> dict[str, dict[str, Parser]]:
    return {extension: {"text_native": parse_text_with_native} for extension in TEXT_EXTENSIONS}


def _build_text_parser_chain() -> dict[str, list[str]]:
    return {extension: ["text_native"] for extension in TEXT_EXTENSIONS}


def _build_text_parser_availability() -> dict[str, dict[str, bool]]:
    return {extension: {"text_native": TEXT_NATIVE_AVAILABLE} for extension in TEXT_EXTENSIONS}


def _build_audio_parser_mapping() -> dict[str, dict[str, Parser]]:
    return {extension: {"audio_transcription": parse_audio_with_transcription} for extension in AUDIO_EXTENSIONS}


def _build_audio_parser_chain() -> dict[str, list[str]]:
    return {extension: ["audio_transcription"] for extension in AUDIO_EXTENSIONS}


def _build_audio_parser_availability() -> dict[str, dict[str, bool]]:
    return {
        extension: {"audio_transcription": is_audio_transcription_available(extension)}
        for extension in AUDIO_EXTENSIONS
    }


def _build_markitdown_generic_mapping() -> dict[str, dict[str, Parser]]:
    return {
        extension: {"markitdown_generic": parse_with_markitdown_generic}
        for extension in MARKITDOWN_GENERIC_EXTENSIONS
    }


def _build_markitdown_generic_chain() -> dict[str, list[str]]:
    return {extension: ["markitdown_generic"] for extension in MARKITDOWN_GENERIC_EXTENSIONS}


def _build_markitdown_generic_availability() -> dict[str, dict[str, bool]]:
    return {
        extension: {"markitdown_generic": GENERIC_MARKITDOWN_AVAILABLE}
        for extension in MARKITDOWN_GENERIC_EXTENSIONS
    }


PARSER_REGISTRY: dict[str, dict[str, Parser]] = {
    ".pdf": {
        "pymupdf_ocr_vision": parse_pdf_with_pymupdf_ocr_vision,
        "pymupdf4llm": parse_pdf_with_pymupdf4llm,
        "pdfplumber": parse_pdf_with_pdfplumber,
        "markitdown": parse_pdf_with_markitdown,
        "pymupdf_native": parse_pdf_with_pymupdf_native,
    },
    ".docx": {
        "mammoth": parse_docx_with_mammoth,
        "markitdown": parse_docx_with_markitdown,
        "docx_native": parse_docx_with_native,
    },
    ".ppt": {
        "markitdown": parse_pptx_with_markitdown,
        "python_pptx_native": parse_pptx_with_python_pptx,
    },
    ".pptx": {
        "markitdown": parse_pptx_with_markitdown,
        "python_pptx_native": parse_pptx_with_python_pptx,
    },
    ".png": {
        "llm_vision": parse_image_with_llm_vision,
    },
    ".jpg": {
        "llm_vision": parse_image_with_llm_vision,
    },
    ".jpeg": {
        "llm_vision": parse_image_with_llm_vision,
    },
    ".webp": {
        "llm_vision": parse_image_with_llm_vision,
    },
    ".gif": {
        "llm_vision": parse_image_with_llm_vision,
    },
    ".bmp": {
        "llm_vision": parse_image_with_llm_vision,
    },
    ".tif": {
        "llm_vision": parse_image_with_llm_vision,
    },
    ".tiff": {
        "llm_vision": parse_image_with_llm_vision,
    },
    **_build_audio_parser_mapping(),
    **_build_markitdown_generic_mapping(),
    **_build_text_parser_mapping(),
}

DEFAULT_PARSER_CHAIN: dict[str, list[str]] = {
    ".pdf": ["pymupdf_native", "pymupdf4llm", "pdfplumber", "markitdown"],
    ".docx": ["markitdown", "mammoth", "docx_native"],
    ".ppt": ["markitdown", "python_pptx_native"],
    ".pptx": ["markitdown", "python_pptx_native"],
    ".png": ["llm_vision"],
    ".jpg": ["llm_vision"],
    ".jpeg": ["llm_vision"],
    ".webp": ["llm_vision"],
    ".gif": ["llm_vision"],
    ".bmp": ["llm_vision"],
    ".tif": ["llm_vision"],
    ".tiff": ["llm_vision"],
    **_build_audio_parser_chain(),
    **_build_markitdown_generic_chain(),
    **_build_text_parser_chain(),
}

_PARSER_AVAILABILITY: dict[str, dict[str, bool]] = {
    ".pdf": {
        "pymupdf_ocr_vision": PDF_PYMUPDF_OCR_VISION_AVAILABLE,
        "pymupdf4llm": PDF_PYMUPDF4LLM_AVAILABLE,
        "pdfplumber": PDF_PDFPLUMBER_AVAILABLE,
        "markitdown": PDF_MARKITDOWN_AVAILABLE,
        "pymupdf_native": PDF_PYMUPDF_NATIVE_AVAILABLE,
    },
    ".docx": {
        "mammoth": DOCX_MAMMOTH_AVAILABLE,
        "markitdown": DOCX_MARKITDOWN_AVAILABLE,
        "docx_native": DOCX_NATIVE_AVAILABLE,
    },
    ".ppt": {
        "markitdown": PPTX_MARKITDOWN_AVAILABLE,
        "python_pptx_native": PPTX_NATIVE_AVAILABLE,
    },
    ".pptx": {
        "markitdown": PPTX_MARKITDOWN_AVAILABLE,
        "python_pptx_native": PPTX_NATIVE_AVAILABLE,
    },
    **_build_audio_parser_availability(),
    **_build_markitdown_generic_availability(),
    **_build_text_parser_availability(),
}

SUPPORTED_EXTENSIONS = frozenset(PARSER_REGISTRY)


def resolve_parser_extension(file_path: str | Path, extension: str) -> str:
    """Resolve an extension into a parser-registry key."""

    normalized = normalize_extension(extension)
    if normalized in PARSER_REGISTRY:
        return normalized
    if is_probably_text_file(file_path):
        return TEXT_FALLBACK_EXTENSION
    return normalized


def get_available_parsers(extension: str, *, allow_llm_vision: bool) -> list[str]:
    """Return parser names that are runnable in the current environment."""

    normalized = normalize_extension(extension)
    available = _PARSER_AVAILABILITY.get(normalized)
    if available is None:
        parser_def = PARSER_REGISTRY.get(normalized, {})
        return [
            name
            for name in parser_def
            if name != "llm_vision" or allow_llm_vision
        ]

    parser_names = [name for name, is_available in available.items() if is_available]
    if normalized in PARSER_REGISTRY and "llm_vision" in PARSER_REGISTRY[normalized] and allow_llm_vision:
        parser_names.append("llm_vision")
    return parser_names


# ── Startup logging (改进 5: MinerU auto-engine 思路) ──

_logger = structlog.get_logger()


def log_parser_availability() -> None:
    """Log all parsers and their availability status at startup.

    Helps operators quickly see which parsers are usable in the current
    environment. Missing packages result in degraded capability, not crashes.
    """
    core_parsers = {
        "pymupdf_native": PDF_PYMUPDF_NATIVE_AVAILABLE,
        "pymupdf4llm": PDF_PYMUPDF4LLM_AVAILABLE,
        "pdfplumber": PDF_PDFPLUMBER_AVAILABLE,
        "pymupdf_ocr_vision": PDF_PYMUPDF_OCR_VISION_AVAILABLE,
        "markitdown (pdf)": PDF_MARKITDOWN_AVAILABLE,
        "mammoth (docx)": DOCX_MAMMOTH_AVAILABLE,
        "docx_native": DOCX_NATIVE_AVAILABLE,
        "markitdown (docx)": DOCX_MARKITDOWN_AVAILABLE,
        "python_pptx_native": PPTX_NATIVE_AVAILABLE,
        "markitdown (pptx)": PPTX_MARKITDOWN_AVAILABLE,
        "markitdown_generic": GENERIC_MARKITDOWN_AVAILABLE,
        "text_native": TEXT_NATIVE_AVAILABLE,
        "audio_transcription": AUDIO_NATIVE_AVAILABLE,
    }

    available = [name for name, ok in core_parsers.items() if ok]
    missing = [name for name, ok in core_parsers.items() if not ok]

    _logger.info(
        "parser_availability_summary",
        available_count=len(available),
        missing_count=len(missing),
        available=available,
        missing=missing or None,
    )
