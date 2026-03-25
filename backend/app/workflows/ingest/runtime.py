"""Ingest runtime entrypoints backed by the new raw-file schema."""

from __future__ import annotations

import json
import mimetypes
import re
import shutil
from pathlib import Path

import structlog

from app.core.database import managed_session
from app.models import IngestStatus, RawFileAsset, TaskStatus
from app.repositories.files_repo import get_raw_file_by_id, replace_raw_file_assets, update_raw_file
from app.services.upload_support import (
    build_asset_dir,
    build_raw_markdown_path,
    resolve_storage_key_path,
    to_storage_key,
)
from app.workflows.common.result import WorkflowResult, err_result, ok_result
from app.workflows.ingest.parsing.classifier import classify_file
from app.workflows.ingest.parsing.orchestrator import parse_file
from app.workflows.ingest.parsing.strategy import build_parse_plan
from app.workflows.ingest.state import IngestParseState

try:
    from PIL import Image
except ImportError:
    Image = None

logger = structlog.get_logger()

_PAGE_RE = re.compile(r"(?:page|p|slide|s)[_\-]?(\d{1,4})", re.IGNORECASE)


def create_parse_file_initial_state(*, subject: str, file_id: int) -> IngestParseState:
    return {
        "subject": subject,
        "file_id": file_id,
        "error": None,
    }


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


def _compute_quality_score(*, markdown: str, image_count: int, classification: dict[str, object]) -> float:
    score = 0.55
    if markdown.strip():
        score += 0.2
    if len(markdown.strip()) >= 500:
        score += 0.1
    if image_count > 0:
        score += 0.05
    if classification.get("has_tables"):
        score += 0.05
    if classification.get("has_formulas"):
        score += 0.05
    return max(0.0, min(round(score, 3), 1.0))


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
    for path in sorted(asset_dir.iterdir()):
        if not path.is_file():
            continue
        mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        width, height = _read_image_dimensions(path)
        rows.append(
            RawFileAsset(
                raw_file_id=raw_file_id,
                asset_name=path.name,
                asset_kind=_guess_asset_kind(path.name),
                storage_backend="local",
                storage_key=to_storage_key(path),
                mime_type=mime_type,
                page_num=_guess_page_num(path.name),
                width=width,
                height=height,
                ocr_text=None,
            )
        )
    return rows


