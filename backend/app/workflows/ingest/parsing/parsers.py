"""Named parser registry and capability helpers for ingest workflows."""

from __future__ import annotations

import structlog

from collections.abc import Awaitable, Callable
from importlib import import_module
from importlib.util import find_spec
from pathlib import Path

from app.shared.infra.exceptions import FileParseError
from app.workflows.ingest.parsing.audio import (
    AUDIO_NATIVE_AVAILABLE,
    is_audio_transcription_available,
    parse_audio_with_transcription,
)
from app.workflows.ingest.parsing.doc import (
    DOC_SOFFICE_AVAILABLE,
    DOC_VIA_DOCX_AVAILABLE,
    DOC_WORD_COM_AVAILABLE,
    parse_doc_with_markitdown,
    parse_doc_with_mammoth,
    parse_doc_with_native,
)
from app.workflows.ingest.parsing.docx import (
    DOCX_MARKITDOWN_AVAILABLE,
    DOCX_NATIVE_AVAILABLE,
    parse_docx_with_markitdown,
    parse_docx_with_native,
)
from app.workflows.ingest.parsing.docx_mammoth import (
    DOCX_MAMMOTH_AVAILABLE,
    parse_docx_with_mammoth,
)
from app.workflows.ingest.parsing.formats import AUDIO_EXTENSIONS, MARKITDOWN_GENERIC_EXTENSIONS, TEXT_EXTENSIONS, normalize_extension
from app.workflows.ingest.parsing.generic import (
    GENERIC_MARKITDOWN_AVAILABLE,
    parse_with_markitdown_generic,
)
from app.workflows.ingest.parsing.image import parse_image_with_llm_vision
from app.workflows.ingest.parsing.features import builtin_pdf_parsing_enabled
from app.workflows.ingest.parsing.pptx import (
    PPTX_MARKITDOWN_AVAILABLE,
    PPTX_NATIVE_AVAILABLE,
    parse_pptx_with_markitdown,
    parse_pptx_with_python_pptx,
)
from app.workflows.ingest.parsing.ppt_ocr import (
    PPT_OCR_VISION_AVAILABLE,
    parse_ppt_with_ocr_vision,
)
from app.workflows.ingest.parsing.text import (
    TEXT_FALLBACK_EXTENSION,
    TEXT_NATIVE_AVAILABLE,
    is_probably_text_file,
    parse_text_with_native,
)
from app.workflows.ingest.parsing.types import ParserRunOptions

Parser = Callable[[str | Path, Path, ParserRunOptions], Awaitable[str]]

_PDF_PARSER_IMPORTS: dict[str, tuple[str, str]] = {
    "ocr_vision": (
        "app.workflows.ingest.parsing.pdf",
        "parse_pdf_with_pymupdf_ocr_vision",
    ),
    "pymupdf_ocr_vision": (
        "app.workflows.ingest.parsing.pdf",
        "parse_pdf_with_pymupdf_ocr_vision",
    ),
    "pymupdf4llm": (
        "app.workflows.ingest.parsing.pdf",
        "parse_pdf_with_pymupdf4llm",
    ),
    "pdfplumber": (
        "app.workflows.ingest.parsing.pdf_pdfplumber",
        "parse_pdf_with_pdfplumber",
    ),
    "markitdown": (
        "app.workflows.ingest.parsing.pdf",
        "parse_pdf_with_markitdown",
    ),
    "pymupdf_native": (
        "app.workflows.ingest.parsing.pdf",
        "parse_pdf_with_pymupdf_native",
    ),
}

_PDF_PARSER_PACKAGE_SPECS: dict[str, tuple[str, ...]] = {
    "ocr_vision": ("fitz",),
    "pymupdf_ocr_vision": ("fitz",),
    "pymupdf4llm": ("pymupdf4llm",),
    "pdfplumber": ("pdfplumber",),
    "markitdown": ("markitdown",),
    "pymupdf_native": ("fitz",),
}


def _packages_available(package_names: tuple[str, ...]) -> bool:
    return all(find_spec(package_name) is not None for package_name in package_names)


