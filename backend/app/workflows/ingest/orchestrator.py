"""Parser routing for ingest workflows."""

from __future__ import annotations

from pathlib import Path
import time

from pydantic import BaseModel, Field
import structlog

from app.core.exceptions import UnsupportedFileTypeError
from app.workflows.ingest.canonicalizer import canonicalize_markdown
from app.workflows.ingest.classifier import ClassificationResult
from app.workflows.ingest.parsers import DEFAULT_PARSER_CHAIN, PARSER_REGISTRY


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
) -> ParseExecutionResult:
    """Parse a file using the classification-informed parser chain."""

    path = Path(file_path)
    assets = Path(asset_dir)
    assets.mkdir(parents=True, exist_ok=True)

    extension = path.suffix.lower()
    parser_chain = _resolve_parser_chain(extension, classification)
    attempted_parsers: list[str] = []
    last_error: Exception | None = None
    started_at = time.monotonic()

    logger.info(
        "parse_file_routing",
        filename=path.name,
        extension=extension,
        parser_chain=parser_chain,
        recommended_parser=classification.recommended_parser if classification else None,
    )

    for parser_name in parser_chain:
        parser = PARSER_REGISTRY[extension][parser_name]
        attempted_parsers.append(parser_name)
        try:
            raw_markdown = await parser(path, assets)
            normalized_markdown = canonicalize_markdown(raw_markdown)
            elapsed = round(time.monotonic() - started_at, 2)
            image_count = len(list(assets.glob("*"))) if assets.exists() else 0
            logger.info(
                "parse_file_completed",
                filename=path.name,
                parser=parser_name,
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


def _resolve_parser_chain(
    extension: str,
    classification: ClassificationResult | None,
) -> list[str]:
    available_parsers = PARSER_REGISTRY.get(extension)
    if available_parsers is None:
        raise UnsupportedFileTypeError(extension)

    preferred_order: list[str] = []
    if classification is not None:
        preferred_order.extend(
            [
                classification.recommended_parser,
                *classification.fallback_parsers,
            ]
        )
    preferred_order.extend(DEFAULT_PARSER_CHAIN.get(extension, []))

    deduped_chain: list[str] = []
    for parser_name in preferred_order:
        if not parser_name or parser_name not in available_parsers:
            continue
        if parser_name in deduped_chain:
            continue
        deduped_chain.append(parser_name)

    if not deduped_chain:
        raise UnsupportedFileTypeError(extension)
    return deduped_chain
