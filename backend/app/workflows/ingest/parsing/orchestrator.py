"""Parser routing for ingest workflows."""

from __future__ import annotations

import asyncio
from pathlib import Path
import time

from pydantic import BaseModel, Field
import structlog

from app.core.exceptions import UnsupportedFileTypeError
from app.workflows.ingest.parsing.canonicalizer import canonicalize_markdown
from app.workflows.ingest.parsing.classifier import ClassificationResult
from app.workflows.ingest.parsing.parsers import PARSER_REGISTRY, resolve_parser_extension
from app.workflows.ingest.parsing.strategy import ParsePlan, build_parse_plan

logger = structlog.get_logger()


class ParseExecutionResult(BaseModel):
    """Structured output of the parser routing layer."""

    markdown: str
    parser_used: str
    attempted_parsers: list[str] = Field(default_factory=list)
    parser_elapsed_s: dict[str, float] = Field(default_factory=dict)
    rewritten_image_refs: int = 0
    extracted_data_images: int = 0
    appended_asset_images: int = 0


async def parse_file(
    file_path: str | Path,
    asset_dir: str | Path,
    *,
    classification: ClassificationResult | None = None,
    parse_plan: ParsePlan | None = None,
) -> ParseExecutionResult:
    """Parse a file using the classification-informed parser chain."""

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
        "parse_file_routing",
        filename=path.name,
        extension=source_extension,
        resolved_extension=extension,
        parse_mode=plan.mode,
        parser_chain=plan.parser_chain,
        recommended_parser=classification.recommended_parser if classification else None,
        decision_reason=plan.decision_reason,
        timeout_s=plan.options.timeout_s,
        parser_parallelism=plan.options.parser_parallelism,
        llm_ocr_page_concurrency=plan.options.llm_ocr_page_concurrency,
        ocr_page_limit=plan.options.ocr_page_limit,
        asset_gallery_limit=plan.options.asset_gallery_limit,
        ocr_language_mode=plan.options.ocr_language_mode,
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
            canonical_result = canonicalize_markdown(
                raw_markdown,
                asset_dir=assets,
                asset_link_prefix=f"../assets/{assets.name}",
                asset_gallery_limit=plan.options.asset_gallery_limit,
            )
            elapsed = round(time.monotonic() - started_at, 2)
            image_count = len(list(assets.glob("*"))) if assets.exists() else 0
            logger.info(
                "parse_file_completed",
                filename=path.name,
                parser=parser_name,
                parse_mode=plan.mode,
                raw_chars=len(raw_markdown),
                final_chars=len(canonical_result.markdown),
                images_extracted=image_count,
                elapsed_s=elapsed,
                attempted_parsers=attempted_parsers,
                parser_elapsed_s=parser_elapsed_s,
                rewritten_image_refs=canonical_result.rewritten_image_refs,
                extracted_data_images=canonical_result.extracted_data_images,
                appended_asset_images=canonical_result.appended_asset_images,
            )
            return ParseExecutionResult(
                markdown=canonical_result.markdown,
                parser_used=parser_name,
                attempted_parsers=attempted_parsers,
                parser_elapsed_s=parser_elapsed_s,
                rewritten_image_refs=canonical_result.rewritten_image_refs,
                extracted_data_images=canonical_result.extracted_data_images,
                appended_asset_images=canonical_result.appended_asset_images,
            )
        except asyncio.TimeoutError as exc:
            parser_elapsed_s[parser_name] = round(time.monotonic() - parser_started_at, 2)
            last_error = exc
            logger.warning(
                "parse_file_attempt_timed_out",
                filename=path.name,
                parser=parser_name,
                timeout_s=plan.options.timeout_s,
                parser_elapsed_s=parser_elapsed_s[parser_name],
            )
        except Exception as exc:
            parser_elapsed_s[parser_name] = round(time.monotonic() - parser_started_at, 2)
            last_error = exc
            logger.warning(
                "parse_file_attempt_failed",
                filename=path.name,
                parser=parser_name,
                error=str(exc),
                parser_elapsed_s=parser_elapsed_s[parser_name],
            )

    if last_error is None:
        raise UnsupportedFileTypeError(extension)
    raise last_error