def _pdf_parser_available(parser_name: str) -> bool:
    if not builtin_pdf_parsing_enabled():
        return False
    package_names = _PDF_PARSER_PACKAGE_SPECS.get(parser_name)
    return bool(package_names and _packages_available(package_names))


async def _parse_pdf_with(
    parser_name: str,
    file_path: str | Path,
    asset_dir: Path,
    options: ParserRunOptions,
) -> str:
    if not builtin_pdf_parsing_enabled():
        raise FileParseError(
            Path(file_path).name,
            reason="Built-in PDF parsing is disabled. Install the PDF parser plugin to parse PDF files.",
        )

    module_name, function_name = _PDF_PARSER_IMPORTS[parser_name]
    parser = getattr(import_module(module_name), function_name)
    return await parser(file_path, asset_dir, options)


async def parse_pdf_with_pymupdf_ocr_vision(
    file_path: str | Path,
    asset_dir: Path,
    options: ParserRunOptions,
) -> str:
    return await _parse_pdf_with("pymupdf_ocr_vision", file_path, asset_dir, options)


async def parse_pdf_with_pymupdf4llm(
    file_path: str | Path,
    asset_dir: Path,
    options: ParserRunOptions,
) -> str:
    return await _parse_pdf_with("pymupdf4llm", file_path, asset_dir, options)


async def parse_pdf_with_pdfplumber(
    file_path: str | Path,
    asset_dir: Path,
    options: ParserRunOptions,
) -> str:
    return await _parse_pdf_with("pdfplumber", file_path, asset_dir, options)


async def parse_pdf_with_markitdown(
    file_path: str | Path,
    asset_dir: Path,
    options: ParserRunOptions,
) -> str:
    return await _parse_pdf_with("markitdown", file_path, asset_dir, options)


async def parse_pdf_with_pymupdf_native(
    file_path: str | Path,
    asset_dir: Path,
    options: ParserRunOptions,
) -> str:
    return await _parse_pdf_with("pymupdf_native", file_path, asset_dir, options)


def _build_pdf_parser_mapping() -> dict[str, dict[str, Parser]]:
    if not builtin_pdf_parsing_enabled():
        return {}
    return {
        ".pdf": {
            "ocr_vision": parse_pdf_with_pymupdf_ocr_vision,
            "pymupdf_ocr_vision": parse_pdf_with_pymupdf_ocr_vision,
            "pymupdf4llm": parse_pdf_with_pymupdf4llm,
            "pdfplumber": parse_pdf_with_pdfplumber,
            "markitdown": parse_pdf_with_markitdown,
            "pymupdf_native": parse_pdf_with_pymupdf_native,
        }
    }


def _build_pdf_parser_chain() -> dict[str, list[str]]:
    if not builtin_pdf_parsing_enabled():
        return {}
    return {
        ".pdf": ["pymupdf_native", "pymupdf4llm", "pdfplumber", "markitdown"],
    }


def _build_pdf_parser_availability() -> dict[str, dict[str, bool]]:
    if not builtin_pdf_parsing_enabled():
        return {}
    return {
        ".pdf": {
            "pymupdf_ocr_vision": _pdf_parser_available("pymupdf_ocr_vision"),
            "pymupdf4llm": _pdf_parser_available("pymupdf4llm"),
            "pdfplumber": _pdf_parser_available("pdfplumber"),
            "markitdown": _pdf_parser_available("markitdown"),
            "pymupdf_native": _pdf_parser_available("pymupdf_native"),
        }
    }


def _build_text_parser_mapping() -> dict[str, dict[str, Parser]]:
    return {extension: {"text_native": parse_text_with_native} for extension in TEXT_EXTENSIONS}


def _build_text_parser_chain() -> dict[str, list[str]]:
    return {extension: ["text_native"] for extension in TEXT_EXTENSIONS}


def _build_text_parser_availability() -> dict[str, dict[str, bool]]:
    return {extension: {"text_native": TEXT_NATIVE_AVAILABLE} for extension in TEXT_EXTENSIONS}


def _build_audio_parser_mapping() -> dict[str, dict[str, Parser]]:
    # 功能尚未扩展链路：当前上传白名单不允许音频文件。
    # AI 提示：除非任务明确要求恢复音频上传，否则可以先不读这组 helper。
    return {extension: {"audio_transcription": parse_audio_with_transcription} for extension in AUDIO_EXTENSIONS}


