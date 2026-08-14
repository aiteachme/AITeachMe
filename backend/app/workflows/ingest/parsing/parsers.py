"""Named parser registry and capability helpers for ingest workflows."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from importlib import import_module
from importlib.util import find_spec
from pathlib import Path

from app.shared.infra.exceptions import FileParseError
from app.workflows.ingest.parsing.lib.features import builtin_pdf_parsing_enabled
from app.workflows.ingest.parsing.lib.formats import TEXT_EXTENSIONS, normalize_extension
from app.workflows.ingest.parsing.text import (
    TEXT_FALLBACK_EXTENSION,
    TEXT_NATIVE_AVAILABLE,
    is_probably_text_file,
    parse_text_with_native,
)
from app.workflows.ingest.parsing.lib.types import ParserRunOptions

Parser = Callable[[str | Path, Path, ParserRunOptions], Awaitable[str]]


def _module_available(module_name: str) -> bool:
    return find_spec(module_name) is not None


def _packages_available(package_names: tuple[str, ...]) -> bool:
    return all(_module_available(package_name) for package_name in package_names)


def _lazy_parser(module_name: str, function_name: str) -> Parser:
    async def _parser(file_path: str | Path, asset_dir: Path, options: ParserRunOptions) -> str:
        parser = getattr(import_module(module_name), function_name)
        return await parser(file_path, asset_dir, options)

    _parser.__name__ = function_name
    return _parser


DOCX_NATIVE_AVAILABLE = True
DOCX_MARKITDOWN_AVAILABLE = _packages_available(("markitdown", "mammoth"))
DOCX_MAMMOTH_AVAILABLE = _module_available("mammoth")
PPTX_MARKITDOWN_AVAILABLE = _packages_available(("markitdown", "pptx"))

_PDF_PARSER_IMPORTS: dict[str, tuple[str, str]] = {
    "markitdown": (
        "app.workflows.ingest.parsing.pdf_markitdown",
        "parse_pdf_with_markitdown",
    ),
}

_PDF_PARSER_PACKAGE_SPECS: dict[str, tuple[str, ...]] = {
    "markitdown": ("markitdown", "pdfplumber"),
}


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
            reason="Built-in PDF parsing is disabled. Configure MinerU/PaddleOCR or enable local PDF parsing.",
        )
    if not _pdf_parser_available(parser_name):
        raise FileParseError(Path(file_path).name, reason=f"PDF parser {parser_name!r} is not available.")

    module_name, function_name = _PDF_PARSER_IMPORTS[parser_name]
    parser = getattr(import_module(module_name), function_name)
    return await parser(file_path, asset_dir, options)


async def parse_pdf_with_markitdown(
    file_path: str | Path,
    asset_dir: Path,
    options: ParserRunOptions,
) -> str:
    return await _parse_pdf_with("markitdown", file_path, asset_dir, options)


def _build_pdf_parser_mapping() -> dict[str, dict[str, Parser]]:
    if not builtin_pdf_parsing_enabled():
        return {}
    return {
        ".pdf": {
            "markitdown": parse_pdf_with_markitdown,
        }
    }


def _build_pdf_parser_chain() -> dict[str, list[str]]:
    if not builtin_pdf_parsing_enabled():
        return {}
    return {
        ".pdf": ["markitdown"],
    }


def _build_pdf_parser_availability() -> dict[str, dict[str, bool]]:
    if not builtin_pdf_parsing_enabled():
        return {}
    return {
        ".pdf": {
            "markitdown": _pdf_parser_available("markitdown"),
        }
    }


def _build_text_parser_mapping() -> dict[str, dict[str, Parser]]:
    return {extension: {"text_native": parse_text_with_native} for extension in TEXT_EXTENSIONS}


def _build_text_parser_chain() -> dict[str, list[str]]:
    return {extension: ["text_native"] for extension in TEXT_EXTENSIONS}


def _build_text_parser_availability() -> dict[str, dict[str, bool]]:
    return {extension: {"text_native": TEXT_NATIVE_AVAILABLE} for extension in TEXT_EXTENSIONS}


PARSER_REGISTRY: dict[str, dict[str, Parser]] = {
    **_build_pdf_parser_mapping(),
    ".docx": {
        "markitdown": _lazy_parser("app.workflows.ingest.parsing.docx", "parse_docx_with_markitdown"),
        "mammoth": _lazy_parser("app.workflows.ingest.parsing.docx_mammoth", "parse_docx_with_mammoth"),
        "docx_native": _lazy_parser("app.workflows.ingest.parsing.docx", "parse_docx_with_native"),
    },
    ".pptx": {
        "markitdown": _lazy_parser("app.workflows.ingest.parsing.pptx_markitdown", "parse_pptx_with_markitdown"),
    },
    **_build_text_parser_mapping(),
}

DEFAULT_PARSER_CHAIN: dict[str, list[str]] = {
    **_build_pdf_parser_chain(),
    ".docx": ["mammoth", "docx_native"],
    ".pptx": ["markitdown"],
    **_build_text_parser_chain(),
}

_PARSER_AVAILABILITY: dict[str, dict[str, bool]] = {
    **_build_pdf_parser_availability(),
    ".docx": {
        "markitdown": DOCX_MARKITDOWN_AVAILABLE,
        "mammoth": DOCX_MAMMOTH_AVAILABLE,
        "docx_native": DOCX_NATIVE_AVAILABLE,
    },
    ".pptx": {
        "markitdown": PPTX_MARKITDOWN_AVAILABLE,
    },
    **_build_text_parser_availability(),
}


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
    return [name for name, is_available in available.items() if is_available]


def resolve_markitdown_parser_name(extension: str) -> str | None:
    """Return the MarkItDown parser registered for an extension, if runnable."""

    normalized = normalize_extension(extension)
    available = get_available_parsers(normalized, allow_llm_vision=False)
    if "markitdown" in available:
        return "markitdown"
    return None


def is_markitdown_available_for_extension(extension: str) -> bool:
    return resolve_markitdown_parser_name(extension) is not None


__all__ = [
    "DEFAULT_PARSER_CHAIN",
    "PARSER_REGISTRY",
    "get_available_parsers",
    "is_markitdown_available_for_extension",
    "parse_pdf_with_markitdown",
    "resolve_markitdown_parser_name",
    "resolve_parser_extension",
]
