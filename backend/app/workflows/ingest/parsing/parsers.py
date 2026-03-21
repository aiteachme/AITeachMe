"""Named parser registry and capability helpers for ingest workflows."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path

from app.workflows.ingest.parsing.docx import (
    DOCX_MARKITDOWN_AVAILABLE,
    DOCX_NATIVE_AVAILABLE,
    parse_docx_with_markitdown,
    parse_docx_with_native,
)
from app.workflows.ingest.parsing.formats import TEXT_EXTENSIONS, normalize_extension
from app.workflows.ingest.parsing.image import parse_image_with_llm_vision
from app.workflows.ingest.parsing.pdf import (
    PDF_MARKITDOWN_AVAILABLE,
    PDF_PYMUPDF4LLM_AVAILABLE,
    PDF_PYMUPDF_NATIVE_AVAILABLE,
    parse_pdf_with_markitdown,
    parse_pdf_with_pymupdf4llm,
    parse_pdf_with_pymupdf_native,
)
from app.workflows.ingest.parsing.pptx import (
    PPTX_MARKITDOWN_AVAILABLE,
    PPTX_NATIVE_AVAILABLE,
    parse_pptx_with_markitdown,
    parse_pptx_with_python_pptx,
)
from app.workflows.ingest.parsing.text import (
    TEXT_FALLBACK_EXTENSION,
    TEXT_NATIVE_AVAILABLE,
    is_probably_text_file,
    parse_text_with_native,
)
from app.workflows.ingest.parsing.types import ParserRunOptions

Parser = Callable[[str | Path, Path, ParserRunOptions], Awaitable[str]]


def _build_text_parser_mapping() -> dict[str, dict[str, Parser]]:
    return {extension: {"text_native": parse_text_with_native} for extension in TEXT_EXTENSIONS}


def _build_text_parser_chain() -> dict[str, list[str]]:
    return {extension: ["text_native"] for extension in TEXT_EXTENSIONS}


def _build_text_parser_availability() -> dict[str, dict[str, bool]]:
    return {extension: {"text_native": TEXT_NATIVE_AVAILABLE} for extension in TEXT_EXTENSIONS}


PARSER_REGISTRY: dict[str, dict[str, Parser]] = {
    ".pdf": {
        "pymupdf4llm": parse_pdf_with_pymupdf4llm,
        "markitdown": parse_pdf_with_markitdown,
        "pymupdf_native": parse_pdf_with_pymupdf_native,
    },
    ".docx": {
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
    **_build_text_parser_mapping(),
}

DEFAULT_PARSER_CHAIN: dict[str, list[str]] = {
    ".pdf": ["pymupdf4llm", "markitdown", "pymupdf_native"],
    ".docx": ["markitdown", "docx_native"],
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
    **_build_text_parser_chain(),
}

_PARSER_AVAILABILITY: dict[str, dict[str, bool]] = {
    ".pdf": {
        "pymupdf4llm": PDF_PYMUPDF4LLM_AVAILABLE,
        "markitdown": PDF_MARKITDOWN_AVAILABLE,
        "pymupdf_native": PDF_PYMUPDF_NATIVE_AVAILABLE,
    },
    ".docx": {
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
        return ["llm_vision"] if allow_llm_vision and normalized in PARSER_REGISTRY else []

    parser_names = [name for name, is_available in available.items() if is_available]
    if normalized in PARSER_REGISTRY and "llm_vision" in PARSER_REGISTRY[normalized] and allow_llm_vision:
        parser_names.append("llm_vision")
    return parser_names
