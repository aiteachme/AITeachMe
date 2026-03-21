"""Parse-phase nodes for ingest workflows."""

from __future__ import annotations

import json
from pathlib import Path
import time

from app.core.database import managed_session
from app.models import IngestStatus
from app.repositories.files_repo import get_raw_file_by_id, update_raw_file
from app.workflows.common.context import WorkflowContext
from app.workflows.ingest.nodes.common import workflow_logger
from app.workflows.ingest.events import IngestFileParsedEvent
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
        )
        try:
            parse_result = await parse_file(
                state["file_path"],
                asset_dir,
                classification=state.get("classification"),
                parse_plan=parse_plan,
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
                    "plan_mode": parse_plan.mode if parse_plan else "",
                    "plan_reason": parse_plan.decision_reason if parse_plan else "",
                    "timeout_s": parse_plan.options.timeout_s if parse_plan else None,
                    "asset_image_limit": parse_plan.options.asset_image_limit if parse_plan else None,
                    "skip_image_supplement": parse_plan.options.skip_image_supplement if parse_plan else None,
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
            logger.info(
                "ingest_file_parse_completed",
                parse_mode=parse_plan.mode if parse_plan else None,
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
