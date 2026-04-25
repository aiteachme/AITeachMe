"""Load, fingerprint, classify, and plan nodes for ingest workflows.

这一层负责把 ``RawFile`` 和上传请求元信息装配成标准化 parse state。
它只准备本次解析运行所需的上下文，不负责真正的解析执行和最终持久化。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import posixpath
import secrets
import tempfile
from pathlib import Path

from app.shared.infra.database import managed_session
from app.shared.infra.env_support import get_env_list
from app.shared.infra.storage import get_content_store
from app.models import IngestStatus
from app.repositories.files_repo import get_raw_file_by_id, update_raw_file
from app.shared.infra.workflow.context import WorkflowContext
from app.utils.path_helpers import build_asset_name_prefix
from app.workflows.ingest.common.parsing.classifier import classify_file
from app.workflows.ingest.common.parsing.defaults import (
    DEFAULT_MINERU_ENABLE_FORMULA,
    DEFAULT_MINERU_ENABLE_TABLE,
    DEFAULT_MINERU_IS_OCR,
    DEFAULT_MINERU_MODEL_VERSION,
)
from app.workflows.ingest.common.parsing.decision import build_parse_decision
from app.workflows.ingest.common.parsing.formats import (
    categorize_text_extension,
    get_text_language_hint,
    is_text_extension,
)
from app.workflows.ingest.common.parsing.parsers import (
    is_markitdown_available_for_extension,
    resolve_markitdown_parser_name,
)
from app.workflows.ingest.common.parsing.strategy import ParsePlan, build_parse_plan
from app.workflows.ingest.common.parsing.types import ParserRunOptions
from app.workflows.ingest.fast_parse.lib.common import workflow_logger
from app.workflows.ingest.fast_parse.state import IngestParseState


def _decode_json_object(raw: str | None) -> dict[str, object]:
    try:
        decoded = json.loads(raw or "{}")
    except Exception:
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _relative_asset_link_prefix(*, markdown_key: str, asset_dir: str) -> str:
    markdown_parent = posixpath.dirname(markdown_key.rstrip("/")) or "."
    relative = posixpath.relpath(asset_dir.rstrip("/"), markdown_parent)
    return "." if relative == "." else relative


def _coerce_optional_bool(value: object, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default


def _resolve_parse_request(
    *,
    raw_payload: dict[str, object],
) -> tuple[dict[str, object], str | None, str | None, str, bool, bool, bool]:
    requested_parser_provider = raw_payload.get("requested_parser_provider")
    if isinstance(requested_parser_provider, str):
        requested_parser_provider = requested_parser_provider.strip().lower() or None
    else:
        requested_parser_provider = None

    mineru_token: str | None = None
    mineru_model_version = DEFAULT_MINERU_MODEL_VERSION
    mineru_enable_formula = DEFAULT_MINERU_ENABLE_FORMULA
    mineru_enable_table = DEFAULT_MINERU_ENABLE_TABLE
    mineru_is_ocr = DEFAULT_MINERU_IS_OCR

    sanitized_payload = dict(raw_payload)
    mineru_block = sanitized_payload.get("mineru")
    if requested_parser_provider == "mineru" and isinstance(mineru_block, dict):
        token_value = mineru_block.get("api_token")
        mineru_token = str(token_value).strip() if token_value else None

        model_version = mineru_block.get("model_version")
        if isinstance(model_version, str):
            candidate = model_version.strip().lower()
            if candidate in {"vlm", "pipeline"}:
                mineru_model_version = candidate

        mineru_enable_formula = _coerce_optional_bool(
            mineru_block.get("enable_formula"),
            default=mineru_enable_formula,
        )
        mineru_enable_table = _coerce_optional_bool(
            mineru_block.get("enable_table"),
            default=mineru_enable_table,
        )
        mineru_is_ocr = _coerce_optional_bool(
            mineru_block.get("is_ocr"),
            default=mineru_is_ocr,
        )

        sanitized_block = dict(mineru_block)
        sanitized_block.pop("api_token", None)
        sanitized_payload["mineru"] = sanitized_block

    return (
        sanitized_payload,
        requested_parser_provider,
        mineru_token,
        mineru_model_version,
        mineru_enable_formula,
        mineru_enable_table,
        mineru_is_ocr,
    )


async def _load_raw_file_state(state: IngestParseState) -> IngestParseState:
    cs = get_content_store()
    with managed_session() as session:
        raw_file = get_raw_file_by_id(session, state["file_id"])
        if raw_file is None or raw_file.user_id != state["user_id"]:
            return {
                **state,
                "error": f"raw_file_not_found:{state['file_id']}",
            }

        file_id = state["file_id"]
        file_scope = cs.user_file_scope(user_id=raw_file.user_id)
        temp_dir = Path(tempfile.mkdtemp(prefix="atm_ingest_"))
        storage_key = raw_file.file_path or raw_file.storage_key
        local_path = await cs.materialize(storage_key, temp_dir)
        if not local_path.exists():
            return {
                **state,
                "error": f"raw_file_missing_storage:{file_id}",
            }

        if raw_file.parse_error_message:
            update_raw_file(
                session,
                raw_file,
                parse_error_message=None,
            )
            raw_file = get_raw_file_by_id(session, file_id) or raw_file

        parse_request_payload = _decode_json_object(raw_file.parse_metadata_json)
        (
            sanitized_payload,
            requested_parser_provider,
            mineru_token,
            mineru_model_version,
            mineru_enable_formula,
            mineru_enable_table,
            mineru_is_ocr,
        ) = _resolve_parse_request(raw_payload=parse_request_payload)

        if sanitized_payload != parse_request_payload:
            update_raw_file(
                session,
                raw_file,
                parse_metadata_json=json.dumps(sanitized_payload, ensure_ascii=False),
            )
            raw_file = get_raw_file_by_id(session, file_id) or raw_file

        mineru_token_source = "not_requested"
        if requested_parser_provider == "mineru":
            if mineru_token:
                mineru_token_source = "request"
            else:
                env_tokens = get_env_list("MINERU_API_TOKENS") or get_env_list("MINERU_API_TOKEN")
                if env_tokens:
                    mineru_token = secrets.choice(env_tokens)
                    mineru_token_source = "server_env_pool" if len(env_tokens) > 1 else "server_env"
                else:
                    mineru_token_source = "missing"

        extension = raw_file.file_ext.lower()
        parse_decision = build_parse_decision(
            extension=extension,
            requested_provider=requested_parser_provider,
            mineru_available=bool(mineru_token),
            markitdown_available=is_markitdown_available_for_extension(extension),
        )

        record_markdown_path = raw_file.markdown_path or file_scope.raw_markdown_key(
            file_uid=raw_file.uid,
            filename=raw_file.original_filename,
        )
        record_asset_dir = raw_file.asset_dir or file_scope.asset_prefix(
            file_uid=raw_file.uid,
            filename=raw_file.original_filename,
        ).rstrip("/")
        asset_upload_prefix = record_asset_dir.rstrip("/") + "/"
        asset_storage_dir = record_asset_dir
        asset_link_prefix = _relative_asset_link_prefix(
            markdown_key=record_markdown_path,
            asset_dir=record_asset_dir,
        )

        return {
            **state,
            "filename": raw_file.original_filename,
            "filetype": raw_file.file_ext,
            "file_path": str(local_path),
            "temp_dir": str(temp_dir),
            "local_markdown_path": str(temp_dir / f"{file_id}.md"),
            "local_asset_dir": str(temp_dir / "assets" / str(file_id)),
            "record_markdown_path": record_markdown_path,
            "record_asset_dir": record_asset_dir,
            "asset_upload_prefix": asset_upload_prefix,
            "asset_storage_dir": asset_storage_dir,
            "asset_link_prefix": asset_link_prefix,
            "asset_name_prefix": build_asset_name_prefix(
                filename=raw_file.original_filename,
                file_uid=raw_file.uid,
                file_id=file_id,
            ),
            "storage_backend": raw_file.storage_backend or "local",
            "requested_parser_provider": requested_parser_provider,
            "mineru_token": mineru_token,
            "mineru_token_source": mineru_token_source,
            "mineru_model_version": mineru_model_version,
            "mineru_enable_formula": mineru_enable_formula,
            "mineru_enable_table": mineru_enable_table,
            "mineru_is_ocr": mineru_is_ocr,
            "parse_decision": parse_decision,
            "is_text_fast_path": is_text_extension(extension),
            "text_category": categorize_text_extension(extension) if is_text_extension(extension) else None,
            "text_language_hint": get_text_language_hint(extension) if is_text_extension(extension) else None,
            "error": None,
        }


def build_load_raw_file_node(*, context: WorkflowContext):
    async def load_raw_file_node(state: IngestParseState) -> IngestParseState:
        logger = workflow_logger(context, state)
        logger.info("ingest_load_raw_file_started")
        next_state = await _load_raw_file_state(state)
        if next_state.get("error"):
            logger.warning("ingest_load_raw_file_failed", error=next_state["error"])
            return next_state

        parse_decision = next_state.get("parse_decision")
        logger.info(
            "ingest_load_raw_file_completed",
            file_path=next_state["file_path"],
            temp_dir=next_state["temp_dir"],
            text_fast_path=next_state["is_text_fast_path"],
            requested_parser_provider=next_state.get("requested_parser_provider"),
            primary_provider=parse_decision.primary_provider if parse_decision else None,
            mineru_token_source=next_state.get("mineru_token_source"),
        )
        return next_state

    return load_raw_file_node


def build_compute_fingerprint_node(*, context: WorkflowContext):
    async def compute_fingerprint_node(state: IngestParseState) -> IngestParseState:
        logger = workflow_logger(context, state)
        try:
            file_bytes = Path(state["file_path"]).read_bytes()
            content_hash = hashlib.sha256(file_bytes).hexdigest()
            file_size_bytes = len(file_bytes)
            logger.info("ingest_file_fingerprint_completed", file_size_bytes=file_size_bytes)
            return {
                **state,
                "content_hash": content_hash,
                "file_size_bytes": file_size_bytes,
                "error": None,
            }
        except Exception as exc:
            logger.error("ingest_file_fingerprint_failed", error=str(exc), exc_info=True)
            return {
                **state,
                "error": f"compute_fingerprint_failed: {exc}",
            }

    return compute_fingerprint_node


def build_classify_file_node(*, context: WorkflowContext):
    async def classify_file_node(state: IngestParseState) -> IngestParseState:
        logger = workflow_logger(context, state)
        try:
            classification = await asyncio.to_thread(
                classify_file,
                state["file_path"],
                state["filetype"],
            )
            classification_payload = json.dumps(classification.to_dict(), ensure_ascii=False)
            with managed_session() as session:
                raw_file = get_raw_file_by_id(session, state["file_id"])
                if raw_file is None or raw_file.user_id != state["user_id"]:
                    return {
                        **state,
                        "error": f"raw_file_not_found:{state['file_id']}",
                    }
                update_raw_file(
                    session,
                    raw_file,
                    estimated_pages=classification.estimated_pages,
                    detected_language=classification.detected_language,
                    classification_json=classification_payload,
                    ingest_status=IngestStatus.FAST_PARSING.value,
                    digest_current_step="ingest.fast_parse.running",
                )
            logger.info(
                "ingest_file_classified",
                category=classification.file_category,
                recommended_parser=classification.recommended_parser,
                detected_language=classification.detected_language,
                estimated_pages=classification.estimated_pages,
            )
            return {
                **state,
                "classification": classification,
                "classification_payload": classification_payload,
                "estimated_pages": classification.estimated_pages,
                "detected_language": classification.detected_language,
                "error": None,
            }
        except Exception as exc:
            logger.error("ingest_file_classify_failed", error=str(exc), exc_info=True)
            return {
                **state,
                "error": f"classify_file_failed: {exc}",
            }

    return classify_file_node


def build_plan_parse_node(*, context: WorkflowContext):
    async def plan_parse_node(state: IngestParseState) -> IngestParseState:
        logger = workflow_logger(context, state)
        try:
            parse_decision = state.get("parse_decision")
            if parse_decision and parse_decision.uses_mineru:
                parse_plan = ParsePlan(
                    mode="external_mineru",
                    parser_chain=["mineru"],
                    decision_reason=parse_decision.primary_reason,
                    options=ParserRunOptions(),
                )
            else:
                parse_plan = build_parse_plan(
                    file_path=state["file_path"],
                    filetype=state["filetype"],
                    file_size_bytes=state.get("file_size_bytes"),
                    classification=state.get("classification"),
                )
                if parse_decision and parse_decision.uses_markitdown:
                    markitdown_parser = resolve_markitdown_parser_name(state["filetype"])
                    if markitdown_parser:
                        parse_plan = parse_plan.model_copy(
                            update={
                                "mode": "local_markitdown",
                                "parser_chain": [markitdown_parser],
                                "decision_reason": parse_decision.primary_reason,
                            }
                        )
                        parse_plan.options.enable_page_vision_ocr = False
                        parse_plan.options.enable_asset_vision_ocr = False
                        parse_plan.options.asset_vision_ocr_limit = 0

            parse_plan.options.asset_name_prefix = state.get("asset_name_prefix", "")
            logger.info(
                "ingest_parse_plan_built",
                mode=parse_plan.mode,
                parser_chain=parse_plan.parser_chain,
                decision_reason=parse_plan.decision_reason,
                requested_parser_provider=state.get("requested_parser_provider"),
            )
            return {
                **state,
                "parse_plan": parse_plan,
                "error": None,
            }
        except Exception as exc:
            logger.error("ingest_parse_plan_failed", error=str(exc), exc_info=True)
            return {
                **state,
                "error": f"plan_parse_failed: {exc}",
            }

    return plan_parse_node
