"""Named parser registry for ingest workflows."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path

from app.workflows.ingest.parse_docx import (
    parse_docx_with_markitdown,
    parse_docx_with_python_docx,
)
from app.workflows.ingest.parse_image import parse_image_with_llm_vision
from app.workflows.ingest.parse_pdf import (
    parse_pdf_with_markitdown,
    parse_pdf_with_pymupdf4llm,
    parse_pdf_with_pymupdf_native,
)
from app.workflows.ingest.parse_pptx import (
    parse_pptx_with_markitdown,
    parse_pptx_with_python_pptx,
)


Parser = Callable[[str | Path, Path], Awaitable[str]]

PARSER_REGISTRY: dict[str, dict[str, Parser]] = {
    ".pdf": {
        "pymupdf4llm": parse_pdf_with_pymupdf4llm,
        "markitdown": parse_pdf_with_markitdown,
        "pymupdf_native": parse_pdf_with_pymupdf_native,
    },
    ".docx": {
        "markitdown": parse_docx_with_markitdown,
        "python_docx_native": parse_docx_with_python_docx,
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
}

DEFAULT_PARSER_CHAIN: dict[str, list[str]] = {
    ".pdf": ["pymupdf4llm", "markitdown", "pymupdf_native"],
    ".docx": ["markitdown", "python_docx_native"],
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
}

SUPPORTED_EXTENSIONS = frozenset(PARSER_REGISTRY)
