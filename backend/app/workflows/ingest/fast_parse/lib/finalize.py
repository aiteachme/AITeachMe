"""Finalize nodes for ingest workflows.

Reads DB: ``raw_file``.
Writes DB: final ``raw_file`` success / failure state and ingest readiness.
Writes FS: no new files; final state points at markdown/assets written earlier in the workflow.
Idempotency: success/failure finalization rewrites the same record for the same ``raw_file``.
"""

from __future__ import annotations

import mimetypes
import re
from pathlib import Path

from app.shared.infra.database import managed_session
from app.shared.infra.storage import get_content_store, run_store_sync
from app.models import IngestStatus, RawFileAsset, TaskStatus
from app.repositories.files_repo import get_raw_file_by_id, replace_raw_file_assets, update_raw_file
from app.shared.infra.workflow.context import WorkflowContext
from app.utils.path_helpers import to_storage_key
from app.workflows.ingest.application.events import (
    IngestFileFastParsedEvent,
    IngestFileParseFailedEvent,
    IngestFileReadyForDigestEvent,
)
from app.workflows.ingest.fast_parse.lib.common import workflow_logger
from app.workflows.ingest.fast_parse.state import IngestParseState

try:
    from PIL import Image
except ImportError:
    Image = None

_PAGE_RE = re.compile(r"(?:page|p|slide|s)[_\-]?(\d{1,4})", re.IGNORECASE)


def _guess_asset_kind(filename: str) -> str:
    lowered = filename.lower()
    if "formula" in lowered or "equation" in lowered or "latex" in lowered:
        return "formula_image"
    return "image"


def _guess_page_num(filename: str) -> int | None:
    match = _PAGE_RE.search(filename)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _read_image_dimensions(path: Path) -> tuple[int | None, int | None]:
    if Image is None:
        return None, None
    try:
        with Image.open(path) as image:
            return image.width, image.height
    except Exception:
        return None, None


def _build_asset_rows(*, raw_file_id: int, asset_dir: Path) -> list[RawFileAsset]:
    rows: list[RawFileAsset] = []
    if not asset_dir.exists():
        return rows
    for path in sorted(asset_dir.iterdir()):
        if not path.is_file():
            continue
        width, height = _read_image_dimensions(path)
        rows.append(
            RawFileAsset(
                raw_file_id=raw_file_id,
                asset_name=path.name,
                asset_kind=_guess_asset_kind(path.name),
                storage_backend="local",
                storage_key=to_storage_key(path),
                mime_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                page_num=_guess_page_num(path.name),
                width=width,
                height=height,
            )
        )
    return rows


def build_finalize_success_node(*, context: WorkflowContext):
    """Phase 1 finalize: sets status to FAST_PARSED, publishes event.

    After this node, the file is immediately visible to the frontend while
    Phase 2 (deep enhance) starts in the background.
    """

    async def finalize_success_node(state: IngestParseState) -> IngestParseState:
        logger = workflow_logger(context, state)
        cs = get_content_store()
        try:
            markdown_path = state["markdown_path"]  # str key
            asset_dir = state["asset_dir"]  # str key
            parsed_markdown = state.get("parsed_markdown")

            # 统一读取逻辑：从 state 或 storage 读 markdown
            if parsed_markdown is None:
                parsed_markdown = run_store_sync(cs.read_text, markdown_path, default=None)
                if parsed_markdown is None:
                    # 尝试从本地临时路径读取
                    local_md = Path(state.get("_local_markdown_path", ""))
                    if local_md.exists():
                        parsed_markdown = local_md.read_text(encoding="utf-8")

            # 将 markdown 写回 storage（确保持久化）
            if parsed_markdown:
                run_store_sync(cs.write_text, markdown_path, parsed_markdown)

            # 处理 assets：检查本地临时目录，上传到 storage
            local_asset_dir = Path(state.get("_local_asset_dir", asset_dir))
            asset_rows: list[RawFileAsset] = []
            if local_asset_dir.exists() and local_asset_dir.is_dir():
                # 上传 assets 到正式 storage
                run_store_sync(
                    cs.upload_dir,
                    local_asset_dir,
                    cs.asset_prefix(state["subject"], state["file_id"]),
                )
                asset_rows = _build_asset_rows(raw_file_id=state["file_id"], asset_dir=local_asset_dir)
            else:
                asset_rows = _build_asset_rows(raw_file_id=state["file_id"], asset_dir=Path(asset_dir))

            with managed_session() as session:
                raw_file = get_raw_file_by_id(session, state["file_id"])
                if raw_file is None or raw_file.subject != state["subject"]:
                    return {
                        **state,
                        "error": f"raw_file_not_found:{state['file_id']}",
                    }

                replace_raw_file_assets(session, raw_file_id=state["file_id"], assets=asset_rows)
                update_raw_file(
                    session,
                    raw_file,
                    parsed_markdown=parsed_markdown or "",
                    parser_used=state.get("parser_used"),
                    parse_metadata_json=state.get("parse_metadata") or "{}",
                    parse_error_message=None,
                    classification_json=state.get("classification_payload") or "{}",
                    quality_score=None,
                    image_count=len(asset_rows),
                    status=TaskStatus.COMPLETED.value,
                    ingest_status=IngestStatus.FAST_PARSED.value,
                    digest_current_step="ingest.fast_parse.completed",
                    size_bytes=state.get("file_size_bytes"),
                    checksum_sha256=state.get("content_hash"),
                    estimated_pages=state.get("estimated_pages"),
                    detected_language=state.get("detected_language"),
                    markdown_path=str(markdown_path),
                    asset_dir=str(asset_dir),
                )

            # Publish Phase 1 completion event
            await context.event_bus.publish(
                IngestFileFastParsedEvent(
                    subject=state["subject"],
                    file_id=state["file_id"],
                    parser_used=state.get("parser_used") or "",
                    markdown_chars=state.get("markdown_chars", 0),
                    image_count=state.get("image_count", 0),
                )
            )
            logger.info(
                "ingest_file_fast_parse_finalized",
                parser_used=state.get("parser_used"),
                markdown_chars=state.get("markdown_chars", 0),
                image_count=state.get("image_count", 0),
            )
            return {
                **state,
                "error": None,
            }
        except Exception as exc:
            logger.error("ingest_file_finalize_success_failed", error=str(exc), exc_info=True)
            return {
                **state,
                "error": f"finalize_success_failed: {exc}",
            }

    return finalize_success_node


def build_finalize_failure_node(*, context: WorkflowContext):
    """Phase 1 failure finalize: sets status to FAILED."""

    async def finalize_failure_node(state: IngestParseState) -> IngestParseState:
        logger = workflow_logger(context, state)
        error_message = state.get("error", "unknown_error")
        with managed_session() as session:
            raw_file = get_raw_file_by_id(session, state["file_id"])
            if raw_file is not None and raw_file.subject == state["subject"]:
                update_raw_file(
                    session,
                    raw_file,
                    parse_error_message=error_message,
                    status=TaskStatus.FAILED.value,
                    ingest_status=IngestStatus.FAILED.value,
                    digest_current_step="ingest.parse.failed",
                )
        await context.event_bus.publish(
            IngestFileParseFailedEvent(
                subject=state["subject"],
                file_id=state["file_id"],
                error_message=error_message,
            )
        )
        logger.error("ingest_file_finalize_failed", error=error_message)
        return state

    return finalize_failure_node
