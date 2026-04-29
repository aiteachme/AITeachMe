"""Parser routing for ingest workflows — two-phase architecture.

Phase 1 (fast_parse_file): Traditional parsing only, no LLM calls.
Phase 2 (deep_enhance_file): LLM Vision OCR enhancement, runs in background.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import time

from pydantic import BaseModel, Field
import structlog

from app.shared.infra.exceptions import UnsupportedFileTypeError
from app.utils.path_helpers import list_asset_files
from app.workflows.ingest.parsing.asset_ocr import enhance_markdown_with_asset_ocr
from app.workflows.ingest.parsing.canonicalizer import canonicalize_markdown
from app.workflows.ingest.parsing.classifier import ClassificationResult
from app.workflows.ingest.parsing.parsers import PARSER_REGISTRY, resolve_parser_extension
from app.workflows.ingest.parsing.strategy import ParsePlan, build_parse_plan

logger = structlog.get_logger()


class FastParseResult(BaseModel):
    """Phase 1 output: traditional parsing only, no LLM."""

    markdown: str
    parser_used: str
    attempted_parsers: list[str] = Field(default_factory=list)
    parser_elapsed_s: dict[str, float] = Field(default_factory=dict)
    rewritten_image_refs: int = 0
    extracted_data_images: int = 0
    appended_asset_images: int = 0
    needs_enhance: bool = True
    needs_quality_reparse: bool = False
    needs_asset_ocr: bool = False


class DeepEnhanceResult(BaseModel):
    """Phase 2 output: LLM OCR enhanced markdown."""

    markdown: str
    asset_ocr_images: int = 0
    asset_ocr_replacements: int = 0


async def fast_parse_file(
    file_path: str | Path,
    asset_dir: str | Path,
    *,
    classification: ClassificationResult | None = None,
    parse_plan: ParsePlan | None = None,
    asset_link_prefix: str = "../assets",
) -> FastParseResult:
    """Phase 1: Parse with traditional methods only. No LLM calls.

    Returns fast Markdown and extracted images. The result is immediately
    presentable to the user while Phase 2 runs in background.
    """

    path = Path(file_path)
    assets = Path(asset_dir)
    assets.mkdir(parents=True, exist_ok=True)

    source_extension = path.suffix.lower()
    extension = resolve_parser_extension(path, source_extension)
    if extension not in PARSER_REGISTRY:
        raise UnsupportedFileTypeError(source_extension or extension)

    plan = parse_plan or build_parse_plan(
        file_path=path,
        filetype=extension,
        file_size_bytes=path.stat().st_size if path.exists() else None,
        classification=classification,
    )
    attempted_parsers: list[str] = []
    parser_elapsed_s: dict[str, float] = {}
    last_error: Exception | None = None
    started_at = time.monotonic()

    logger.info(
        "fast_parse_file_start",
        filename=path.name,
        extension=source_extension,
        resolved_extension=extension,
        parse_mode=plan.mode,
        parser_chain=plan.parser_chain,
        decision_reason=plan.decision_reason,
    )

    for parser_name in plan.parser_chain:
        parser = PARSER_REGISTRY[extension][parser_name]
        attempted_parsers.append(parser_name)
        parser_started_at = time.monotonic()
        try:
            raw_markdown = await asyncio.wait_for(
                parser(path, assets, plan.options),
                timeout=plan.options.timeout_s,
            )
            parser_elapsed_s[parser_name] = round(time.monotonic() - parser_started_at, 2)

            # Canonicalize: normalize image refs, extract embedded images
            # Use full gallery limit since we're not doing OCR in Phase 1
            canonical_result = canonicalize_markdown(
                raw_markdown,
                asset_dir=assets,
                asset_link_prefix=asset_link_prefix,
                asset_name_prefix=plan.options.asset_name_prefix,
                asset_gallery_limit=plan.options.asset_gallery_limit,
            )

            elapsed = round(time.monotonic() - started_at, 2)
            image_count = len(
                list_asset_files(
                    assets,
                    asset_name_prefix=plan.options.asset_name_prefix,
                )
            )

            # Determine if Phase 2 is needed
            from app.workflows.ingest.parsing.formats import is_text_extension
            needs_quality_reparse = False
            needs_asset_ocr = (
                plan.options.enable_asset_vision_ocr
                and not is_text_extension(extension)
                and image_count > 0
                and plan.mode != "external_ocr"
            )
            needs_enhance = needs_quality_reparse or needs_asset_ocr

            logger.info(
                "fast_parse_file_completed",
                filename=path.name,
                parser=parser_name,
                parse_mode=plan.mode,
                raw_chars=len(raw_markdown),
                final_chars=len(canonical_result.markdown),
                images_extracted=image_count,
                elapsed_s=elapsed,
                needs_enhance=needs_enhance,
                needs_quality_reparse=needs_quality_reparse,
                needs_asset_ocr=needs_asset_ocr,
            )
            return FastParseResult(
                markdown=canonical_result.markdown,
                parser_used=parser_name,
                attempted_parsers=attempted_parsers,
                parser_elapsed_s=parser_elapsed_s,
                rewritten_image_refs=canonical_result.rewritten_image_refs,
                extracted_data_images=canonical_result.extracted_data_images,
                appended_asset_images=canonical_result.appended_asset_images,
                needs_enhance=needs_enhance,
                needs_quality_reparse=needs_quality_reparse,
                needs_asset_ocr=needs_asset_ocr,
            )
        except asyncio.TimeoutError as exc:
            parser_elapsed_s[parser_name] = round(time.monotonic() - parser_started_at, 2)
            last_error = exc
            logger.warning(
                "fast_parse_file_timeout",
                filename=path.name,
                parser=parser_name,
                timeout_s=plan.options.timeout_s,
            )
        except Exception as exc:
            parser_elapsed_s[parser_name] = round(time.monotonic() - parser_started_at, 2)
            last_error = exc
            logger.warning(
                "fast_parse_file_attempt_failed",
                filename=path.name,
                parser=parser_name,
                error=str(exc),
            )

    if last_error is None:
        raise UnsupportedFileTypeError(extension)
    raise last_error


async def deep_enhance_file(
    markdown: str,
    *,
    file_path: str | Path,
    asset_dir: str | Path,
    asset_link_prefix: str,
    asset_name_prefix: str,
    parse_plan: ParsePlan,
    classification: ClassificationResult | None = None,
) -> DeepEnhanceResult:
    """Phase 2: Enhance markdown with LLM Vision OCR. Runs in background.

    Takes the Phase 1 markdown and enriches it with:
    - Asset-level OCR (images → text via LLM Vision)
    - PDF page-level OCR fallback (low-density pages)
    """

    path = Path(file_path)
    assets = Path(asset_dir)

    logger.info(
        "deep_enhance_file_start",
        filename=path.name,
        enable_asset_vision_ocr=parse_plan.options.enable_asset_vision_ocr,
        asset_vision_ocr_limit=parse_plan.options.asset_vision_ocr_limit,
        llm_ocr_page_concurrency=parse_plan.options.llm_ocr_page_concurrency,
    )

    started_at = time.monotonic()

    # Step 1: Asset-level OCR enrichment
    enhanced_result = await enhance_markdown_with_asset_ocr(
        markdown,
        asset_dir=assets,
        asset_link_prefix=asset_link_prefix,
        asset_name_prefix=asset_name_prefix,
        enabled=parse_plan.options.enable_asset_vision_ocr,
        limit=parse_plan.options.asset_vision_ocr_limit,
        language_mode=parse_plan.options.ocr_language_mode,
        concurrency=parse_plan.options.llm_ocr_page_concurrency,
    )

    final_markdown = enhanced_result.markdown
    total_ocr_images = enhanced_result.ocr_image_count
    total_replacements = enhanced_result.placeholder_replacements

    elapsed = round(time.monotonic() - started_at, 2)
    logger.info(
        "deep_enhance_file_completed",
        filename=path.name,
        ocr_images=total_ocr_images,
        ocr_replacements=total_replacements,
        elapsed_s=elapsed,
    )
    return DeepEnhanceResult(
        markdown=final_markdown,
        asset_ocr_images=total_ocr_images,
        asset_ocr_replacements=total_replacements,
    )