def _build_audio_parser_chain() -> dict[str, list[str]]:
    # 功能尚未扩展链路：当前上传白名单不允许音频文件。
    return {extension: ["audio_transcription"] for extension in AUDIO_EXTENSIONS}


def _build_audio_parser_availability() -> dict[str, dict[str, bool]]:
    # 功能尚未扩展链路：当前上传白名单不允许音频文件。
    return {
        extension: {"audio_transcription": is_audio_transcription_available(extension)}
        for extension in AUDIO_EXTENSIONS
    }


def _build_markitdown_generic_mapping() -> dict[str, dict[str, Parser]]:
    # demo / 未扩展链路：当前上传白名单不会走到通用 MarkItDown 格式。
    # AI 提示：如果任务不是恢复 xls/html/csv 等上传，可以跳过这组 helper。
    return {
        extension: {"markitdown_generic": parse_with_markitdown_generic}
        for extension in MARKITDOWN_GENERIC_EXTENSIONS
    }


def _build_markitdown_generic_chain() -> dict[str, list[str]]:
    # demo / 未扩展链路：当前上传白名单不会走到通用 MarkItDown 格式。
    return {extension: ["markitdown_generic"] for extension in MARKITDOWN_GENERIC_EXTENSIONS}


def _build_markitdown_generic_availability() -> dict[str, dict[str, bool]]:
    # demo / 未扩展链路：当前上传白名单不会走到通用 MarkItDown 格式。
    return {
        extension: {"markitdown_generic": GENERIC_MARKITDOWN_AVAILABLE}
        for extension in MARKITDOWN_GENERIC_EXTENSIONS
    }


PARSER_REGISTRY: dict[str, dict[str, Parser]] = {
    **_build_pdf_parser_mapping(),
    # 旧链路：.doc 已停用，不再支持上传和解析。
    # AI 提示：除非任务明确要求恢复 .doc 支持，否则可以先不读这些 parser。
    # ".doc": {
    #     "doc_markitdown": parse_doc_with_markitdown,
    #     "doc_mammoth": parse_doc_with_mammoth,
    #     "doc_native": parse_doc_with_native,
    # },
    ".docx": {
        "mammoth": parse_docx_with_mammoth,
        "markitdown": parse_docx_with_markitdown,
        "docx_native": parse_docx_with_native,
    },
    ".ppt": {
        "ocr_vision": parse_ppt_with_ocr_vision,
        "markitdown": parse_pptx_with_markitdown,
        "python_pptx_native": parse_pptx_with_python_pptx,
    },
    ".pptx": {
        "ocr_vision": parse_ppt_with_ocr_vision,
        "markitdown": parse_pptx_with_markitdown,
        "python_pptx_native": parse_pptx_with_python_pptx,
    },
    # 未扩展链路：当前上传白名单不开放图片直传解析。
    # AI 提示：如果任务没有要求恢复图片上传，可以先不读 raw image parser 细节。
    # ".png": {
    #     "llm_vision": parse_image_with_llm_vision,
    # },
    # ".jpg": {
    #     "llm_vision": parse_image_with_llm_vision,
    # },
    # ".jpeg": {
    #     "llm_vision": parse_image_with_llm_vision,
    # },
    # ".webp": {
    #     "llm_vision": parse_image_with_llm_vision,
    # },
    # ".gif": {
    #     "llm_vision": parse_image_with_llm_vision,
    # },
    # ".bmp": {
    #     "llm_vision": parse_image_with_llm_vision,
    # },
    # ".tif": {
    #     "llm_vision": parse_image_with_llm_vision,
    # },
    # ".tiff": {
    #     "llm_vision": parse_image_with_llm_vision,
    # },
    # 功能尚未扩展链路：当前上传白名单不开放音频直传解析。
    # **_build_audio_parser_mapping(),
    # demo / 未扩展链路：当前上传白名单不开放通用 MarkItDown 格式。
    # **_build_markitdown_generic_mapping(),
    **_build_text_parser_mapping(),
}

