"""Phase 2 background task: deep OCR enhancement of parsed files."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import structlog

from app.shared.infra.settings import get_settings
from app.shared.infra.database import managed_session
from app.shared.infra.storage import get_content_store, run_store_sync
from app.models import IngestStatus
from app.repositories.files_repo import get_raw_file_by_id, replace_raw_file_assets, update_raw_file
from app.utils.path_helpers import build_asset_name_prefix
from app.workflows.ingest.events import (
    IngestFileEnhanceFailedEvent,
    IngestFileEnhanceStartedEvent,
    IngestFileReadyForDigestEvent,
)
from app.workflows.ingest.common.parsing.classifier import ClassificationResult
from app.workflows.ingest.common.parsing.orchestrator import deep_enhance_file
from app.workflows.ingest.common.parsing.strategy import build_parse_plan
from app.workflows.ingest.common.parsing.types import ParserRunOptions
from app.workflows.ingest.fast_parse.lib.runtime_helpers import _build_asset_rows

logger = structlog.get_logger()


async def _materialize_stored_assets(
    *,
    subject: str,
    file_id: int,
    asset_dir: Path,
) -> int:
    """Copy persisted Phase 1 assets into the Phase 2 work directory."""

    cs = get_content_store()
    prefix = cs.asset_prefix(subject, file_id)
    keys = await cs.list_prefix(prefix)
    copied = 0
    for key in keys:
        relative_name = key[len(prefix):].lstrip("/\\") if key.startswith(prefix) else Path(key).name
        if not relative_name or ".." in Path(relative_name).parts:
            continue
        target = asset_dir / relative_name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(await cs.read_bytes(key))
        copied += 1
    return copied


async def _run_deep_enhance_background(
    *,
    subject: str,
    file_id: int,
    event_bus=None,
) -> None:
    """Background Phase 2: LLM Vision OCR enhancement.

    This runs as an asyncio.Task after Phase 1 completes. It reads the
    Phase 1 markdown, enhances it with OCR, and updates the DB status.
    """

    enhance_logger = logger.bind(subject=subject, file_id=file_id, phase="deep_enhance")
    enhance_logger.info("deep_enhance_background_started")

    cs = get_content_store()
    try:
        with tempfile.TemporaryDirectory(prefix="atm_enhance_") as tmp_dir_str:
            _temp_dir = Path(tmp_dir_str)
            # Load context from DB
            with managed_session() as session:
                raw_file = get_raw_file_by_id(session, file_id)
                if raw_file is None:
                    enhance_logger.warning("deep_enhance_raw_file_not_found")
                    return

                original_storage_backend = raw_file.storage_backend or "local"
                original_parser_used = raw_file.parser_used

                file_path = await cs.materialize(raw_file.file_path or raw_file.storage_key, _temp_dir)
                # Materialize markdown to temp for Phase 2 parsing
                md_key = raw_file.markdown_path or cs.raw_markdown_key(subject, file_id)
                markdown_path = _temp_dir / f"{file_id}.md"
                md_text = run_store_sync(cs.read_text, md_key, default=None)
                if md_text:
                    markdown_path.write_text(md_text, encoding="utf-8")
                else:
                    markdown_path.write_text(raw_file.markdown_content or "", encoding="utf-8")
                asset_dir = _temp_dir / "assets" / str(file_id)
                asset_dir.mkdir(parents=True, exist_ok=True)
                asset_name_prefix = build_asset_name_prefix(
                    filename=raw_file.original_filename,
                    file_uid=raw_file.uid,
                    file_id=file_id,
                )

                # Rebuild classification and parse_plan
                classification = None
                if raw_file.classification_json:
                    try:
                        classification = ClassificationResult(**json.loads(raw_file.classification_json))
                    except Exception:
                        pass

                parse_plan = build_parse_plan(
                    file_path=str(file_path),
                    filetype=raw_file.file_ext,
                    file_size_bytes=raw_file.size_bytes,
                    classification=classification,
                )
                parse_plan.options.asset_name_prefix = asset_name_prefix

                # Update status to ENHANCING
                update_raw_file(
                    session,
                    raw_file,
                    ingest_status=IngestStatus.ENHANCING.value,
                    digest_current_step="ingest.enhance.running",
                )

            materialized_asset_count = await _materialize_stored_assets(
                subject=subject,
                file_id=file_id,
                asset_dir=asset_dir,
            )
            enhance_logger.info(
                "deep_enhance_assets_materialized",
                asset_count=materialized_asset_count,
            )

            # Publish enhance started event
            if event_bus is not None:
                await event_bus.publish(
                    IngestFileEnhanceStartedEvent(subject=subject, file_id=file_id)
                )

            # Read Phase 1 markdown
            if not markdown_path.exists():
                enhance_logger.warning("deep_enhance_markdown_not_found", path=str(markdown_path))
                with managed_session() as session:
                    raw_file = get_raw_file_by_id(session, file_id)
                    if raw_file is not None:
                        update_raw_file(
                            session,
                            raw_file,
                            ingest_status=IngestStatus.ENHANCE_FAILED.value,
                            digest_current_step="ingest.enhance.failed",
                        )
                return

            markdown = markdown_path.read_text(encoding="utf-8")

            # ── Step 1: Quality re-parse with pymupdf4llm (no LLM needed) ──
            # Phase 1 used pymupdf_native for speed. Now re-parse with pymupdf4llm
            # for better markdown formatting (tables, headings, formula rendering).
            extension = Path(str(file_path)).suffix.lower()
            # MinerU already returns a high-quality markdown; avoid overriding it here.
            if extension == ".pdf" and original_parser_used != "mineru":
                try:
                    from app.workflows.ingest.common.parsing.pdf import parse_pdf_with_pymupdf4llm, PDF_PYMUPDF4LLM_AVAILABLE
                    from app.workflows.ingest.common.parsing.canonicalizer import canonicalize_markdown

                    if PDF_PYMUPDF4LLM_AVAILABLE:
                        quality_options = ParserRunOptions(
                            ocr_language_mode=parse_plan.options.ocr_language_mode,
                            asset_name_prefix=asset_name_prefix,
                        )
                        raw_quality = await parse_pdf_with_pymupdf4llm(
                            file_path, asset_dir, quality_options,
                        )
                        quality_result = canonicalize_markdown(
                            raw_quality,
                            asset_dir=asset_dir,
                            asset_link_prefix=f"../assets/{file_id}",
                            asset_name_prefix=asset_name_prefix,
                        )
                        quality_md = quality_result.markdown
                        # Only use quality version if it has reasonable content.
                        if quality_md and len(quality_md.strip()) > len(markdown.strip()) * 0.5:
                            old_chars = len(markdown)
                            markdown = quality_md
                            markdown_path.write_text(markdown, encoding="utf-8")
                            enhance_logger.info(
                                "quality_reparse_completed",
                                parser="pymupdf4llm",
                                chars_before=old_chars,
                                chars_after=len(quality_md),
                            )
                except Exception as exc:
                    enhance_logger.warning("quality_reparse_failed", error=str(exc))
                    # Continue with Phase 1 markdown; quality re-parse is best-effort.

            # ── Step 2: LLM OCR enrichment (only if vision model configured) ──
            has_vision = get_settings().has_vision_ocr_model

            if has_vision:
                enhance_result = await deep_enhance_file(
                    markdown,
                    file_path=str(file_path),
                    asset_dir=str(asset_dir),
                    asset_link_prefix=f"../assets/{file_id}",
                    asset_name_prefix=asset_name_prefix,
                    parse_plan=parse_plan,
                    classification=classification,
                )
            else:
                enhance_logger.info(
                    "skipping_ocr_no_vision_model",
                    hint="Set OCR_MODEL in .env to enable LLM OCR (e.g. OCR_MODEL=qwen-vl-max)",
                )
                # Create a dummy result; no OCR was done.
                from app.workflows.ingest.common.parsing.orchestrator import DeepEnhanceResult
                enhance_result = DeepEnhanceResult(markdown=markdown)

            # Overwrite markdown with enhanced version and persist assets together.
            markdown_path.write_text(enhance_result.markdown, encoding="utf-8")
            md_key = raw_file.markdown_path or cs.raw_markdown_key(subject, file_id)
            await cs.write_text(md_key, enhance_result.markdown)
            asset_prefix = cs.asset_prefix(subject, file_id)
            uploaded_asset_count = await cs.upload_dir(asset_dir, asset_prefix)
            asset_storage_dir = asset_prefix.rstrip("/")
            asset_rows = _build_asset_rows(
                raw_file_id=file_id,
                asset_dir=asset_dir,
                asset_storage_dir=asset_storage_dir,
                storage_backend=original_storage_backend,
            )

            # Update DB: READY_FOR_DIGEST
            with managed_session() as session:
                raw_file = get_raw_file_by_id(session, file_id)
                if raw_file is not None:
                    replace_raw_file_assets(session, raw_file_id=file_id, assets=asset_rows)
                    # Update parse_metadata with OCR stats and asset persistence stats.
                    parse_metadata = {}
                    if raw_file.parse_metadata_json:
                        try:
                            parse_metadata = json.loads(raw_file.parse_metadata_json)
                        except Exception:
                            pass
                    parse_metadata["asset_ocr_images"] = enhance_result.asset_ocr_images
                    parse_metadata["asset_ocr_replacements"] = enhance_result.asset_ocr_replacements
                    parse_metadata["provider_status"] = "enhanced"
                    parse_metadata["enhance_materialized_asset_count"] = materialized_asset_count
                    parse_metadata["enhance_uploaded_asset_count"] = uploaded_asset_count
                    parse_metadata["asset_storage_dir"] = asset_storage_dir

                    update_raw_file(
                        session,
                        raw_file,
                        parsed_markdown=enhance_result.markdown,
                        parse_metadata_json=json.dumps(parse_metadata, ensure_ascii=False),
                        image_count=len(asset_rows),
                        ingest_status=IngestStatus.READY_FOR_DIGEST.value,
                        digest_current_step="ingest.enhance.completed",
                    )

            # Publish ready event
            if event_bus is not None:
                await event_bus.publish(
                    IngestFileReadyForDigestEvent(subject=subject, file_id=file_id)
                )
            enhance_logger.info(
                "deep_enhance_background_completed",
                ocr_images=enhance_result.asset_ocr_images,
                ocr_replacements=enhance_result.asset_ocr_replacements,
                asset_count=len(asset_rows),
            )

    except Exception as exc:
        enhance_logger.exception("deep_enhance_background_failed", error=str(exc))
        # Mark as ENHANCE_FAILED (Phase 1 result preserved)
        try:
            with managed_session() as session:
                raw_file = get_raw_file_by_id(session, file_id)
                if raw_file is not None:
                    update_raw_file(
                        session,
                        raw_file,
                        ingest_status=IngestStatus.ENHANCE_FAILED.value,
                        digest_current_step="ingest.enhance.failed",
                        parse_error_message=f"Phase 2 enhance failed: {exc}",
                    )
            if event_bus is not None:
                await event_bus.publish(
                    IngestFileEnhanceFailedEvent(
                        subject=subject, file_id=file_id, error_message=str(exc)
                    )
                )
        except Exception:
            enhance_logger.exception("deep_enhance_failure_update_error")
