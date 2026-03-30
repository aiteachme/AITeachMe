"""Deep enhance nodes for ingest workflows (Phase 2).

Reads DB: ``raw_file`` for context loading.
Writes DB: ``raw_file`` ingest status and enhanced parse metadata.
Writes FS: overwrites ``raw_markdowns/<raw_file_id>.md`` with OCR-enhanced version.
Idempotency: reruns overwrite the same markdown for the same ``raw_file``.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import structlog

from app.core.database import managed_session
from app.models import IngestStatus
from app.repositories.files_repo import get_raw_file_by_id, update_raw_file
from app.utils.path_helpers import build_asset_dir, build_raw_markdown_path, resolve_storage_key_path
from app.workflows.ingest.parsing.classifier import ClassificationResult
from app.workflows.ingest.parsing.orchestrator import deep_enhance_file
from app.workflows.ingest.parsing.strategy import ParsePlan
from app.workflows.ingest.state import IngestEnhanceState

logger = structlog.get_logger()


def build_load_enhance_context_node():
    """Load Phase 1 products and prepare context for Phase 2."""

    async def load_enhance_context_node(state: IngestEnhanceState) -> IngestEnhanceState:
        try:
            with managed_session() as session:
                raw_file = get_raw_file_by_id(session, state["file_id"])
                if raw_file is None or raw_file.subject != state["subject"]:
                    return {
                        **state,
                        "error": f"raw_file_not_found:{state['file_id']}",
                    }

                file_path = str(resolve_storage_key_path(raw_file.storage_key))
                markdown_path = str(build_raw_markdown_path(state["subject"], state["file_id"]))
                asset_dir = str(build_asset_dir(state["subject"], state["file_id"]))

                # Recover parse_plan and classification from stored metadata
                parse_plan = None
                classification = None
                if raw_file.parse_metadata_json:
                    try:
                        meta = json.loads(raw_file.parse_metadata_json)
                        # Reconstruct minimal parse plan from metadata
                        from app.workflows.ingest.parsing.strategy import build_parse_plan
                        parse_plan = build_parse_plan(
                            file_path=file_path,
                            filetype=raw_file.file_ext,
                            file_size_bytes=raw_file.size_bytes,
                            classification=None,
                        )
                    except Exception:
                        pass
                if raw_file.classification_json:
                    try:
                        classification = ClassificationResult(**json.loads(raw_file.classification_json))
                    except Exception:
                        pass

                # If we still have no parse_plan, build one from scratch
                if parse_plan is None:
                    from app.workflows.ingest.parsing.strategy import build_parse_plan
                    parse_plan = build_parse_plan(
                        file_path=file_path,
                        filetype=raw_file.file_ext,
                        file_size_bytes=raw_file.size_bytes,
                        classification=classification,
                    )

                # Update status to ENHANCING
                update_raw_file(
                    session,
                    raw_file,
                    ingest_status=IngestStatus.ENHANCING.value,
                    digest_current_step="ingest.enhance.running",
                )

                asset_name_prefix = ""
                if raw_file.parse_metadata_json:
                    try:
                        meta = json.loads(raw_file.parse_metadata_json)
                        # Try to recover asset_name_prefix from parse plan options
                    except Exception:
                        pass

                from app.utils.path_helpers import build_asset_name_prefix
                asset_name_prefix = build_asset_name_prefix(
                    filename=raw_file.original_filename,
                    file_uid=raw_file.uid,
                    file_id=state["file_id"],
                )

            logger.info(
                "enhance_context_loaded",
                file_id=state["file_id"],
                file_path=file_path,
                markdown_path=markdown_path,
            )
            return {
                **state,
                "file_path": file_path,
                "filetype": raw_file.file_ext,
                "markdown_path": markdown_path,
                "asset_dir": asset_dir,
                "asset_name_prefix": asset_name_prefix,
                "classification": classification,
                "parse_plan": parse_plan,
                "error": None,
            }
        except Exception as exc:
            logger.error("enhance_context_load_failed", error=str(exc), exc_info=True)
            return {
                **state,
                "error": f"load_enhance_context_failed: {exc}",
            }

    return load_enhance_context_node


def build_deep_enhance_file_node():
    """Phase 2: Run LLM Vision OCR on extracted assets."""

    async def deep_enhance_file_node(state: IngestEnhanceState) -> IngestEnhanceState:
        markdown_path = Path(state["markdown_path"])
        if not markdown_path.exists():
            return {
                **state,
                "error": f"markdown_not_found:{state['markdown_path']}",
            }

        markdown = markdown_path.read_text(encoding="utf-8")
        parse_plan = state.get("parse_plan")
        if parse_plan is None:
            return {
                **state,
                "error": "no_parse_plan_for_enhance",
            }

        started_at = time.monotonic()
        try:
            enhance_result = await deep_enhance_file(
                markdown,
                file_path=state["file_path"],
                asset_dir=state["asset_dir"],
                asset_link_prefix=f"../assets/{state['file_id']}",
                asset_name_prefix=state.get("asset_name_prefix", ""),
                parse_plan=parse_plan,
                classification=state.get("classification"),
            )
            # Overwrite markdown with enhanced version
            markdown_path.write_text(enhance_result.markdown, encoding="utf-8")
            elapsed = round(time.monotonic() - started_at, 2)

            logger.info(
                "deep_enhance_file_completed",
                file_id=state["file_id"],
                ocr_images=enhance_result.asset_ocr_images,
                ocr_replacements=enhance_result.asset_ocr_replacements,
                elapsed_s=elapsed,
            )
            return {
                **state,
                "enhanced_markdown": enhance_result.markdown,
                "asset_ocr_images": enhance_result.asset_ocr_images,
                "asset_ocr_replacements": enhance_result.asset_ocr_replacements,
                "error": None,
            }
        except Exception as exc:
            logger.error(
                "deep_enhance_file_failed",
                error=str(exc),
                elapsed_s=round(time.monotonic() - started_at, 2),
                exc_info=True,
            )
            return {
                **state,
                "error": f"deep_enhance_failed: {exc}",
            }

    return deep_enhance_file_node


def build_finalize_deep_enhance_node():
    """Finalize Phase 2: update DB status to READY_FOR_DIGEST."""

    async def finalize_deep_enhance_node(state: IngestEnhanceState) -> IngestEnhanceState:
        try:
            enhanced_markdown = state.get("enhanced_markdown")
            with managed_session() as session:
                raw_file = get_raw_file_by_id(session, state["file_id"])
                if raw_file is None or raw_file.subject != state["subject"]:
                    return {
                        **state,
                        "error": f"raw_file_not_found:{state['file_id']}",
                    }

                # Update parse_metadata with OCR results
                parse_metadata = {}
                if raw_file.parse_metadata_json:
                    try:
                        parse_metadata = json.loads(raw_file.parse_metadata_json)
                    except Exception:
                        pass

                parse_metadata["asset_ocr_images"] = state.get("asset_ocr_images", 0)
                parse_metadata["asset_ocr_replacements"] = state.get("asset_ocr_replacements", 0)
                parse_metadata["provider_status"] = "enhanced"

                update_raw_file(
                    session,
                    raw_file,
                    parsed_markdown=enhanced_markdown or raw_file.parsed_markdown,
                    parse_metadata_json=json.dumps(parse_metadata, ensure_ascii=False),
                    ingest_status=IngestStatus.READY_FOR_DIGEST.value,
                    digest_current_step="ingest.enhance.completed",
                )

            logger.info(
                "ingest_enhance_finalized",
                file_id=state["file_id"],
                ocr_images=state.get("asset_ocr_images", 0),
            )
            return {
                **state,
                "error": None,
            }
        except Exception as exc:
            logger.error("ingest_enhance_finalize_failed", error=str(exc), exc_info=True)
            return {
                **state,
                "error": f"finalize_enhance_failed: {exc}",
            }

    return finalize_deep_enhance_node


def build_finalize_enhance_failure_node():
    """Handle Phase 2 failure: set status to ENHANCE_FAILED (Phase 1 result preserved)."""

    async def finalize_enhance_failure_node(state: IngestEnhanceState) -> IngestEnhanceState:
        error_message = state.get("error", "unknown_enhance_error")
        try:
            with managed_session() as session:
                raw_file = get_raw_file_by_id(session, state["file_id"])
                if raw_file is not None and raw_file.subject == state["subject"]:
                    update_raw_file(
                        session,
                        raw_file,
                        ingest_status=IngestStatus.ENHANCE_FAILED.value,
                        digest_current_step="ingest.enhance.failed",
                        parse_error_message=f"Phase 2 enhance failed: {error_message}",
                    )
        except Exception:
            logger.exception("enhance_failure_finalize_error", file_id=state["file_id"])

        logger.warning(
            "ingest_enhance_failed",
            file_id=state["file_id"],
            error=error_message,
        )
        return state

    return finalize_enhance_failure_node
