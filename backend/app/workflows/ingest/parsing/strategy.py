"""Parser planning and capability-aware routing for ingest workflows."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.exceptions import MissingLLMApiKeyError, UnsupportedFileTypeError
from app.workflows.ingest.parsing.classifier import ClassificationResult
from app.workflows.ingest.parsing.formats import (
    categorize_text_extension,
    is_image_extension,
    is_text_extension,
    normalize_extension,
)
from app.workflows.ingest.parsing.parsers import (
    DEFAULT_PARSER_CHAIN,
    get_available_parsers,
    resolve_parser_extension,
)
from app.workflows.ingest.parsing.types import ParserRunOptions

_LARGE_FILE_MB = 20
_LARGE_DOC_PAGES = 120
_MEDIUM_DOC_PAGES = 40
_LARGE_SLIDE_COUNT = 80
_LARGE_DOCX_PAGE_COUNT = 60
_VISION_MAX_MB = 8
class ParsePlan(BaseModel):
    """Materialized parser execution plan stored in workflow state."""

    mode: str
    parser_chain: list[str] = Field(default_factory=list)
    decision_reason: str
    options: ParserRunOptions = Field(default_factory=ParserRunOptions)


def build_parse_plan(
    *,
    file_path: str | Path,
    filetype: str,
    file_size_bytes: int | None,
    classification: ClassificationResult | None,
) -> ParsePlan:
    """Choose parser chain and runtime budget from file signals and capabilities."""

    settings = get_settings()
    extension = resolve_parser_extension(file_path, normalize_extension(filetype))
    allow_llm_vision = bool(settings.llm_api_key)
    available_parsers = get_available_parsers(extension, allow_llm_vision=allow_llm_vision)
    if not available_parsers:
        if is_image_extension(extension):
            raise MissingLLMApiKeyError()
        raise UnsupportedFileTypeError(extension)

    file_mb = round((file_size_bytes or 0) / (1024 * 1024), 2)
    estimated_pages = classification.estimated_pages if classification else 0
    options = ParserRunOptions(timeout_s=settings.ingest_parser_timeout_s)
    preferred_order = _preferred_parser_order(
        extension=extension,
        file_mb=file_mb,
        estimated_pages=estimated_pages,
        classification=classification,
        llm_enabled=allow_llm_vision,
    )

    parser_chain = [name for name in preferred_order if name in available_parsers]
    if not parser_chain:
        parser_chain = [name for name in DEFAULT_PARSER_CHAIN.get(extension, []) if name in available_parsers]
    if not parser_chain:
        raise UnsupportedFileTypeError(extension)

    mode, reason = _decide_mode_and_options(
        extension=extension,
        file_mb=file_mb,
        estimated_pages=estimated_pages,
        classification=classification,
        options=options,
    )
    return ParsePlan(
        mode=mode,
        parser_chain=parser_chain,
        decision_reason=reason,
        options=options,
    )


def _preferred_parser_order(
    *,
    extension: str,
    file_mb: float,
    estimated_pages: int,
    classification: ClassificationResult | None,
    llm_enabled: bool,
) -> list[str]:
    if is_image_extension(extension):
        if not llm_enabled:
            return []
        return ["llm_vision"]

    if is_text_extension(extension):
        return ["text_native"]

    if extension == ".pdf":
        if classification and classification.file_category == "scanned_pdf":
            return ["pymupdf_native", "markitdown", "pymupdf4llm"]
        if file_mb >= _LARGE_FILE_MB or estimated_pages >= _LARGE_DOC_PAGES:
            return ["pymupdf_native", "pymupdf4llm", "markitdown"]
        if classification and (classification.has_tables or classification.has_formulas):
            return ["pymupdf4llm", "pymupdf_native", "markitdown"]
        return _classification_first(classification, extension)

    if extension == ".docx":
        if file_mb >= 10 or estimated_pages >= _LARGE_DOCX_PAGE_COUNT:
            return ["docx_native", "markitdown"]
        return _classification_first(classification, extension)

    if extension in {".ppt", ".pptx"}:
        if file_mb >= 15 or estimated_pages >= _LARGE_SLIDE_COUNT:
            return ["python_pptx_native", "markitdown"]
        return _classification_first(classification, extension)

    return _classification_first(classification, extension)


def _classification_first(
    classification: ClassificationResult | None,
    extension: str,
) -> list[str]:
    preferred_order: list[str] = []
    if classification is not None:
        preferred_order.extend([classification.recommended_parser, *classification.fallback_parsers])
    preferred_order.extend(DEFAULT_PARSER_CHAIN.get(extension, []))
    return list(dict.fromkeys(name for name in preferred_order if name))


def _decide_mode_and_options(
    *,
    extension: str,
    file_mb: float,
    estimated_pages: int,
    classification: ClassificationResult | None,
    options: ParserRunOptions,
) -> tuple[str, str]:
    if is_image_extension(extension):
        if file_mb > _VISION_MAX_MB:
            options.timeout_s = max(options.timeout_s, 150)
            return "vision_large_image", "Image file routed to LLM vision with extended timeout."
        options.asset_image_limit = 1
        return "vision_image", "Image file routed directly to LLM vision."

    if is_text_extension(extension):
        options.asset_image_limit = 0
        text_category = categorize_text_extension(extension)
        if text_category == "markdown":
            return "native_markdown", "Markdown file is normalized directly without document conversion."
        if text_category == "structured_text":
            return "native_structured_text", "Structured text file is preserved inside fenced markdown."
        return "native_text", "Text file is normalized directly without document conversion."

    if extension == ".pdf":
        if classification and classification.file_category == "scanned_pdf":
            options.asset_image_limit = 8
            options.timeout_s = min(options.timeout_s, 75)
            return "fast_scanned_pdf", "Scanned PDF prefers native text-plus-image extraction."
        if file_mb >= _LARGE_FILE_MB or estimated_pages >= _LARGE_DOC_PAGES:
            options.asset_image_limit = 12
            options.skip_image_supplement = True
            options.timeout_s = max(options.timeout_s, 120)
            return "fast_large_pdf", "Large PDF uses faster parser order and caps image extraction."
        if estimated_pages >= _MEDIUM_DOC_PAGES:
            options.asset_image_limit = 16
            return "balanced_medium_pdf", "Medium PDF keeps balanced extraction with moderate asset budget."
        return "quality_pdf", "Text-heavy PDF keeps quality-first parser ordering."

    if extension == ".docx":
        if file_mb >= 10 or estimated_pages >= _LARGE_DOCX_PAGE_COUNT:
            options.asset_image_limit = 10
            options.skip_image_supplement = True
            return "fast_docx", "Large DOCX prefers native parsing and skips secondary image sweep."
        return "balanced_docx", "DOCX uses balanced parser ordering."

    if extension in {".ppt", ".pptx"}:
        if file_mb >= 15 or estimated_pages >= _LARGE_SLIDE_COUNT:
            options.asset_image_limit = 10
            options.skip_image_supplement = True
            return "fast_pptx", "Large slide deck prefers native parsing and skips secondary image sweep."
        return "balanced_pptx", "Slide deck uses balanced parser ordering."

    return "balanced_default", "Default parser chain selected."
