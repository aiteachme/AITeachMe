"""Parse-phase node for ingest workflows (Phase 1 fast parse).

这个节点统一承接四类 Phase 1 主线：
1. 文本类文件 UTF-8 快通道
2. MinerU 显式外部解析分支
3. PaddleOCR 显式外部解析分支
4. 本地 parser chain 常规解析分支
"""

from __future__ import annotations

import asyncio
import json
import shutil
import time
from pathlib import Path

from app.shared.infra.workflow.context import WorkflowContext
from app.shared.infra.env_support import get_env, get_env_bounded_float, get_env_bounded_int
from app.workflows.ingest.parsing.lib.defaults import (
    DEFAULT_EXTERNAL_PARSE_TIMEOUT_S,
    DEFAULT_PADDLE_OCR_PARSE_TIMEOUT_S,
)
from app.utils.path_helpers import list_asset_files
from app.workflows.ingest.parsing.canonicalizer import canonicalize_markdown
from app.workflows.ingest.parsing.mineru_cloud import MinerURequestOptions
from app.workflows.ingest.parsing.mineru_cloud_parallel import (
    parse_file_to_dir_parallel as parse_file_to_dir_with_mineru,
)
from app.workflows.ingest.parsing.paddle_ocr_cloud import (
    DEFAULT_PADDLE_OCR_MODEL,
    PaddleOCRRequestOptions,
    parse_file_to_dir as parse_file_to_dir_with_paddle_ocr,
)
from app.workflows.ingest.parsing.paddle_ocr_parallel import (
    DEFAULT_PADDLE_OCR_CHUNK_CONCURRENCY,
    DEFAULT_PADDLE_OCR_MAX_PAGES_PER_CHUNK,
    parse_file_to_dir_parallel as parse_file_to_dir_with_paddle_ocr_parallel,
)
from app.workflows.ingest.parsing.orchestrator import fast_parse_file
from app.workflows.ingest.parsing.lib.formats import is_image_extension
from app.workflows.ingest.parsing.lib.provider_contracts import ExternalProviderTimeoutError
from app.workflows.ingest.parsing.strategy import ParsePlan, build_parse_plan
from app.workflows.ingest.parsing.lib.common import workflow_logger
from app.workflows.ingest.parsing.lib.runtime_helpers import (
    _ExternalFastParseResult,
    _compute_quality_score,
)
from app.workflows.ingest.parsing.state import IngestParseState


def _classification_for_quality_score(state: IngestParseState) -> dict[str, object]:
    classification_payload = state.get("classification_payload")
    if classification_payload:
        try:
            decoded = json.loads(classification_payload)
        except Exception:
            decoded = {}
        if isinstance(decoded, dict):
            return decoded
    classification = state.get("classification")
    if classification is not None:
        return classification.to_dict()
    return {}