DEFAULT_PARSER_CHAIN: dict[str, list[str]] = {
    **_build_pdf_parser_chain(),
    # 旧链路：.doc 已停用，不再支持上传和解析。
    # ".doc": ["doc_markitdown", "doc_mammoth", "doc_native"],
    ".docx": ["markitdown", "mammoth", "docx_native"],
    ".ppt": ["markitdown", "python_pptx_native"],
    ".pptx": ["markitdown", "python_pptx_native"],
    # 未扩展链路：当前上传白名单不开放图片直传解析。
    # ".png": ["llm_vision"],
    # ".jpg": ["llm_vision"],
    # ".jpeg": ["llm_vision"],
    # ".webp": ["llm_vision"],
    # ".gif": ["llm_vision"],
    # ".bmp": ["llm_vision"],
    # ".tif": ["llm_vision"],
    # ".tiff": ["llm_vision"],
    # 功能尚未扩展链路：当前上传白名单不开放音频直传解析。
    # **_build_audio_parser_chain(),
    # demo / 未扩展链路：当前上传白名单不开放通用 MarkItDown 格式。
    # **_build_markitdown_generic_chain(),
    **_build_text_parser_chain(),
}

_PARSER_AVAILABILITY: dict[str, dict[str, bool]] = {
    **_build_pdf_parser_availability(),
    # 旧链路：.doc 已停用，不再支持上传和解析。
    # ".doc": {
    #     "doc_markitdown": DOCX_MARKITDOWN_AVAILABLE,
    #     "doc_mammoth": DOCX_MAMMOTH_AVAILABLE,
    #     "doc_native": DOCX_NATIVE_AVAILABLE,
    # },
    ".docx": {
        "mammoth": DOCX_MAMMOTH_AVAILABLE,
        "markitdown": DOCX_MARKITDOWN_AVAILABLE,
        "docx_native": DOCX_NATIVE_AVAILABLE,
    },
    ".ppt": {
        "ocr_vision": PPT_OCR_VISION_AVAILABLE,
        "markitdown": PPTX_MARKITDOWN_AVAILABLE,
        "python_pptx_native": PPTX_NATIVE_AVAILABLE,
    },
    ".pptx": {
        "ocr_vision": PPT_OCR_VISION_AVAILABLE,
        "markitdown": PPTX_MARKITDOWN_AVAILABLE,
        "python_pptx_native": PPTX_NATIVE_AVAILABLE,
    },
    # 功能尚未扩展链路：当前上传白名单不开放音频直传解析。
    # **_build_audio_parser_availability(),
    # demo / 未扩展链路：当前上传白名单不开放通用 MarkItDown 格式。
    # **_build_markitdown_generic_availability(),
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


def resolve_markitdown_parser_name(extension: str) -> str | None:
    """Return the MarkItDown parser registered for an extension, if runnable."""

    normalized = normalize_extension(extension)
    available = get_available_parsers(normalized, allow_llm_vision=False)
    if "doc_markitdown" in available:
        return "doc_markitdown"
    if "markitdown" in available:
        return "markitdown"
    if "markitdown_generic" in available:
        return "markitdown_generic"
    return None


def is_markitdown_available_for_extension(extension: str) -> bool:
    return resolve_markitdown_parser_name(extension) is not None


# ── Startup logging (改进 5: MinerU auto-engine 思路) ──

_logger = structlog.get_logger()


def log_parser_availability() -> None:
    """Log all parsers and their availability status at startup.

    Helps operators quickly see which parsers are usable in the current
    environment. Missing packages result in degraded capability, not crashes.
    """
    core_parsers = {
        # 旧链路：.doc 已停用，不再支持上传和解析。
        # "doc_via_docx": DOC_VIA_DOCX_AVAILABLE,
        # "doc_word_com": DOC_WORD_COM_AVAILABLE,
        # "doc_soffice": DOC_SOFFICE_AVAILABLE,
        "pymupdf_native": _pdf_parser_available("pymupdf_native"),
        "pymupdf4llm": _pdf_parser_available("pymupdf4llm"),
        "pdfplumber": _pdf_parser_available("pdfplumber"),
        "pymupdf_ocr_vision": _pdf_parser_available("pymupdf_ocr_vision"),
        "markitdown (pdf)": _pdf_parser_available("markitdown"),
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
