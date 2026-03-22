"""Load, fingerprint, classify, and plan nodes for ingest workflows.

Reads DB: ``raw_file``.
Writes DB: ``raw_file`` classification / ingest-prep metadata.
Writes FS: reads the persisted raw file path and derives deterministic markdown/assets paths.
Idempotency: reruns refresh metadata for the same ``raw_file`` and reuse the same output paths.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.core.database import managed_session
from app.models import IngestStatus
from app.repositories.files_repo import get_raw_file_by_id, update_raw_file
from app.services.upload_support import build_asset_dir, build_markdown_path
from app.workflows.common.context import WorkflowContext
from app.workflows.ingest.nodes.common import workflow_logger
from app.workflows.ingest.events import IngestFileClassifiedEvent
from app.workflows.ingest.parsing.classifier import classify_file
from app.workflows.ingest.state import IngestParseState
from app.workflows.ingest.parsing.strategy import build_parse_plan


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
        logger = workflow_logger(context, state)
        logger.info("ingest_load_raw_file_started")
        next_state = _load_raw_file_state(state)
        if next_state.get("error"):
            logger.warning("ingest_load_raw_file_failed", error=next_state["error"])
            return next_state

        logger.info(
            "ingest_load_raw_file_completed",
            file_path=next_state["file_path"],
            markdown_path=next_state["markdown_path"],
            asset_dir=next_state["asset_dir"],
        )
        return next_state

    return load_raw_file_node


def build_compute_fingerprint_node(*, context: WorkflowContext):
    async def compute_fingerprint_node(state: IngestParseState) -> IngestParseState:
        logger = workflow_logger(context, state)
        try:
            file_bytes = Path(state["file_path"]).read_bytes()
            content_hash = hashlib.sha256(file_bytes).hexdigest()
            file_size_bytes = len(file_bytes)
            logger.info("ingest_file_fingerprint_completed", file_size_bytes=file_size_bytes)
            return {
                **state,
                "content_hash": content_hash,
                "file_size_bytes": file_size_bytes,
                "error": None,
            }
        except Exception as exc:
            logger.error("ingest_file_fingerprint_failed", error=str(exc), exc_info=True)
            return {
                **state,
                "error": f"compute_fingerprint_failed: {exc}",
            }

    return compute_fingerprint_node


def build_classify_file_node(*, context: WorkflowContext):
    async def classify_file_node(state: IngestParseState) -> IngestParseState:
        logger = workflow_logger(context, state)
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
            logger.info(
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
            logger.error("ingest_file_classify_failed", error=str(exc), exc_info=True)
            return {
                **state,
                "error": f"classify_file_failed: {exc}",
            }

    return classify_file_node


def build_plan_parse_node(*, context: WorkflowContext):
    async def plan_parse_node(state: IngestParseState) -> IngestParseState:
        logger = workflow_logger(context, state)
        try:
            parse_plan = build_parse_plan(
                file_path=state["file_path"],
                filetype=state["filetype"],
                file_size_bytes=state.get("file_size_bytes"),
                classification=state.get("classification"),
            )
            logger.info(
                "ingest_parse_plan_built",
                mode=parse_plan.mode,
                parser_chain=parse_plan.parser_chain,
                decision_reason=parse_plan.decision_reason,
                timeout_s=parse_plan.options.timeout_s,
                asset_image_limit=parse_plan.options.asset_image_limit,
                skip_image_supplement=parse_plan.options.skip_image_supplement,
            )
            return {
                **state,
                "parse_plan": parse_plan,
                "parse_plan_payload": parse_plan.model_dump_json(),
                "error": None,
            }
        except Exception as exc:
            logger.error("ingest_parse_plan_failed", error=str(exc), exc_info=True)
            return {
                **state,
                "error": f"plan_parse_failed: {exc}",
            }

    return plan_parse_node
