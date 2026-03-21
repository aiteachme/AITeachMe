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
from app.workflows.ingest.parsing.parsers import PARSER_REGISTRY
from app.workflows.ingest.parsing.strategy import ParsePlan, build_parse_plan

logger = structlog.get_logger()


class ParseExecutionResult(BaseModel):
    """Structured output of the parser routing layer."""

    markdown: str
    parser_used: str
    attempted_parsers: list[str] = Field(default_factory=list)


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

    extension = path.suffix.lower()
    if extension not in PARSER_REGISTRY:
        raise UnsupportedFileTypeError(extension)

    plan = parse_plan or build_parse_plan(
        file_path=path,
        filetype=extension,
        file_size_bytes=path.stat().st_size if path.exists() else None,
        classification=classification,
    )
    attempted_parsers: list[str] = []
    last_error: Exception | None = None
    started_at = time.monotonic()

    logger.info(
        "parse_file_routing",
        filename=path.name,
        extension=extension,
        parse_mode=plan.mode,
        parser_chain=plan.parser_chain,
        recommended_parser=classification.recommended_parser if classification else None,
        decision_reason=plan.decision_reason,
        timeout_s=plan.options.timeout_s,
    )

    for parser_name in plan.parser_chain:
        parser = PARSER_REGISTRY[extension][parser_name]
        attempted_parsers.append(parser_name)
        try:
            raw_markdown = await asyncio.wait_for(
                parser(path, assets, plan.options),
                timeout=plan.options.timeout_s,
            )
            normalized_markdown = canonicalize_markdown(raw_markdown)
            elapsed = round(time.monotonic() - started_at, 2)
            image_count = len(list(assets.glob("*"))) if assets.exists() else 0
            logger.info(
                "parse_file_completed",
                filename=path.name,
                parser=parser_name,
                parse_mode=plan.mode,
                raw_chars=len(raw_markdown),
                final_chars=len(normalized_markdown),
                images_extracted=image_count,
                elapsed_s=elapsed,
                attempted_parsers=attempted_parsers,
            )
            return ParseExecutionResult(
                markdown=normalized_markdown,
                parser_used=parser_name,
                attempted_parsers=attempted_parsers,
            )
        except asyncio.TimeoutError as exc:
            last_error = exc
            logger.warning(
                "parse_file_attempt_timed_out",
                filename=path.name,
                parser=parser_name,
                timeout_s=plan.options.timeout_s,
            )
        except Exception as exc:
            last_error = exc
            logger.warning(
                "parse_file_attempt_failed",
                filename=path.name,
                parser=parser_name,
                error=str(exc),
            )

    if last_error is None:
        raise UnsupportedFileTypeError(extension)
    raise last_error
