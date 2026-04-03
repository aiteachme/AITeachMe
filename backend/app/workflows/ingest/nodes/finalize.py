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

from app.shared.infra.config import get_settings
from app.shared.infra.database import managed_session
from app.shared.infra.storage import get_artifact_store
from app.models import IngestStatus, RawFileAsset, TaskStatus
from app.repositories.files_repo import get_raw_file_by_id, replace_raw_file_assets, update_raw_file
from app.utils.path_helpers import to_storage_key
from app.workflows.common.context import WorkflowContext
from app.workflows.ingest.events import (
    IngestFileFastParsedEvent,
    IngestFileParseFailedEvent,
    IngestFileReadyForDigestEvent,
)
from app.workflows.ingest.nodes.common import workflow_logger
from app.workflows.ingest.state import IngestParseState

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
        settings = get_settings()
        try:
            markdown_path = Path(state["markdown_path"])
            asset_dir = Path(state["asset_dir"])
            parsed_markdown = state.get("parsed_markdown")

            if settings.is_cloud_mode:
                # cloud 模式：markdown_path 和 asset_dir 存的是 storage_key
                # parsed_markdown 应该已经在 state 中（解析器产出）
                # 如果没有，尝试从本地临时文件读取
                if parsed_markdown is None:
                    # 解析器可能把 markdown 写到了本地临时路径
                    local_md = Path(state.get("_local_markdown_path", ""))
                    if local_md.exists():
                        parsed_markdown = local_md.read_text(encoding="utf-8")

                # 把 markdown 写回 OSS
                store = get_artifact_store()
                md_storage_key = state["markdown_path"]  # 已经是 storage_key
                if parsed_markdown:
                    await store.write_bytes(md_storage_key, parsed_markdown.encode("utf-8"))

                # 把 assets 写回 OSS（解析器可能把 assets 写到了本地临时 asset_dir）
                local_asset_dir = Path(state.get("_local_asset_dir", str(asset_dir)))
                asset_rows: list[RawFileAsset] = []
                if local_asset_dir.exists() and local_asset_dir.is_dir():
                    for path in sorted(local_asset_dir.iterdir()):
                        if not path.is_file():
                            continue
                        asset_key = f"{state['subject']}/assets/{state['file_id']}/{path.name}"
                        await store.write_file(asset_key, path)
                        width, height = _read_image_dimensions(path)
                        asset_rows.append(
                            RawFileAsset(
                                raw_file_id=state["file_id"],
                                asset_name=path.name,
                                asset_kind=_guess_asset_kind(path.name),
                                storage_backend="s3",
                                storage_key=asset_key,
                                mime_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                                page_num=_guess_page_num(path.name),
                                width=width,
                                height=height,
                            )
                        )
            else:
                # local 模式：原有逻辑
                if parsed_markdown is None and markdown_path.exists():
                    parsed_markdown = markdown_path.read_text(encoding="utf-8")
                asset_rows = _build_asset_rows(raw_file_id=state["file_id"], asset_dir=asset_dir)

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