def _build_parse_metadata(
    *,
    state: IngestParseState,
    parser_used: str,
    attempted_parsers: list[str],
    parser_elapsed_s: dict[str, float],
    rewritten_image_refs: int,
    extracted_data_images: int,
    appended_asset_images: int,
    needs_enhance: bool,
    needs_quality_reparse: bool,
    needs_asset_ocr: bool,
    effective_parse_plan: ParsePlan | None = None,
    provider_metadata: dict[str, object] | None = None,
    fast_path: bool = False,
) -> str:
    parse_plan = effective_parse_plan or state.get("parse_plan")
    parse_decision = state.get("parse_decision")
    payload = {
        "provider_used": parser_used,
        "provider_status": "fast_parsed",
        "parser_used": parser_used,
        "parse_mode": (
            parse_plan.mode
            if parse_plan is not None
            else f"native_{state.get('text_category') or 'text'}"
        ),
        "decision_reason": (
            parse_plan.decision_reason
            if parse_plan is not None
            else "文本文件走 UTF-8 快速通道，不进入常规分类/计划链路。"
        ),
        "parser_chain": (
            ["mineru"]
            if parser_used == "mineru"
            else ["paddle_ocr"]
            if parser_used == "paddle_ocr"
            else parse_plan.parser_chain
            if parse_plan is not None
            else attempted_parsers
        ),
        "attempted_parsers": attempted_parsers,
        "parser_elapsed_s": parser_elapsed_s,
        "requested_features": [],
        "applied_features": [],
        "skipped_features": [],
        "failed_feature": None,
        "provider_failure_reason": None,
        "requested_parser_provider": state.get("requested_parser_provider"),
        "parse_decision": parse_decision.model_dump(mode="json") if parse_decision else None,
        "mineru": {
            "token_source": state.get("mineru_token_source"),
            "model_version": state.get("mineru_model_version"),
            "enable_formula": state.get("mineru_enable_formula"),
            "enable_table": state.get("mineru_enable_table"),
            "is_ocr": state.get("mineru_is_ocr"),
        }
        if state.get("mineru_token") or parser_used == "mineru"
        else None,
        "paddle_ocr": {
            "token_source": state.get("paddle_ocr_token_source"),
        }
        if state.get("paddle_ocr_token") or parser_used == "paddle_ocr"
        else None,
        "ocr": {
            "base_url_source": "OCR_BASE_URL" if state.get("requested_parser_provider") == "ocr" else None,
        }
        if state.get("requested_parser_provider") == "ocr"
        else None,
        "provider_metadata": provider_metadata,
        "rewritten_image_refs": rewritten_image_refs,
        "extracted_data_images": extracted_data_images,
        "appended_asset_images": appended_asset_images,
        "asset_ocr_images": 0,
        "asset_ocr_replacements": 0,
        "needs_enhance": needs_enhance,
        "needs_quality_reparse": needs_quality_reparse,
        "needs_asset_ocr": needs_asset_ocr,
        "raw_markdown_storage_key": state.get("record_markdown_path"),
        "asset_storage_dir": state.get("asset_storage_dir"),
        "fast_path": fast_path,
        "text_category": state.get("text_category") if fast_path else None,
        "lang_hint": state.get("text_language_hint") if fast_path else None,
    }
    return json.dumps(payload, ensure_ascii=False)


def _copy_external_assets(
    *,
    source_dir: Path | None,
    dest_dir: Path,
    asset_name_prefix: str,
) -> int:
    if source_dir is None or not source_dir.exists():
        return 0

    copied_assets = 0
    used_names: set[str] = set()
    for src in sorted(path for path in source_dir.rglob("*") if path.is_file()):
        target_name = f"{asset_name_prefix}{src.name}"
        if target_name in used_names or (dest_dir / target_name).exists():
            stem = Path(src.name).stem
            suffix = Path(src.name).suffix
            target_name = f"{asset_name_prefix}{stem}_{copied_assets + 1}{suffix}"
        shutil.copy2(src, dest_dir / target_name)
        used_names.add(target_name)
        copied_assets += 1
    return copied_assets


def _paddle_ocr_parse_timeout_s() -> float:
    return get_env_bounded_float(
        "PADDLE_OCR_PARSE_TIMEOUT_S",
        float(DEFAULT_PADDLE_OCR_PARSE_TIMEOUT_S),
        min_value=15.0,
        max_value=600.0,
    )


def _paddle_ocr_model() -> str:
    return (get_env("PADDLE_OCR_MODEL") or "").strip() or DEFAULT_PADDLE_OCR_MODEL


def _paddle_ocr_parse_mode() -> str:
    raw_mode = (get_env("PADDLE_OCR_PARSE_MODE") or "").strip().lower()
    if raw_mode in {"parallel", "split", "chunked", "async"}:
        return "parallel"
    return "single"


def _paddle_ocr_chunk_max_pages() -> int:
    return get_env_bounded_int(
        "PADDLE_OCR_CHUNK_MAX_PAGES",
        DEFAULT_PADDLE_OCR_MAX_PAGES_PER_CHUNK,
        min_value=1,
        max_value=100,
    )


def _paddle_ocr_chunk_concurrency() -> int:
    return get_env_bounded_int(
        "PADDLE_OCR_CHUNK_CONCURRENCY",
        DEFAULT_PADDLE_OCR_CHUNK_CONCURRENCY,
        min_value=1,
        max_value=16,
    )


