from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import mimetypes
import re
import shutil
import tempfile
import time
from pathlib import Path

import structlog

from app.shared.infra.config import get_settings
from app.shared.infra.database import managed_session
from app.shared.infra.storage import get_content_store, run_store_sync
from app.models import IngestStatus, RawFileAsset, TaskStatus
from app.repositories.files_repo import get_raw_file_by_id, replace_raw_file_assets, update_raw_file
from app.utils.path_helpers import build_asset_name_prefix
from app.workflows.common.result import WorkflowResult, err_result, ok_result
from app.workflows.ingest.events import (
    IngestFileEnhanceFailedEvent,
    IngestFileEnhanceStartedEvent,
    IngestFileReadyForDigestEvent,
)
from app.workflows.ingest.parsing.classifier import ClassificationResult, classify_file
from app.workflows.ingest.parsing.formats import (
    categorize_text_extension,
    get_text_language_hint,
    is_text_extension,
)
from app.workflows.ingest.parsing.orchestrator import deep_enhance_file, fast_parse_file
from app.workflows.ingest.parsing.strategy import ParsePlan, build_parse_plan
from app.workflows.ingest.parsing.types import ParserRunOptions
from app.workflows.ingest.state import IngestParseState
from app.workflows.ingest.parsing.mineru_cloud import MinerURequestOptions, parse_file_to_dir
from app.shared.infra.config import get_settings

try:
    from PIL import Image
except ImportError:
    Image = None

logger = structlog.get_logger()

_PAGE_RE = re.compile(r"(?:page|p|slide|s)[_\-]?(\d{1,4})", re.IGNORECASE)

# Track background tasks to prevent GC collection (RISK-2 fix)
_background_tasks: set[asyncio.Task] = set()


@dataclass(frozen=True, slots=True)
class _MinerUFastParseResult:
    markdown: str
    parser_used: str
    attempted_parsers: list[str]
    parser_elapsed_s: dict[str, float]
    rewritten_image_refs: int
    extracted_data_images: int
    appended_asset_images: int
    needs_enhance: bool


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


