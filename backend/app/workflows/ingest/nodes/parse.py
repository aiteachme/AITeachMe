"""Parse-phase nodes for ingest workflows.

Reads DB: ``raw_file`` lookup during parse result persistence.
Writes DB: ``raw_file`` ingest status transitions and parse metadata.
Writes FS: overwrites ``raw_markdowns/<raw_file_id>.md`` and matching files under shared ``assets/``.
Idempotency: reruns replace markdown/assets for the same file and refresh metadata in place.
"""

from __future__ import annotations

import json
from pathlib import Path
import time

from app.core.database import managed_session
from app.models import IngestStatus
from app.repositories.files_repo import get_raw_file_by_id, update_raw_file
from app.repositories.subject_repo import get_subject_by_slug
from app.services.upload_support import list_asset_files
from app.workflows.common.context import WorkflowContext
from app.workflows.ingest.events import IngestFileParsedEvent
from app.workflows.ingest.nodes.common import workflow_logger
from app.workflows.ingest.parsing.orchestrator import parse_file
from app.workflows.ingest.state import IngestParseState


def build_parse_file_node(*, context: WorkflowContext):
    async def parse_file_node(state: IngestParseState) -> IngestParseState:
        logger = workflow_logger(context, state)
        markdown_path = Path(state["markdown_path"])
        asset_dir = Path(state["asset_dir"])
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        asset_dir.mkdir(parents=True, exist_ok=True)

        started_at = time.monotonic()
        parse_plan = state.get("parse_plan")
        logger.info(
            "ingest_file_parse_started",
            markdown_path=str(markdown_path),
            asset_dir=str(asset_dir),
            parse_mode=parse_plan.mode if parse_plan else None,
            parser_chain=parse_plan.parser_chain if parse_plan else None,
            parser_parallelism=parse_plan.options.parser_parallelism if parse_plan else None,
            asset_name_prefix=parse_plan.options.asset_name_prefix if parse_plan else None,
            enable_asset_vision_ocr=parse_plan.options.enable_asset_vision_ocr if parse_plan else None,
            asset_vision_ocr_limit=parse_plan.options.asset_vision_ocr_limit if parse_plan else None,
            llm_ocr_page_concurrency=parse_plan.options.llm_ocr_page_concurrency if parse_plan else None,
            ocr_language_mode=parse_plan.options.ocr_language_mode if parse_plan else None,
        )
        try:
            parse_result = await parse_file(
                state["file_path"],
                asset_dir,
                classification=state.get("classification"),
                parse_plan=parse_plan,
                asset_link_prefix=f"../assets/{state['file_id']}",
            )
            markdown_path.write_text(parse_result.markdown, encoding="utf-8")
            image_count = len(
                list_asset_files(
                    asset_dir,
                    asset_name_prefix=state.get("asset_name_prefix"),
                )
            )
            elapsed = round(time.monotonic() - started_at, 2)
            parse_metadata = json.dumps(
                {
                    "provider_used": parse_result.parser_used,
                    "provider_status": "completed",
                    "parser_used": parse_result.parser_used,
                    "attempted_parsers": parse_result.attempted_parsers,
                    "parse_mode": parse_plan.mode if parse_plan else "",
                    "decision_reason": parse_plan.decision_reason if parse_plan else "",
                    "parser_chain": parse_plan.parser_chain if parse_plan else [],
                    "parser_parallelism": parse_plan.options.parser_parallelism if parse_plan else None,
                    "llm_ocr_page_concurrency": (
                        parse_plan.options.llm_ocr_page_concurrency if parse_plan else None
                    ),
                    "ocr_page_limit": parse_plan.options.ocr_page_limit if parse_plan else None,
                    "asset_gallery_limit": parse_plan.options.asset_gallery_limit if parse_plan else None,
                    "ocr_language_mode": parse_plan.options.ocr_language_mode if parse_plan else None,
                    "elapsed_s": elapsed,
                    "markdown_chars": len(parse_result.markdown),
                    "image_count": image_count,
                    "parser_elapsed_s": parse_result.parser_elapsed_s,
                    "rewritten_image_refs": parse_result.rewritten_image_refs,
                    "extracted_data_images": parse_result.extracted_data_images,
                    "appended_asset_images": parse_result.appended_asset_images,
                    "asset_ocr_images": parse_result.asset_ocr_images,
                    "asset_ocr_replacements": parse_result.asset_ocr_replacements,
                },
                ensure_ascii=False,
            )
            with managed_session() as session:
                raw_file = get_raw_file_by_id(session, state["file_id"])
                subject_record = get_subject_by_slug(session, state["subject"])
                if (
                    raw_file is None
                    or subject_record is None
                    or subject_record.id is None
                    or raw_file.subject_id != int(subject_record.id)
                ):
                    return {
                        **state,
                        "error": f"raw_file_not_found:{state['file_id']}",
                    }
                update_raw_file(
                    session,
                    raw_file,
                    ingest_status=IngestStatus.VALIDATING.value,
                    digest_current_step="ingest.parse.validating",
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
            logger.info(
                "ingest_file_parse_completed",
                parse_mode=parse_plan.mode if parse_plan else None,
                parser_used=parse_result.parser_used,
                attempted_parsers=parse_result.attempted_parsers,
                parser_elapsed_s=parse_result.parser_elapsed_s,
                markdown_chars=len(parse_result.markdown),
                image_count=image_count,
                elapsed_s=elapsed,
                rewritten_image_refs=parse_result.rewritten_image_refs,
                extracted_data_images=parse_result.extracted_data_images,
                appended_asset_images=parse_result.appended_asset_images,
                asset_ocr_images=parse_result.asset_ocr_images,
                asset_ocr_replacements=parse_result.asset_ocr_replacements,
            )
            return {
                **state,
                "parse_metadata": parse_metadata,
                "parsed_markdown": parse_result.markdown,
                "parser_used": parse_result.parser_used,
                "attempted_parsers": parse_result.attempted_parsers,
                "parser_elapsed_s": parse_result.parser_elapsed_s,
                "markdown_chars": len(parse_result.markdown),
                "image_count": image_count,
                "rewritten_image_refs": parse_result.rewritten_image_refs,
                "extracted_data_images": parse_result.extracted_data_images,
                "appended_asset_images": parse_result.appended_asset_images,
                "asset_ocr_images": parse_result.asset_ocr_images,
                "asset_ocr_replacements": parse_result.asset_ocr_replacements,
                "error": None,
            }
        except Exception as exc:
            logger.error(
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