async def _run_mineru_external_parse(
    *,
    state: IngestParseState,
    local_asset_dir: Path,
    parse_plan: ParsePlan | None,
) -> tuple[_ExternalFastParseResult, dict[str, object]]:
    started_at = time.monotonic()
    extracted = await asyncio.to_thread(
        parse_file_to_dir_with_mineru,
        file_path=Path(state["file_path"]),
        options=MinerURequestOptions(
            api_token=state.get("mineru_token") or "",
            model_version=state.get("mineru_model_version") or "vlm",
            enable_formula=bool(state.get("mineru_enable_formula", True)),
            enable_table=bool(state.get("mineru_enable_table", True)),
            is_ocr=bool(state.get("mineru_is_ocr", False)),
        ),
        output_dir=Path(state["temp_dir"]) / "mineru_output",
        total_timeout_s=DEFAULT_EXTERNAL_PARSE_TIMEOUT_S,
    )

    mineru_markdown_raw = extracted.markdown_path.read_text(encoding="utf-8", errors="replace")
    copied_assets = _copy_external_assets(
        source_dir=extracted.images_dir,
        dest_dir=local_asset_dir,
        asset_name_prefix=state["asset_name_prefix"],
    )

    canonical_result = canonicalize_markdown(
        mineru_markdown_raw,
        asset_dir=local_asset_dir,
        asset_link_prefix=state["asset_link_prefix"],
        asset_name_prefix=state["asset_name_prefix"],
        asset_gallery_limit=parse_plan.options.asset_gallery_limit if parse_plan else 12,
    )
    elapsed = round(time.monotonic() - started_at, 2)
    batch_ids = list(extracted.batch_ids or (extracted.batch_id,))
    provider_metadata: dict[str, object] = {
        "batch_id": extracted.batch_id,
        "batch_ids": batch_ids,
        "batch_count": len(batch_ids),
        "file_name": extracted.file_name,
        "copied_assets": copied_assets,
        "token_source": state.get("mineru_token_source"),
        "timeout_budget_s": DEFAULT_EXTERNAL_PARSE_TIMEOUT_S,
        "strategy": "single",
    }
    provider_metadata.update(extracted.metadata)
    return (
        _ExternalFastParseResult(
            markdown=canonical_result.markdown,
            parser_used="mineru",
            attempted_parsers=["mineru"],
            parser_elapsed_s={"mineru": elapsed},
            rewritten_image_refs=canonical_result.rewritten_image_refs,
            extracted_data_images=canonical_result.extracted_data_images,
            appended_asset_images=canonical_result.appended_asset_images,
            needs_enhance=False,
        ),
        provider_metadata,
    )


async def _run_paddle_ocr_external_parse(
    *,
    state: IngestParseState,
    local_asset_dir: Path,
    parse_plan: ParsePlan | None,
) -> tuple[_ExternalFastParseResult, dict[str, object]]:
    started_at = time.monotonic()
    timeout_budget_s = _paddle_ocr_parse_timeout_s()
    model = _paddle_ocr_model()
    parse_mode = _paddle_ocr_parse_mode()
    output_dir = Path(state["temp_dir"]) / f"paddle_ocr_{parse_mode}_output"
    request_options = PaddleOCRRequestOptions(
        api_token=state.get("paddle_ocr_token") or "",
        model=model,
    )
    if parse_mode == "parallel":
        chunk_max_pages = _paddle_ocr_chunk_max_pages()
        chunk_concurrency = _paddle_ocr_chunk_concurrency()
        extracted = await asyncio.to_thread(
            parse_file_to_dir_with_paddle_ocr_parallel,
            file_path=Path(state["file_path"]),
            options=request_options,
            output_dir=output_dir,
            total_timeout_s=timeout_budget_s,
            max_pages_per_chunk=chunk_max_pages,
            max_concurrent_jobs=chunk_concurrency,
        )
    else:
        chunk_max_pages = None
        chunk_concurrency = None
        extracted = await asyncio.to_thread(
            parse_file_to_dir_with_paddle_ocr,
            file_path=Path(state["file_path"]),
            options=request_options,
            output_dir=output_dir,
            total_timeout_s=timeout_budget_s,
        )

    paddle_ocr_markdown_raw = extracted.markdown_path.read_text(encoding="utf-8", errors="replace")
    copied_assets = _copy_external_assets(
        source_dir=extracted.images_dir,
        dest_dir=local_asset_dir,
        asset_name_prefix=state["asset_name_prefix"],
    )

    canonical_result = canonicalize_markdown(
        paddle_ocr_markdown_raw,
        asset_dir=local_asset_dir,
        asset_link_prefix=state["asset_link_prefix"],
        asset_name_prefix=state["asset_name_prefix"],
        asset_gallery_limit=parse_plan.options.asset_gallery_limit if parse_plan else 12,
    )
    elapsed = round(time.monotonic() - started_at, 2)
    extracted_metadata = getattr(extracted, "metadata", {}) or {}
    job_ids = tuple(getattr(extracted, "job_ids", ()) or ())
    provider_metadata: dict[str, object] = {
        "job_id": extracted.job_id,
        "model": extracted.model,
        "strategy": parse_mode,
        "copied_assets": copied_assets,
        "token_source": state.get("paddle_ocr_token_source"),
        "timeout_budget_s": timeout_budget_s,
    }
    if job_ids:
        provider_metadata["job_ids"] = list(job_ids)
    if chunk_max_pages is not None:
        provider_metadata["chunk_max_pages"] = chunk_max_pages
    if chunk_concurrency is not None:
        provider_metadata["chunk_concurrency"] = chunk_concurrency
    if isinstance(extracted_metadata, dict):
        provider_metadata.update(extracted_metadata)
    return (
        _ExternalFastParseResult(
            markdown=canonical_result.markdown,
            parser_used="paddle_ocr",
            attempted_parsers=["paddle_ocr"],
            parser_elapsed_s={"paddle_ocr": elapsed},
            rewritten_image_refs=canonical_result.rewritten_image_refs,
            extracted_data_images=canonical_result.extracted_data_images,
            appended_asset_images=canonical_result.appended_asset_images,
            needs_enhance=False,
        ),
        provider_metadata,
    )


