from __future__ import annotations

import asyncio
import json
import mimetypes
import re
import shutil
import time
from pathlib import Path

import structlog

from app.core.database import managed_session
from app.models import IngestStatus, RawFileAsset, TaskStatus
from app.repositories.files_repo import get_raw_file_by_id, replace_raw_file_assets, update_raw_file
from app.services.upload_support import (
    build_asset_dir,
    build_asset_name_prefix,
    build_raw_markdown_path,
    resolve_storage_key_path,
    to_storage_key,
)
from app.workflows.common.result import WorkflowResult, err_result, ok_result
from app.workflows.ingest.events import (
    IngestFileEnhanceFailedEvent,
    IngestFileEnhanceStartedEvent,
    IngestFileFastParsedEvent,
    IngestFileReadyForDigestEvent,
)
from app.workflows.ingest.parsing.classifier import ClassificationResult, classify_file
from app.workflows.ingest.parsing.formats import (
    categorize_text_extension,
    get_text_language_hint,
    is_image_extension,
    is_text_extension,
)
from app.workflows.ingest.parsing.orchestrator import deep_enhance_file, fast_parse_file
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


# ── Phase 2 background task ──


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

    try:
        # Load context from DB
        with managed_session() as session:
            raw_file = get_raw_file_by_id(session, file_id)
            if raw_file is None:
                enhance_logger.warning("deep_enhance_raw_file_not_found")
                return

            file_path = resolve_storage_key_path(raw_file.storage_key)
            markdown_path = build_raw_markdown_path(subject, file_id)
            asset_dir = build_asset_dir(subject, file_id)
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
        if extension == ".pdf":
            try:
                from app.workflows.ingest.parsing.pdf import parse_pdf_with_pymupdf4llm, PDF_PYMUPDF4LLM_AVAILABLE
                from app.workflows.ingest.parsing.types import ParserRunOptions
                from app.workflows.ingest.parsing.canonicalizer import canonicalize_markdown

                if PDF_PYMUPDF4LLM_AVAILABLE:
                    quality_options = ParserRunOptions(
                        ocr_language_mode=parse_plan.options.ocr_language_mode,
                        asset_name_prefix=asset_name_prefix,
                    )
                    raw_quality = await parse_pdf_with_pymupdf4llm(
                        file_path, asset_dir, quality_options,
                    )
                    quality_md = canonicalize_markdown(raw_quality)
                    # Only use quality version if it has reasonable content
                    if quality_md and len(quality_md.strip()) > len(markdown.strip()) * 0.5:
                        markdown = quality_md
                        markdown_path.write_text(markdown, encoding="utf-8")
                        enhance_logger.info(
                            "quality_reparse_completed",
                            parser="pymupdf4llm",
                            chars_before=len(markdown),
                            chars_after=len(quality_md),
                        )
            except Exception as exc:
                enhance_logger.warning("quality_reparse_failed", error=str(exc))
                # Continue with Phase 1 markdown — quality re-parse is best-effort

        # ── Step 2: LLM OCR enrichment (only if vision model configured) ──
        from app.core.config import get_settings
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
            # Create a dummy result — no OCR was done
            from app.workflows.ingest.parsing.orchestrator import DeepEnhanceResult
            enhance_result = DeepEnhanceResult(markdown=markdown)

        # Overwrite markdown with enhanced version
        markdown_path.write_text(enhance_result.markdown, encoding="utf-8")

        # Update DB: READY_FOR_DIGEST
        with managed_session() as session:
            raw_file = get_raw_file_by_id(session, file_id)
            if raw_file is not None:
                # Update parse_metadata with OCR stats
                parse_metadata = {}
                if raw_file.parse_metadata_json:
                    try:
                        parse_metadata = json.loads(raw_file.parse_metadata_json)
                    except Exception:
                        pass
                parse_metadata["asset_ocr_images"] = enhance_result.asset_ocr_images
                parse_metadata["asset_ocr_replacements"] = enhance_result.asset_ocr_replacements
                parse_metadata["provider_status"] = "enhanced"

                update_raw_file(
                    session,
                    raw_file,
                    parsed_markdown=enhance_result.markdown,
                    parse_metadata_json=json.dumps(parse_metadata, ensure_ascii=False),
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


# ── Main entry point ──


async def run_parse_file_workflow(
    *,
    subject: str,
    file_id: int,
    event_bus=None,
) -> WorkflowResult[IngestParseState]:
    """Two-phase ingest workflow entry point.

    Phase 1 (synchronous): traditional parsing → FAST_PARSED → returns immediately.
    Phase 2 (background): LLM OCR enhancement → READY_FOR_DIGEST → auto-dispatched.
    """

    logger.info(
        "ingest_workflow_started",
        subject=subject,
        file_id=file_id,
        phase="Phase 1 (Fast Parse)",
    )

    try:
        with managed_session() as session:
            raw_file = get_raw_file_by_id(session, file_id)
            if raw_file is None:
                logger.warning("ingest_workflow_raw_file_not_found", file_id=file_id)
                return err_result(
                    "raw_file_not_found",
                    f"源文件 `{file_id}` 不存在。",
                    metadata={"subject": subject, "file_id": file_id},
                )

            file_path = resolve_storage_key_path(raw_file.storage_key)
            if not file_path.exists():
                logger.warning("ingest_storage_file_missing", file_id=file_id, path=str(file_path))
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

            # file_service.py already set status=PROCESSING, ingest=CLASSIFYING
            # so we only need to clear the error message
            if raw_file.parse_error_message:
                raw_file.parse_error_message = None
                session.add(raw_file)
                session.commit()
                session.refresh(raw_file)

            # ── Fast Path: text/markdown/code files skip classify+plan entirely ──
            # (改进 2: RAGFlow Naive + LangChain 直通思路)
            ext = raw_file.file_ext.lower()
            if is_text_extension(ext):
                t0 = time.perf_counter()
                raw_text = file_path.read_text(encoding="utf-8", errors="replace")
                lang_hint = get_text_language_hint(ext)
                text_category = categorize_text_extension(ext)

                # Wrap structured text in code block with language hint
                if text_category == "structured_text" and lang_hint:
                    markdown = f"```{lang_hint}\n{raw_text}\n```"
                elif text_category == "markdown":
                    markdown = raw_text
                else:
                    markdown = raw_text

                # Write raw markdown file
                markdown_path = build_raw_markdown_path(subject, file_id)
                markdown_path.parent.mkdir(parents=True, exist_ok=True)
                markdown_path.write_text(markdown, encoding="utf-8")

                elapsed = time.perf_counter() - t0
                logger.info(
                    "ingest_fast_path_text_completed",
                    subject=subject,
                    file_id=file_id,
                    filename=raw_file.original_filename,
                    text_category=text_category,
                    lang_hint=lang_hint,
                    chars=len(markdown),
                    elapsed_ms=round(elapsed * 1000, 1),
                )

                update_raw_file(
                    session,
                    raw_file,
                    parsed_markdown=markdown,
                    parser_used="text_native",
                    parse_metadata_json=json.dumps({
                        "parser_used": "text_native",
                        "fast_path": True,
                        "text_category": text_category,
                        "lang_hint": lang_hint,
                        "parse_elapsed_ms": round(elapsed * 1000, 1),
                    }, ensure_ascii=False),
                    parse_error_message=None,
                    status=TaskStatus.COMPLETED.value,
                    ingest_status=IngestStatus.READY_FOR_DIGEST.value,
                    digest_current_step="ingest.fast_path.completed",
                )

                return ok_result({
                    "subject": subject,
                    "file_id": file_id,
                    "filename": raw_file.original_filename,
                    "filetype": raw_file.file_ext,
                    "error": None,
                    "fast_path": True,
                })

            # ── Regular Path: classify → plan → parse for PDF/DOCX/PPTX/images ──
            logger.info(
                "ingest_classify_started",
                subject=subject,
                file_id=file_id,
                filename=raw_file.original_filename,
                filetype=raw_file.file_ext,
                size_bytes=raw_file.size_bytes,
            )
            classification = await asyncio.to_thread(classify_file, file_path, raw_file.file_ext)
            classification_payload = classification.to_dict()
            logger.info(
                "ingest_classify_completed",
                subject=subject,
                file_id=file_id,
                file_category=classification.file_category,
                recommended_parser=classification.recommended_parser,
                detected_language=classification.detected_language,
                estimated_pages=classification.estimated_pages,
                has_tables=classification.has_tables,
                has_formulas=classification.has_formulas,
            )
            update_raw_file(
                session,
                raw_file,
                classification_json=json.dumps(classification_payload, ensure_ascii=False),
                detected_language=classification.detected_language,
                estimated_pages=classification.estimated_pages,
                ingest_status=IngestStatus.FAST_PARSING.value,
                digest_current_step="ingest.fast_parse.running",
            )

            # Build parse plan
            parse_plan = build_parse_plan(
                file_path=file_path,
                filetype=raw_file.file_ext,
                file_size_bytes=raw_file.size_bytes,
                classification=classification,
            )
            logger.info(
                "ingest_parse_plan_built",
                subject=subject,
                file_id=file_id,
                parse_mode=parse_plan.mode,
                parser_chain=parse_plan.parser_chain,
                decision_reason=parse_plan.decision_reason,
                enable_asset_vision_ocr=parse_plan.options.enable_asset_vision_ocr,
                llm_ocr_page_concurrency=parse_plan.options.llm_ocr_page_concurrency,
            )
            asset_dir = build_asset_dir(subject, file_id)
            if asset_dir.exists():
                shutil.rmtree(asset_dir, ignore_errors=True)
            asset_dir.mkdir(parents=True, exist_ok=True)

            markdown_path = build_raw_markdown_path(subject, file_id)
            markdown_path.parent.mkdir(parents=True, exist_ok=True)

            asset_name_prefix = build_asset_name_prefix(
                filename=raw_file.original_filename,
                file_uid=raw_file.uid,
                file_id=file_id,
            )
            parse_plan.options.asset_name_prefix = asset_name_prefix

        # ── Phase 1: Fast Parse (synchronous) ──

        logger.info(
            "ingest_fast_parse_started",
            subject=subject,
            file_id=file_id,
            filename=raw_file.original_filename,
            parse_mode=parse_plan.mode,
            parser_chain=parse_plan.parser_chain,
        )
        parse_result = await fast_parse_file(
            file_path=file_path,
            asset_dir=asset_dir,
            classification=classification,
            parse_plan=parse_plan,
            asset_link_prefix=f"../assets/{file_id}",
        )

        # Save Phase 1 results
        markdown_path.write_text(parse_result.markdown, encoding="utf-8")
        asset_rows = _build_asset_rows(raw_file_id=file_id, asset_dir=asset_dir)
        parse_metadata = {
            "provider_used": parse_result.parser_used,
            "provider_status": "fast_parsed",
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
            "asset_ocr_images": 0,
            "asset_ocr_replacements": 0,
            "needs_enhance": parse_result.needs_enhance,
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

            # Set status to FAST_PARSED (not READY_FOR_DIGEST yet)
            final_ingest_status = (
                IngestStatus.FAST_PARSED.value
                if parse_result.needs_enhance
                else IngestStatus.READY_FOR_DIGEST.value
            )
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
                ingest_status=final_ingest_status,
                digest_current_step=(
                    "ingest.fast_parse.completed"
                    if parse_result.needs_enhance
                    else "ingest.parse.completed"
                ),
            )

        logger.info(
            "ingest_fast_parse_completed",
            subject=subject,
            file_id=file_id,
            parser_used=parse_result.parser_used,
            parse_mode=parse_plan.mode,
            asset_count=len(asset_rows),
            quality_score=quality_score,
            needs_enhance=parse_result.needs_enhance,
        )

        # ── Phase 2: Background enhance (quality re-parse + optional OCR) ──
        # Phase 2 always dispatches: pymupdf4llm quality re-parse runs without LLM.
        # LLM OCR only runs when OCR_MODEL is explicitly configured.

        if parse_result.needs_enhance:
            logger.info("dispatching_deep_enhance_background", subject=subject, file_id=file_id)
            asyncio.create_task(
                _run_deep_enhance_background(
                    subject=subject,
                    file_id=file_id,
                    event_bus=event_bus,
                )
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
    except Exception as exc:
        logger.exception("ingest_workflow_unhandled_error", subject=subject, file_id=file_id, error=str(exc))
        try:
            with managed_session() as session:
                raw_file = get_raw_file_by_id(session, file_id)
                if raw_file is not None:
                    update_raw_file(
                        session,
                        raw_file,
                        status=TaskStatus.FAILED.value,
                        ingest_status=IngestStatus.FAILED.value,
                        parse_error_message=str(exc),
                        digest_current_step="ingest.unhandled_error",
                    )
        except Exception:
            logger.exception("ingest_workflow_error_recovery_failed", file_id=file_id)
        return err_result("ingest_unhandled_error", str(exc), metadata={"subject": subject, "file_id": file_id})
