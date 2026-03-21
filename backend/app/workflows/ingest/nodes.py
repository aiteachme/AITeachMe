"""Ingest workflow nodes."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time

from app.core.database import managed_session
from app.models import IngestStatus, TaskStatus
from app.repositories.files_repo import get_raw_file_by_id, update_raw_file
from app.services.upload_support import build_asset_dir, build_markdown_path
from app.workflows.common.context import WorkflowContext
from app.workflows.ingest.classifier import classify_file
from app.workflows.ingest.events import (
    IngestFileClassifiedEvent,
    IngestFileParsedEvent,
    IngestFileParseFailedEvent,
    IngestFileReadyForDigestEvent,
)
from app.workflows.ingest.orchestrator import parse_file
from app.workflows.ingest.state import IngestParseState


def _workflow_logger(context: WorkflowContext, state: IngestParseState):
    return context.get_logger().bind(
        file_id=state["file_id"],
        filename=state.get("filename"),
    )


def _load_raw_file_state(state: IngestParseState) -> IngestParseState:
    with managed_session() as session:
        raw_file = get_raw_file_by_id(session, state["file_id"])
        if raw_file is None or raw_file.subject != state["subject"]:
            return {
                **state,
                "error": f"raw_file_not_found:{state['file_id']}",
            }

        file_id = state["file_id"]
        return {
            **state,
            "filename": raw_file.filename,
            "filetype": raw_file.filetype,
            "file_path": raw_file.file_path,
            "markdown_path": str(build_markdown_path(raw_file.subject, file_id)),
            "asset_dir": str(build_asset_dir(raw_file.subject, file_id)),
            "error": None,
        }


def build_load_raw_file_node(*, context: WorkflowContext):
    async def load_raw_file_node(state: IngestParseState) -> IngestParseState:
        workflow_logger = _workflow_logger(context, state)
        workflow_logger.info("ingest_load_raw_file_started")
        next_state = _load_raw_file_state(state)
        if next_state.get("error"):
            workflow_logger.warning(
                "ingest_load_raw_file_failed",
                error=next_state["error"],
            )
            return next_state

        workflow_logger.info(
            "ingest_load_raw_file_completed",
            file_path=next_state["file_path"],
            markdown_path=next_state["markdown_path"],
            asset_dir=next_state["asset_dir"],
        )
        return next_state

    return load_raw_file_node


def build_compute_fingerprint_node(*, context: WorkflowContext):
    async def compute_fingerprint_node(state: IngestParseState) -> IngestParseState:
        workflow_logger = _workflow_logger(context, state)
        try:
            file_bytes = Path(state["file_path"]).read_bytes()
            content_hash = hashlib.sha256(file_bytes).hexdigest()
            file_size_bytes = len(file_bytes)
            workflow_logger.info(
                "ingest_file_fingerprint_completed",
                file_size_bytes=file_size_bytes,
            )
            return {
                **state,
                "content_hash": content_hash,
                "file_size_bytes": file_size_bytes,
                "error": None,
            }
        except Exception as exc:
            workflow_logger.error(
                "ingest_file_fingerprint_failed",
                error=str(exc),
                exc_info=True,
            )
            return {
                **state,
                "error": f"compute_fingerprint_failed: {exc}",
            }

    return compute_fingerprint_node


def build_classify_file_node(*, context: WorkflowContext):
    async def classify_file_node(state: IngestParseState) -> IngestParseState:
        workflow_logger = _workflow_logger(context, state)
        try:
            classification = classify_file(state["file_path"], state["filetype"])
            classification_payload = json.dumps(classification.to_dict(), ensure_ascii=False)
            with managed_session() as session:
                raw_file = get_raw_file_by_id(session, state["file_id"])
                if raw_file is None or raw_file.subject != state["subject"]:
                    return {
                        **state,
                        "error": f"raw_file_not_found:{state['file_id']}",
                    }
                update_raw_file(
                    session,
                    raw_file,
                    estimated_pages=classification.estimated_pages,
                    detected_language=classification.detected_language,
                    classification_result=classification_payload,
                    ingest_status=IngestStatus.PARSING.value,
                )
            await context.event_bus.publish(
                IngestFileClassifiedEvent(
                    subject=state["subject"],
                    file_id=state["file_id"],
                    file_category=classification.file_category,
                    recommended_parser=classification.recommended_parser,
                    detected_language=classification.detected_language,
                )
            )
            workflow_logger.info(
                "ingest_file_classified",
                category=classification.file_category,
                recommended_parser=classification.recommended_parser,
                detected_language=classification.detected_language,
                estimated_pages=classification.estimated_pages,
            )
            return {
                **state,
                "classification": classification,
                "classification_payload": classification_payload,
                "estimated_pages": classification.estimated_pages,
                "detected_language": classification.detected_language,
                "error": None,
            }
        except Exception as exc:
            workflow_logger.error(
                "ingest_file_classify_failed",
                error=str(exc),
                exc_info=True,
            )
            return {
                **state,
                "error": f"classify_file_failed: {exc}",
            }

    return classify_file_node


def build_parse_file_node(*, context: WorkflowContext):
    async def parse_file_node(state: IngestParseState) -> IngestParseState:
        workflow_logger = _workflow_logger(context, state)
        markdown_path = Path(state["markdown_path"])
        asset_dir = Path(state["asset_dir"])
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        asset_dir.mkdir(parents=True, exist_ok=True)

        started_at = time.monotonic()
        workflow_logger.info(
            "ingest_file_parse_started",
            markdown_path=str(markdown_path),
            asset_dir=str(asset_dir),
        )
        try:
            parse_result = await parse_file(
                state["file_path"],
                asset_dir,
                classification=state.get("classification"),
            )
            markdown_path.write_text(parse_result.markdown, encoding="utf-8")
            image_count = len(list(asset_dir.glob("*"))) if asset_dir.exists() else 0
            elapsed = round(time.monotonic() - started_at, 2)
            classification = state.get("classification")
            parse_metadata = json.dumps(
                {
                    "recommended_parser": classification.recommended_parser if classification else "",
                    "parser_used": parse_result.parser_used,
                    "attempted_parsers": parse_result.attempted_parsers,
                    "fallbacks": classification.fallback_parsers if classification else [],
                    "elapsed_s": elapsed,
                    "markdown_chars": len(parse_result.markdown),
                    "image_count": image_count,
                },
                ensure_ascii=False,
            )
            with managed_session() as session:
                raw_file = get_raw_file_by_id(session, state["file_id"])
                if raw_file is None or raw_file.subject != state["subject"]:
                    return {
                        **state,
                        "error": f"raw_file_not_found:{state['file_id']}",
                    }
                update_raw_file(
                    session,
                    raw_file,
                    ingest_status=IngestStatus.VALIDATING.value,
                )
            await context.event_bus.publish(
                IngestFileParsedEvent(
                    subject=state["subject"],
                    file_id=state["file_id"],
                    parser_used=parse_result.parser_used,
                    markdown_chars=len(parse_result.markdown),
                    image_count=image_count,
                )
            )
            workflow_logger.info(
                "ingest_file_parse_completed",
                parser_used=parse_result.parser_used,
                attempted_parsers=parse_result.attempted_parsers,
                markdown_chars=len(parse_result.markdown),
                image_count=image_count,
                elapsed_s=elapsed,
            )
            return {
                **state,
                "parse_metadata": parse_metadata,
                "parser_used": parse_result.parser_used,
                "attempted_parsers": parse_result.attempted_parsers,
                "markdown_chars": len(parse_result.markdown),
                "image_count": image_count,
                "error": None,
            }
        except Exception as exc:
            workflow_logger.error(
                "ingest_file_parse_failed",
                error=str(exc),
                elapsed_s=round(time.monotonic() - started_at, 2),
                exc_info=True,
            )
            return {
                **state,
                "error": f"parse_file_failed: {exc}",
            }

    return parse_file_node


def build_finalize_success_node(*, context: WorkflowContext):
    async def finalize_success_node(state: IngestParseState) -> IngestParseState:
        workflow_logger = _workflow_logger(context, state)
        try:
            with managed_session() as session:
                raw_file = get_raw_file_by_id(session, state["file_id"])
                if raw_file is None or raw_file.subject != state["subject"]:
                    return {
                        **state,
                        "error": f"raw_file_not_found:{state['file_id']}",
                    }
                update_raw_file(
                    session,
                    raw_file,
                    markdown_path=state["markdown_path"],
                    asset_dir=state["asset_dir"],
                    status=TaskStatus.COMPLETED.value,
                    error_message=None,
                    content_hash=state.get("content_hash"),
                    file_size_bytes=state.get("file_size_bytes"),
                    estimated_pages=state.get("estimated_pages"),
                    detected_language=state.get("detected_language"),
                    classification_result=state.get("classification_payload"),
                    parse_metadata=state.get("parse_metadata"),
                    image_count=state.get("image_count"),
                    ingest_status=IngestStatus.READY_FOR_DIGEST.value,
                )
            await context.event_bus.publish(
                IngestFileReadyForDigestEvent(
                    subject=state["subject"],
                    file_id=state["file_id"],
                )
            )
            workflow_logger.info(
                "ingest_file_finalize_success",
                parser_used=state.get("parser_used"),
                markdown_chars=state.get("markdown_chars", 0),
                image_count=state.get("image_count", 0),
            )
            return {
                **state,
                "error": None,
            }
        except Exception as exc:
            workflow_logger.error(
                "ingest_file_finalize_success_failed",
                error=str(exc),
                exc_info=True,
            )
            return {
                **state,
                "error": f"finalize_success_failed: {exc}",
            }

    return finalize_success_node


def build_finalize_failure_node(*, context: WorkflowContext):
    async def finalize_failure_node(state: IngestParseState) -> IngestParseState:
        workflow_logger = _workflow_logger(context, state)
        error_message = state.get("error", "unknown_error")
        with managed_session() as session:
            raw_file = get_raw_file_by_id(session, state["file_id"])
            if raw_file is not None and raw_file.subject == state["subject"]:
                update_raw_file(
                    session,
                    raw_file,
                    asset_dir=state.get("asset_dir"),
                    status=TaskStatus.FAILED.value,
                    error_message=error_message,
                    ingest_status=IngestStatus.FAILED.value,
                )
        await context.event_bus.publish(
            IngestFileParseFailedEvent(
                subject=state["subject"],
                file_id=state["file_id"],
                error_message=error_message,
            )
        )
        workflow_logger.error(
            "ingest_file_finalize_failed",
            error=error_message,
        )
        return state

    return finalize_failure_node