def build_parse_file_node(*, context: WorkflowContext):
    """Phase 1 fast parse node — text fast path, external providers, or local parser chain."""

    async def parse_file_node(state: IngestParseState) -> IngestParseState:
        logger = workflow_logger(context, state)
        local_markdown_path = Path(state["local_markdown_path"])
        local_asset_dir = Path(state["local_asset_dir"])
        local_markdown_path.parent.mkdir(parents=True, exist_ok=True)
        local_asset_dir.mkdir(parents=True, exist_ok=True)

        started_at = time.monotonic()
        parse_plan = state.get("parse_plan")
        parse_decision = state.get("parse_decision")
        effective_parse_plan = parse_plan
        logger.info(
            "ingest_fast_parse_started",
            local_markdown_path=str(local_markdown_path),
            local_asset_dir=str(local_asset_dir),
            parse_mode=parse_plan.mode if parse_plan else None,
            parser_chain=parse_plan.parser_chain if parse_plan else None,
            text_fast_path=state.get("is_text_fast_path", False),
            primary_provider=parse_decision.primary_provider if parse_decision else None,
        )
        try:
            provider_metadata: dict[str, object] | None = None

            if state.get("is_text_fast_path"):
                raw_text = Path(state["file_path"]).read_text(encoding="utf-8", errors="replace")
                if state.get("text_category") == "structured_text" and state.get("text_language_hint"):
                    markdown = f"```{state['text_language_hint']}\n{raw_text}\n```"
                else:
                    markdown = raw_text
                local_markdown_path.write_text(markdown, encoding="utf-8")
                elapsed = round(time.monotonic() - started_at, 2)
                parse_metadata = _build_parse_metadata(
                    state=state,
                    parser_used="text_native",
                    attempted_parsers=["text_native"],
                    parser_elapsed_s={"text_native": elapsed},
                    rewritten_image_refs=0,
                    extracted_data_images=0,
                    appended_asset_images=0,
                    needs_enhance=False,
                    needs_quality_reparse=False,
                    needs_asset_ocr=False,
                    fast_path=True,
                )
                quality_score = _compute_quality_score(
                    markdown=markdown,
                    image_count=0,
                    classification={},
                )
                logger.info(
                    "ingest_fast_path_text_completed",
                    text_category=state.get("text_category"),
                    lang_hint=state.get("text_language_hint"),
                    chars=len(markdown),
                    elapsed_s=elapsed,
                )
                return {
                    **state,
                    "parse_metadata": parse_metadata,
                    "parsed_markdown": markdown,
                    "parser_used": "text_native",
                    "attempted_parsers": ["text_native"],
                    "parser_elapsed_s": {"text_native": elapsed},
                    "markdown_chars": len(markdown),
                    "image_count": 0,
                    "rewritten_image_refs": 0,
                    "extracted_data_images": 0,
                    "appended_asset_images": 0,
                    "quality_score": quality_score,
                    "needs_enhance": False,
                    "needs_quality_reparse": False,
                    "needs_asset_ocr": False,
                    "error": None,
                }

            if parse_decision and (parse_decision.uses_mineru or parse_decision.uses_paddle_ocr):
                is_external_only_image = is_image_extension(state["filetype"])
                provider_failures: dict[str, str] = {}
                attempted_external_parsers: list[str] = []
                external_elapsed_s: dict[str, float] = {}
                provider_order: list[str] = []
                for provider_name in [parse_decision.primary_provider, *parse_decision.fallback_chain]:
                    if provider_name in {"mineru", "paddle_ocr"} and provider_name not in provider_order:
                        provider_order.append(provider_name)

                parse_result = None
                timeout_triggered_provider: str | None = None
                for provider_name in provider_order:
                    provider_started_at = time.monotonic()
                    timeout_budget_s = (
                        _paddle_ocr_parse_timeout_s()
                        if provider_name == "paddle_ocr"
                        else DEFAULT_EXTERNAL_PARSE_TIMEOUT_S
                    )
                    try:
                        if provider_name == "mineru":
                            external_result, current_provider_metadata = await _run_mineru_external_parse(
                                state=state,
                                local_asset_dir=local_asset_dir,
                                parse_plan=parse_plan,
                            )
                        else:
                            external_result, current_provider_metadata = await _run_paddle_ocr_external_parse(
                                state=state,
                                local_asset_dir=local_asset_dir,
                                parse_plan=parse_plan,
                            )
                        parse_result = _ExternalFastParseResult(
                            markdown=external_result.markdown,
                            parser_used=external_result.parser_used,
                            attempted_parsers=[*attempted_external_parsers, *external_result.attempted_parsers],
                            parser_elapsed_s={**external_elapsed_s, **external_result.parser_elapsed_s},
                            rewritten_image_refs=external_result.rewritten_image_refs,
                            extracted_data_images=external_result.extracted_data_images,
                            appended_asset_images=external_result.appended_asset_images,
                            needs_enhance=external_result.needs_enhance,
                            needs_quality_reparse=external_result.needs_quality_reparse,
                            needs_asset_ocr=external_result.needs_asset_ocr,
                        )
                        if provider_name != parse_decision.primary_provider:
                            effective_parse_plan = ParsePlan(
                                mode=f"external_{provider_name}",
                                parser_chain=[provider_name],
                                decision_reason=parse_decision.primary_reason,
                            )
                        provider_metadata = current_provider_metadata
                        if provider_failures:
                            provider_metadata = {
                                **provider_metadata,
                                "provider_failures": provider_failures,
                            }
                        break
                    except ExternalProviderTimeoutError as exc:
                        attempted_external_parsers.append(provider_name)
                        provider_failures[provider_name] = str(exc)
                        timeout_triggered_provider = provider_name
                        external_elapsed_s[provider_name] = round(time.monotonic() - provider_started_at, 2)
                        logger.warning(
                            "ingest_external_provider_attempt_timed_out",
                            provider=provider_name,
                            timeout_budget_s=timeout_budget_s,
                            error=str(exc),
                        )
                        if not is_external_only_image:
                            break
                    except Exception as exc:
                        attempted_external_parsers.append(provider_name)
                        provider_failures[provider_name] = str(exc)
                        logger.warning(
                            "ingest_external_provider_attempt_failed",
                            provider=provider_name,
                            error=str(exc),
                        )
                        if provider_name == "mineru":
                            external_elapsed_s["mineru"] = round(time.monotonic() - provider_started_at, 2)
                        else:
                            external_elapsed_s["paddle_ocr"] = round(time.monotonic() - provider_started_at, 2)

                if parse_result is None:
                    if is_external_only_image:
                        return {
                            **state,
                            "error": (
                                "image_external_parser_unavailable: 当前无法处理图片上传，"
                                "请配置 PaddleOCR 或 MinerU 后重试。"
                            ),
                        }
                    effective_parse_plan = build_parse_plan(
                        file_path=state["file_path"],
                        filetype=state["filetype"],
                        file_size_bytes=state.get("file_size_bytes"),
                        classification=state.get("classification"),
                    )
                    local_parse_result = await fast_parse_file(
                        file_path=state["file_path"],
                        asset_dir=local_asset_dir,
                        classification=state.get("classification"),
                        parse_plan=effective_parse_plan,
                        asset_link_prefix=state["asset_link_prefix"],
                    )
                    parse_result = _ExternalFastParseResult(
                        markdown=local_parse_result.markdown,
                        parser_used=local_parse_result.parser_used,
                        attempted_parsers=[*attempted_external_parsers, *local_parse_result.attempted_parsers],
                        parser_elapsed_s={**external_elapsed_s, **local_parse_result.parser_elapsed_s},
                        rewritten_image_refs=local_parse_result.rewritten_image_refs,
                        extracted_data_images=local_parse_result.extracted_data_images,
                        appended_asset_images=local_parse_result.appended_asset_images,
                        needs_enhance=local_parse_result.needs_enhance,
                        needs_quality_reparse=local_parse_result.needs_quality_reparse,
                        needs_asset_ocr=local_parse_result.needs_asset_ocr,
                    )
                    provider_metadata = {
                        "provider_failures": provider_failures,
                        "fallback_to": "local",
                        "timeout_provider": timeout_triggered_provider,
                        "timeout_budget_s": (
                            _paddle_ocr_parse_timeout_s()
                            if timeout_triggered_provider == "paddle_ocr"
                            else DEFAULT_EXTERNAL_PARSE_TIMEOUT_S
                        ),
                    }
                    logger.info(
                        "ingest_external_provider_fell_back_to_local",
                        attempted_providers=attempted_external_parsers,
                        local_parser=local_parse_result.parser_used,
                        timeout_provider=timeout_triggered_provider,
                    )
            else:
                parse_result = await fast_parse_file(
                    file_path=state["file_path"],
                    asset_dir=local_asset_dir,
                    classification=state.get("classification"),
                    parse_plan=parse_plan,
                    asset_link_prefix=state["asset_link_prefix"],
                )

            local_markdown_path.write_text(parse_result.markdown, encoding="utf-8")
            image_count = len(
                list_asset_files(
                    local_asset_dir,
                    asset_name_prefix=state.get("asset_name_prefix"),
                )
            )
            quality_score = _compute_quality_score(
                markdown=parse_result.markdown,
                image_count=image_count,
                classification=_classification_for_quality_score(state),
            )
            parse_metadata = _build_parse_metadata(
                state=state,
                parser_used=parse_result.parser_used,
                attempted_parsers=parse_result.attempted_parsers,
                parser_elapsed_s=parse_result.parser_elapsed_s,
                rewritten_image_refs=parse_result.rewritten_image_refs,
                extracted_data_images=parse_result.extracted_data_images,
                appended_asset_images=parse_result.appended_asset_images,
                needs_enhance=parse_result.needs_enhance,
                needs_quality_reparse=getattr(parse_result, "needs_quality_reparse", False),
                needs_asset_ocr=getattr(parse_result, "needs_asset_ocr", False),
                effective_parse_plan=effective_parse_plan,
                provider_metadata=provider_metadata,
            )
            logger.info(
                "ingest_fast_parse_completed",
                parse_mode=effective_parse_plan.mode if effective_parse_plan else None,
                parser_used=parse_result.parser_used,
                attempted_parsers=parse_result.attempted_parsers,
                markdown_chars=len(parse_result.markdown),
                image_count=image_count,
                elapsed_s=round(time.monotonic() - started_at, 2),
                needs_enhance=parse_result.needs_enhance,
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
                "quality_score": quality_score,
                "needs_enhance": parse_result.needs_enhance,
                "needs_quality_reparse": getattr(parse_result, "needs_quality_reparse", False),
                "needs_asset_ocr": getattr(parse_result, "needs_asset_ocr", False),
                "error": None,
            }
        except Exception as exc:
            logger.error(
                "ingest_fast_parse_failed",
                error=str(exc),
                elapsed_s=round(time.monotonic() - started_at, 2),
                exc_info=True,
            )
            return {
                **state,
                "error": f"fast_parse_file_failed: {exc}",
            }

    return parse_file_node
