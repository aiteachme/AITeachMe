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
from app.utils.path_helpers import list_asset_files
from app.workflows.ingest.common.parsing.canonicalizer import canonicalize_markdown
from app.workflows.ingest.common.parsing.mineru_cloud import MinerURequestOptions, parse_file_to_dir
from app.workflows.ingest.common.parsing.paddle_ocr_cloud import (
    PaddleOCRRequestOptions,
    parse_file_to_dir as parse_file_to_dir_with_paddle_ocr,
)
from app.workflows.ingest.common.parsing.orchestrator import fast_parse_file
from app.workflows.ingest.fast_parse.lib.common import workflow_logger
from app.workflows.ingest.fast_parse.lib.runtime_helpers import (
    _ExternalFastParseResult,
    _compute_quality_score,
)
from app.workflows.ingest.fast_parse.state import IngestParseState


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
    provider_metadata: dict[str, object] | None = None,
    fast_path: bool = False,
) -> str:
    parse_plan = state.get("parse_plan")
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
        if state.get("requested_parser_provider") == "mineru"
        else None,
        "paddle_ocr": {
            "token_source": state.get("paddle_ocr_token_source"),
        }
        if state.get("requested_parser_provider") == "paddle_ocr"
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

            if parse_decision and parse_decision.uses_mineru:
                extracted = await asyncio.to_thread(
                    parse_file_to_dir,
                    file_path=Path(state["file_path"]),
                    options=MinerURequestOptions(
                        api_token=state.get("mineru_token") or "",
                        model_version=state.get("mineru_model_version") or "vlm",
                        enable_formula=bool(state.get("mineru_enable_formula", True)),
                        enable_table=bool(state.get("mineru_enable_table", True)),
                        is_ocr=bool(state.get("mineru_is_ocr", False)),
                    ),
                    output_dir=Path(state["temp_dir"]) / "mineru_output",
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
                    asset_link_prefix=f"../assets/{state['file_id']}",
                    asset_name_prefix=state["asset_name_prefix"],
                    asset_gallery_limit=parse_plan.options.asset_gallery_limit if parse_plan else 12,
                )
                elapsed = round(time.monotonic() - started_at, 2)
                parse_result = _ExternalFastParseResult(
                    markdown=canonical_result.markdown,
                    parser_used="mineru",
                    attempted_parsers=["mineru"],
                    parser_elapsed_s={"mineru": elapsed},
                    rewritten_image_refs=canonical_result.rewritten_image_refs,
                    extracted_data_images=canonical_result.extracted_data_images,
                    appended_asset_images=canonical_result.appended_asset_images,
                    needs_enhance=False,
                )
                provider_metadata = {
                    "batch_id": extracted.batch_id,
                    "file_name": extracted.file_name,
                    "copied_assets": copied_assets,
                    "token_source": state.get("mineru_token_source"),
                }
            elif parse_decision and parse_decision.uses_paddle_ocr:
                extracted = await asyncio.to_thread(
                    parse_file_to_dir_with_paddle_ocr,
                    file_path=Path(state["file_path"]),
                    options=PaddleOCRRequestOptions(
                        api_token=state.get("paddle_ocr_token") or "",
                    ),
                    output_dir=Path(state["temp_dir"]) / "paddle_ocr_output",
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
                    asset_link_prefix=f"../assets/{state['file_id']}",
                    asset_name_prefix=state["asset_name_prefix"],
                    asset_gallery_limit=parse_plan.options.asset_gallery_limit if parse_plan else 12,
                )
                elapsed = round(time.monotonic() - started_at, 2)
                parse_result = _ExternalFastParseResult(
                    markdown=canonical_result.markdown,
                    parser_used="paddle_ocr",
                    attempted_parsers=["paddle_ocr"],
                    parser_elapsed_s={"paddle_ocr": elapsed},
                    rewritten_image_refs=canonical_result.rewritten_image_refs,
                    extracted_data_images=canonical_result.extracted_data_images,
                    appended_asset_images=canonical_result.appended_asset_images,
                    needs_enhance=False,
                )
                provider_metadata = {
                    "job_id": extracted.job_id,
                    "model": extracted.model,
                    "copied_assets": copied_assets,
                    "token_source": state.get("paddle_ocr_token_source"),
                }
            else:
                parse_result = await fast_parse_file(
                    file_path=state["file_path"],
                    asset_dir=local_asset_dir,
                    classification=state.get("classification"),
                    parse_plan=parse_plan,
                    asset_link_prefix=f"../assets/{state['file_id']}",
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
                provider_metadata=provider_metadata,
            )
            logger.info(
                "ingest_fast_parse_completed",
                parse_mode=parse_plan.mode if parse_plan else None,
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