def _build_asset_rows(
    *,
    raw_file_id: int,
    asset_dir: Path,
    asset_storage_dir: str,
    storage_backend: str,
) -> list[RawFileAsset]:
    rows: list[RawFileAsset] = []
    normalized_storage_dir = asset_storage_dir.rstrip("/")
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
                storage_backend=storage_backend,
                storage_key=f"{normalized_storage_dir}/{path.name}",
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

    cs = get_content_store()
    settings = get_settings()
    try:
        # Load context from DB
        with managed_session() as session:
            raw_file = get_raw_file_by_id(session, file_id)
            if raw_file is None:
                enhance_logger.warning("deep_enhance_raw_file_not_found")
                return

            _temp_dir = Path(tempfile.mkdtemp(prefix="atm_enhance_"))
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
        if extension == ".pdf" and raw_file.parser_used != "mineru":
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
                    # BUG-2 fix: canonicalize_markdown returns CanonicalMarkdownResult, extract .markdown
                    quality_result = canonicalize_markdown(
                        raw_quality,
                        asset_dir=asset_dir,
                        asset_link_prefix=f"../assets/{file_id}",
                        asset_name_prefix=asset_name_prefix,
                    )
                    quality_md = quality_result.markdown
                    # Only use quality version if it has reasonable content
                    if quality_md and len(quality_md.strip()) > len(markdown.strip()) * 0.5:
                        # BUG-1 fix: capture old length before reassignment
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
                # Continue with Phase 1 markdown — quality re-parse is best-effort

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
            # Create a dummy result — no OCR was done
            from app.workflows.ingest.parsing.orchestrator import DeepEnhanceResult
            enhance_result = DeepEnhanceResult(markdown=markdown)

        # Overwrite markdown with enhanced version
        markdown_path.write_text(enhance_result.markdown, encoding="utf-8")
        md_key = raw_file.markdown_path or cs.raw_markdown_key(subject, file_id)
        await cs.write_text(md_key, enhance_result.markdown)

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
        requested_parser_provider: str | None = None
        mineru_token: str | None = None
        mineru_model_version: str = "vlm"
        mineru_enable_formula: bool = True
        mineru_enable_table: bool = True
        mineru_is_ocr: bool = False

        with managed_session() as session:
            raw_file = get_raw_file_by_id(session, file_id)
            if raw_file is None:
                logger.warning("ingest_workflow_raw_file_not_found", file_id=file_id)
                return err_result(
                    "raw_file_not_found",
                    f"源文件 `{file_id}` 不存在。",
                    metadata={"subject": subject, "file_id": file_id},
                )

            settings = get_settings()
            cs = get_content_store()
            _temp_base = Path(tempfile.mkdtemp(prefix="atm_ingest_"))
            file_path = await cs.materialize(raw_file.file_path or raw_file.storage_key, _temp_base)
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

            # ── Load "parse request" metadata (set at upload time) ──
            # 前端 settings 属于“本地配置”，后端后台 ingest 无法直接读取。
            # 因此 upload 时会把 parser_provider 与 MinerU 参数作为 multipart 字段传来，并暂存到 parse_metadata_json。
            # 这里读取后：
            # 1) 把 token 拿到内存中用于本次解析
            # 2) 立即把 DB 中的 token 擦掉（避免长期落盘敏感信息）
            try:
                parse_request_payload = json.loads(raw_file.parse_metadata_json or "{}")
                if not isinstance(parse_request_payload, dict):
                    parse_request_payload = {}
            except Exception:
                parse_request_payload = {}

            requested_parser_provider = parse_request_payload.get("requested_parser_provider")
            if isinstance(requested_parser_provider, str):
                requested_parser_provider = requested_parser_provider.strip() or None
            else:
                requested_parser_provider = None

            if requested_parser_provider == "mineru":
                mineru_block = parse_request_payload.get("mineru")
                if isinstance(mineru_block, dict):
                    token_value = mineru_block.get("api_token")
                    mineru_token = str(token_value).strip() if token_value else None

                    model_version_value = mineru_block.get("model_version")
                    if isinstance(model_version_value, str):
                        candidate = model_version_value.strip().lower()
                        if candidate in {"vlm", "pipeline"}:
                            mineru_model_version = candidate

                    # FastAPI Form(bool) may arrive as bool already; keep conservative parsing.
                    if isinstance(mineru_block.get("enable_formula"), bool):
                        mineru_enable_formula = bool(mineru_block.get("enable_formula"))
                    if isinstance(mineru_block.get("enable_table"), bool):
                        mineru_enable_table = bool(mineru_block.get("enable_table"))
                    if isinstance(mineru_block.get("is_ocr"), bool):
                        mineru_is_ocr = bool(mineru_block.get("is_ocr"))

                    # Sanitize: remove token from DB immediately.
                    sanitized_block = dict(mineru_block)
                    sanitized_block.pop("api_token", None)
                    sanitized_payload = dict(parse_request_payload)
                    sanitized_payload["mineru"] = sanitized_block
                    update_raw_file(
                        session,
                        raw_file,
                        parse_metadata_json=json.dumps(sanitized_payload, ensure_ascii=False),
                    )
                else:
                    mineru_token = None

            # Fallback: allow centralized deployment to provide MinerU token via env.
            if requested_parser_provider == "mineru" and not (mineru_token and mineru_token.strip()):
                env_token = (get_settings().mineru_api_token or "").strip()
                if env_token:
                    mineru_token = env_token

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
                md_key = cs.raw_markdown_key(subject, file_id)
                await cs.write_text(md_key, markdown)

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
            if requested_parser_provider == "mineru":
                parse_plan = ParsePlan(
                    mode="external_mineru",
                    parser_chain=["mineru"],
                    decision_reason="用户在前端选择 MinerU 外部解析引擎。",
                    options=ParserRunOptions(),
                )
            else:
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
            asset_dir = _temp_base / "assets" / str(file_id)
            asset_dir.mkdir(parents=True, exist_ok=True)
            markdown_path = _temp_base / f"{file_id}.md"

            asset_name_prefix = build_asset_name_prefix(
                filename=raw_file.original_filename,
                file_uid=raw_file.uid,
                file_id=file_id,
            )
            parse_plan.options.asset_name_prefix = asset_name_prefix
            storage_backend = raw_file.storage_backend or "local"

        # ── Phase 1: Fast Parse (synchronous) ──

        logger.info(
            "ingest_fast_parse_started",
            subject=subject,
            file_id=file_id,
            filename=raw_file.original_filename,
            parse_mode=parse_plan.mode,
            parser_chain=parse_plan.parser_chain,
        )
        provider_metadata: dict[str, object] | None = None
        # When MinerU is explicitly selected, bypass the local parser chain.
        if requested_parser_provider == "mineru":
            mineru_started_at = time.monotonic()
            with tempfile.TemporaryDirectory(prefix="aiteachme_mineru_") as tmp_dir_str:
                tmp_dir = Path(tmp_dir_str)
                extracted = await asyncio.to_thread(
                    parse_file_to_dir,
                    file_path=file_path,
                    options=MinerURequestOptions(
                        api_token=mineru_token or "",
                        model_version=mineru_model_version,
                        enable_formula=mineru_enable_formula,
                        enable_table=mineru_enable_table,
                        is_ocr=mineru_is_ocr,
                    ),
                    output_dir=tmp_dir,
                )

                mineru_markdown_raw = extracted.markdown_path.read_text(encoding="utf-8", errors="replace")

                # Copy assets into the canonical per-file asset directory.
                # Important: prefix filenames so existing asset listing (prefix filter) keeps working.
                copied_assets = 0
                if extracted.images_dir and extracted.images_dir.exists():
                    for src in sorted(extracted.images_dir.iterdir()):
                        if not src.is_file():
                            continue
                        dest = asset_dir / f"{asset_name_prefix}{src.name}"
                        shutil.copy2(src, dest)
                        copied_assets += 1

                # Canonicalize: rewrite image refs to ../assets/<file_id>/... and normalize markdown.
                from app.workflows.ingest.parsing.canonicalizer import canonicalize_markdown

                canonical_result = canonicalize_markdown(
                    mineru_markdown_raw,
                    asset_dir=asset_dir,
                    asset_link_prefix=f"../assets/{file_id}",
                    asset_name_prefix=asset_name_prefix,
                    asset_gallery_limit=parse_plan.options.asset_gallery_limit,
                )

            mineru_elapsed_s = round(time.monotonic() - mineru_started_at, 2)

            # Build a FastParseResult-compatible payload for the rest of the pipeline.
            # We keep the same shape so downstream metadata/status logic stays unchanged.
            # MinerU 已经输出高质量 markdown（并可按需开启 is_ocr）。
            # 为了保持“选择 MinerU 就不走原有解析/增强链路”的直觉，这里默认不再触发 Phase 2。
            # 如需 LLM Vision OCR 增强，可后续单独提供显式开关。
            needs_enhance = False

            parse_result = _MinerUFastParseResult(
                markdown=canonical_result.markdown,
                parser_used="mineru",
                attempted_parsers=["mineru"],
                parser_elapsed_s={"mineru": mineru_elapsed_s},
                rewritten_image_refs=canonical_result.rewritten_image_refs,
                extracted_data_images=canonical_result.extracted_data_images,
                appended_asset_images=canonical_result.appended_asset_images,
                needs_enhance=needs_enhance,
            )
            provider_metadata = {
                "batch_id": extracted.batch_id,
                "file_name": extracted.file_name,
                "copied_assets": copied_assets,
            }
        else:
            parse_result = await fast_parse_file(
                file_path=file_path,
                asset_dir=asset_dir,
                classification=classification,
                parse_plan=parse_plan,
                asset_link_prefix=f"../assets/{file_id}",
            )

        # Save Phase 1 results — 统一走 ContentStore
        markdown_path.write_text(parse_result.markdown, encoding="utf-8")
        md_key = cs.raw_markdown_key(subject, file_id)
        await cs.write_text(md_key, parse_result.markdown)
        await cs.upload_dir(asset_dir, cs.asset_prefix(subject, file_id))
        md_storage_key = md_key
        asset_storage_dir = cs.asset_prefix(subject, file_id).rstrip("/")
        asset_rows = _build_asset_rows(
            raw_file_id=file_id,
            asset_dir=asset_dir,
            asset_storage_dir=asset_storage_dir,
            storage_backend=storage_backend,
        )
        parse_metadata = {
            "provider_used": parse_result.parser_used,
            "provider_status": "fast_parsed",
            "parser_used": parse_result.parser_used,
            "parse_mode": parse_plan.mode,
            "decision_reason": parse_plan.decision_reason,
            "parser_chain": ["mineru"] if parse_result.parser_used == "mineru" else parse_plan.parser_chain,
            "attempted_parsers": parse_result.attempted_parsers,
            "parser_elapsed_s": parse_result.parser_elapsed_s,
            "requested_features": [],
            "applied_features": [],
            "skipped_features": [],
            "failed_feature": None,
            "provider_failure_reason": None,
            "requested_parser_provider": requested_parser_provider,
            "mineru": {
                "model_version": mineru_model_version,
                "enable_formula": mineru_enable_formula,
                "enable_table": mineru_enable_table,
                "is_ocr": mineru_is_ocr,
            }
            if requested_parser_provider == "mineru"
            else None,
            "provider_metadata": provider_metadata,
            "rewritten_image_refs": parse_result.rewritten_image_refs,
            "extracted_data_images": parse_result.extracted_data_images,
            "appended_asset_images": parse_result.appended_asset_images,
            "asset_ocr_images": 0,
            "asset_ocr_replacements": 0,
            "needs_enhance": parse_result.needs_enhance,
            "raw_markdown_storage_key": md_storage_key,
            "asset_storage_dir": asset_storage_dir,
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
            # RISK-2 fix: track task reference to prevent GC collection
            task = asyncio.create_task(
                _run_deep_enhance_background(
                    subject=subject,
                    file_id=file_id,
                    event_bus=event_bus,
                )
            )
            _background_tasks.add(task)
            task.add_done_callback(_background_tasks.discard)

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
                    # Best-effort: ensure we don't accidentally persist MinerU token on failure.
                    try:
                        payload = json.loads(raw_file.parse_metadata_json or "{}")
                        if isinstance(payload, dict) and isinstance(payload.get("mineru"), dict):
                            sanitized_block = dict(payload["mineru"])
                            sanitized_block.pop("api_token", None)
                            payload["mineru"] = sanitized_block
                            update_raw_file(
                                session,
                                raw_file,
                                parse_metadata_json=json.dumps(payload, ensure_ascii=False),
                            )
                    except Exception:
                        pass
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