async def run_parse_file_workflow(
    *,
    subject: str,
    file_id: int,
    event_bus=None,
) -> WorkflowResult[IngestParseState]:
    del event_bus

    with managed_session() as session:
        raw_file = get_raw_file_by_id(session, file_id)
        if raw_file is None:
            return err_result(
                "raw_file_not_found",
                f"源文件 `{file_id}` 不存在。",
                metadata={"subject": subject, "file_id": file_id},
            )

        file_path = resolve_storage_key_path(raw_file.storage_key)
        if not file_path.exists():
            update_raw_file(
                session,
                raw_file,
                status=TaskStatus.FAILED.value,
                ingest_status=IngestStatus.FAILED.value,
                parse_error_message="源文件不存在，无法继续解析。",
                digest_current_step="ingest.parse.failed",
            )
            return err_result(
                "raw_file_missing_storage",
                "源文件不存在，无法继续解析。",
                metadata={"subject": subject, "file_id": file_id, "filename": raw_file.original_filename},
            )

        raw_file.status = TaskStatus.PROCESSING.value
        raw_file.ingest_status = IngestStatus.CLASSIFYING.value
        raw_file.digest_current_step = "ingest.classify"
        raw_file.parse_error_message = None
        session.add(raw_file)
        session.commit()
        session.refresh(raw_file)

        classification = classify_file(file_path, raw_file.file_ext)
        classification_payload = classification.to_dict()
        update_raw_file(
            session,
            raw_file,
            classification_json=json.dumps(classification_payload, ensure_ascii=False),
            detected_language=classification.detected_language,
            estimated_pages=classification.estimated_pages,
            ingest_status=IngestStatus.PARSING.value,
            digest_current_step="ingest.parse.running",
        )

        parse_plan = build_parse_plan(
            file_path=file_path,
            filetype=raw_file.file_ext,
            file_size_bytes=raw_file.size_bytes,
            classification=classification,
        )
        asset_dir = build_asset_dir(subject, file_id)
        if asset_dir.exists():
            shutil.rmtree(asset_dir, ignore_errors=True)
        asset_dir.mkdir(parents=True, exist_ok=True)

        markdown_path = build_raw_markdown_path(subject, file_id)
        markdown_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        parse_result = await parse_file(
            file_path=file_path,
            asset_dir=asset_dir,
            classification=classification,
            parse_plan=parse_plan,
            asset_link_prefix=f"../assets/{file_id}",
        )
    except Exception as exc:  # noqa: BLE001
        with managed_session() as session:
            raw_file = get_raw_file_by_id(session, file_id)
            if raw_file is not None:
                update_raw_file(
                    session,
                    raw_file,
                    status=TaskStatus.FAILED.value,
                    ingest_status=IngestStatus.FAILED.value,
                    parse_error_message=str(exc),
                    parser_used=None,
                    digest_current_step="ingest.parse.failed",
                )
        logger.exception("ingest_parse_failed", subject=subject, file_id=file_id, error=str(exc))
        return err_result(
            "ingest_parse_failed",
            str(exc),
            metadata={
                "subject": subject,
                "file_id": file_id,
                "filename": raw_file.original_filename if raw_file is not None else None,
                "filetype": raw_file.file_ext if raw_file is not None else None,
                "parse_mode": parse_plan.mode if parse_plan else None,
                "parser_chain": parse_plan.parser_chain if parse_plan else None,
            },
        )

    markdown_path.write_text(parse_result.markdown, encoding="utf-8")
    asset_rows = _build_asset_rows(raw_file_id=file_id, asset_dir=asset_dir)
    parse_metadata = {
        "provider_used": parse_result.parser_used,
        "provider_status": "completed",
        "parser_used": parse_result.parser_used,
        "parse_mode": parse_plan.mode,
        "decision_reason": parse_plan.decision_reason,
        "parser_chain": parse_plan.parser_chain,
        "attempted_parsers": parse_result.attempted_parsers,
        "parser_elapsed_s": parse_result.parser_elapsed_s,
        "requested_features": [],
        "applied_features": [],
        "skipped_features": [],
        "failed_feature": None,
        "provider_failure_reason": None,
        "rewritten_image_refs": parse_result.rewritten_image_refs,
        "extracted_data_images": parse_result.extracted_data_images,
        "appended_asset_images": parse_result.appended_asset_images,
        "asset_ocr_images": parse_result.asset_ocr_images,
        "asset_ocr_replacements": parse_result.asset_ocr_replacements,
        "raw_markdown_storage_key": to_storage_key(markdown_path),
        "asset_storage_dir": to_storage_key(asset_dir),
    }
    quality_score = _compute_quality_score(
        markdown=parse_result.markdown,
        image_count=len(asset_rows),
        classification=classification_payload,
    )

    with managed_session() as session:
        raw_file = get_raw_file_by_id(session, file_id)
        if raw_file is None:
            return err_result(
                "raw_file_not_found",
                f"源文件 `{file_id}` 不存在。",
                metadata={"subject": subject, "file_id": file_id},
            )
        replace_raw_file_assets(session, raw_file_id=file_id, assets=asset_rows)
        update_raw_file(
            session,
            raw_file,
            parsed_markdown=parse_result.markdown,
            parser_used=parse_result.parser_used,
            parse_metadata_json=json.dumps(parse_metadata, ensure_ascii=False),
            parse_error_message=None,
            classification_json=json.dumps(classification_payload, ensure_ascii=False),
            quality_score=quality_score,
            image_count=len(asset_rows),
            estimated_pages=classification.estimated_pages,
            detected_language=classification.detected_language,
            status=TaskStatus.COMPLETED.value,
            ingest_status=IngestStatus.READY_FOR_DIGEST.value,
            digest_current_step="ingest.parse.completed",
        )

    logger.info(
        "ingest_parse_completed",
        subject=subject,
        file_id=file_id,
        parser_used=parse_result.parser_used,
        parse_mode=parse_plan.mode,
        parser_chain=parse_plan.parser_chain,
        asset_count=len(asset_rows),
        quality_score=quality_score,
    )
    return ok_result(
        {
            "subject": subject,
            "file_id": file_id,
            "filename": raw_file.original_filename,
            "filetype": raw_file.file_ext,
            "error": None,
            "parse_plan": parse_plan,
        }
    )
