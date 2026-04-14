"""Main ingest parse workflow entry point (Phase 1 + Phase 2 dispatch)."""

from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
import time
from pathlib import Path

import structlog

from app.shared.infra.config import get_settings
from app.shared.infra.database import managed_session
from app.shared.infra.env_support import get_env
from app.shared.infra.storage import get_content_store
from app.models import IngestStatus, TaskStatus
from app.repositories.files_repo import get_raw_file_by_id, replace_raw_file_assets, update_raw_file
from app.utils.path_helpers import build_asset_name_prefix
from app.shared.infra.workflow.result import WorkflowResult, err_result, ok_result
from app.workflows.ingest.parsing.classifier import classify_file
from app.workflows.ingest.parsing.formats import (
    categorize_text_extension,
    get_text_language_hint,
    is_text_extension,
)
from app.workflows.ingest.parsing.orchestrator import fast_parse_file
from app.workflows.ingest.parsing.strategy import ParsePlan, build_parse_plan
from app.workflows.ingest.parsing.types import ParserRunOptions
from app.workflows.ingest.parsing.mineru_cloud import MinerURequestOptions, parse_file_to_dir
from app.workflows.ingest.state import IngestParseState

from ._helpers import (
    _MinerUFastParseResult,
    _background_tasks,
    _build_asset_rows,
    _compute_quality_score,
)
from .enhance import _run_deep_enhance_background

logger = structlog.get_logger()


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
        mineru_token_source: str = "not_requested"
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
            # 前端 settings 属于"本地配置"，后端后台 ingest 无法直接读取。
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
                    if mineru_token:
                        mineru_token_source = "request"

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
                env_token = (get_env("MINERU_API_TOKEN") or "").strip()
                if env_token:
                    mineru_token = env_token
                    mineru_token_source = "server_env"
                else:
                    mineru_token_source = "missing"

            if requested_parser_provider == "mineru":
                logger.info(
                    "mineru_request_config_resolved",
                    subject=subject,
                    file_id=file_id,
                    token_source=mineru_token_source,
                    model_version=mineru_model_version,
                    enable_formula=mineru_enable_formula,
                    enable_table=mineru_enable_table,
                    is_ocr=mineru_is_ocr,
                )

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
            logger.info(
                "mineru_parse_started",
                subject=subject,
                file_id=file_id,
                token_source=mineru_token_source,
                model_version=mineru_model_version,
                enable_formula=mineru_enable_formula,
                enable_table=mineru_enable_table,
                is_ocr=mineru_is_ocr,
            )
            try:
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
            except Exception:
                logger.exception(
                    "mineru_parse_failed",
                    subject=subject,
                    file_id=file_id,
                    token_source=mineru_token_source,
                    model_version=mineru_model_version,
                )
                raise

            mineru_elapsed_s = round(time.monotonic() - mineru_started_at, 2)
            logger.info(
                "mineru_parse_completed",
                subject=subject,
                file_id=file_id,
                token_source=mineru_token_source,
                batch_id=extracted.batch_id,
                copied_assets=copied_assets,
                elapsed_s=mineru_elapsed_s,
            )

            # Build a FastParseResult-compatible payload for the rest of the pipeline.
            # We keep the same shape so downstream metadata/status logic stays unchanged.
            # MinerU 已经输出高质量 markdown（并可按需开启 is_ocr）。
            # 为了保持"选择 MinerU 就不走原有解析/增强链路"的直觉，这里默认不再触发 Phase 2。
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
                "token_source": mineru_token_source,
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
                "token_source": mineru_token_source,
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
