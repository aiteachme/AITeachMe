"""Fast-parse ingest graph and public workflow entrypoint.

真实链路现在统一走 LangGraph：
读取文件上下文 -> 计算指纹 -> 文本快通道或分类/计划 -> 执行解析 -> 持久化并派发增强。
"""

from __future__ import annotations

import structlog
from langgraph.graph import END, StateGraph

from app.shared.infra.workflow import workflow_tracer
from app.shared.infra.workflow.context import WorkflowContext, create_langgraph_dev_context
from app.shared.infra.workflow.graph_export import WorkflowGraphExport
from app.shared.infra.workflow.result import WorkflowResult, err_result, ok_result
from app.shared.infra.workflow.runtime import run_state_graph
from app.workflows.ingest.common.node_tracing import named_route, traced_ingest_node
from app.workflows.ingest.parsing.prompts import PROMPTS
from app.workflows.ingest.parsing.nodes import (
    build_classify_file_node,
    build_compute_fingerprint_node,
    build_finalize_failure_node,
    build_finalize_success_node,
    build_load_raw_file_node,
    build_parse_file_node,
    build_plan_parse_node,
)
from app.workflows.ingest.parsing.state import (
    IngestParseGraphInput,
    IngestParseGraphOutput,
    IngestParseState,
)
from app.workflows.ingest.parsing.lib.lifecycle import mark_parse_workflow_failed

logger = structlog.get_logger(__name__)

RUN_NAME_FAST_PARSE = "透视引擎：解析上传文件"

STEP_LOAD_RAW_FILE = "load_raw_file"
STEP_COMPUTE_FINGERPRINT = "compute_fingerprint"
STEP_CLASSIFY_FILE = "classify_file"
STEP_PLAN_PARSE = "plan_parse"
STEP_PARSE_FILE = "parse_file"
STEP_FINALIZE_SUCCESS = "finalize_success"
STEP_FINALIZE_FAILURE = "finalize_failure"

STEP_DISPLAY_NAMES = {
    STEP_LOAD_RAW_FILE: "读取原始文件",
    STEP_COMPUTE_FINGERPRINT: "计算内容指纹",
    STEP_CLASSIFY_FILE: "识别资料类型",
    STEP_PLAN_PARSE: "制定解析计划",
    STEP_PARSE_FILE: "执行快速解析",
    STEP_FINALIZE_SUCCESS: "持久化解析结果",
    STEP_FINALIZE_FAILURE: "记录解析失败",
}

STEP_DETAILS: dict[str, dict[str, object]] = {
    STEP_LOAD_RAW_FILE: {
        "description": (
            "加载 RawFile、物化原始文件、解析请求参数与 provider 可用性，"
            "为后续 fast parse 组装统一运行上下文。"
        ),
        "input_keys": ["user_id", "course_id", "file_id"],
        "output_keys": [
            "filename",
            "filetype",
            "file_path",
            "temp_dir",
            "local_markdown_path",
            "local_asset_dir",
            "record_markdown_path",
            "record_asset_dir",
            "asset_upload_prefix",
            "asset_storage_dir",
            "asset_link_prefix",
            "asset_name_prefix",
            "requested_parser_provider",
            "parse_decision",
            "is_text_fast_path",
            "text_category",
            "text_language_hint",
            "error",
        ],
        "reads": ["RawFile", "parse_metadata_json", "ContentStore", "server env"],
        "writes": ["runtime state", "sanitized parse_metadata_json"],
        "routing": "continue -> compute_fingerprint; fail -> finalize_failure",
        "phase": "phase_1_setup",
    },
    STEP_COMPUTE_FINGERPRINT: {
        "description": "计算 SHA256 和文件大小，并决定是否直接进入文本 fast path。",
        "input_keys": ["file_path", "is_text_fast_path"],
        "output_keys": ["content_hash", "file_size_bytes", "error"],
        "reads": ["materialized file bytes"],
        "writes": ["content_hash", "file_size_bytes"],
        "routing": "text_fast_path -> parse_file; continue -> classify_file; fail -> finalize_failure",
        "phase": "phase_1_setup",
    },
    STEP_CLASSIFY_FILE: {
        "description": "对非文本文件做轻量分类，估计页数、语言和内容特征，并回写分类结果。",
        "input_keys": ["file_path", "filetype", "file_id", "user_id"],
        "output_keys": [
            "classification",
            "classification_payload",
            "estimated_pages",
            "detected_language",
            "error",
        ],
        "reads": ["materialized file", "RawFile"],
        "writes": ["classification_json", "estimated_pages", "detected_language", "ingest_status"],
        "routing": "continue -> plan_parse; fail -> finalize_failure",
        "phase": "phase_1_plan",
    },
    STEP_PLAN_PARSE: {
        "description": "根据 provider 决策、文件分类和环境能力生成 ParsePlan，明确解析模式与 parser chain。",
        "input_keys": [
            "file_path",
            "filetype",
            "file_size_bytes",
            "classification",
            "parse_decision",
            "requested_parser_provider",
        ],
        "output_keys": ["parse_plan", "error"],
        "reads": ["parse_decision", "classification", "parser capability"],
        "writes": ["parse_plan"],
        "routing": "continue -> parse_file; fail -> finalize_failure",
        "phase": "phase_1_plan",
    },
    STEP_PARSE_FILE: {
        "description": "执行 Phase 1 fast parse，进入文本 fast path、外部 provider 或本地 parser chain，并生成 Markdown 与资产。",
        "input_keys": [
            "file_path",
            "local_markdown_path",
            "local_asset_dir",
            "parse_plan",
            "parse_decision",
            "classification",
            "asset_link_prefix",
            "asset_name_prefix",
        ],
        "output_keys": [
            "parsed_markdown",
            "parse_metadata",
            "parser_used",
            "attempted_parsers",
            "parser_elapsed_s",
            "markdown_chars",
            "image_count",
            "quality_score",
            "needs_enhance",
            "needs_quality_reparse",
            "needs_asset_ocr",
            "error",
        ],
        "reads": ["materialized file", "ParsePlan", "external provider output", "local parsers"],
        "writes": ["local markdown", "local assets", "parse metadata", "quality score"],
        "routing": "continue -> finalize_success; fail -> finalize_failure",
        "phase": "phase_1_parse",
    },
    STEP_FINALIZE_SUCCESS: {
        "description": "持久化 Markdown 与 assets，刷新 RawFile 解析结果，并推进 ingest_status 到可消费状态。",
        "input_keys": [
            "file_id",
            "user_id",
            "parsed_markdown",
            "local_markdown_path",
            "local_asset_dir",
            "record_markdown_path",
            "asset_upload_prefix",
            "asset_storage_dir",
            "record_asset_dir",
            "parse_metadata",
            "parser_used",
            "classification_payload",
            "quality_score",
            "content_hash",
            "file_size_bytes",
            "needs_enhance",
            "is_text_fast_path",
        ],
        "output_keys": ["image_count", "error"],
        "reads": ["local markdown", "local assets", "RawFile", "ContentStore"],
        "writes": ["stored markdown", "stored assets", "raw_file_asset", "RawFile final state"],
        "routing": "continue -> end; fail -> finalize_failure",
        "phase": "phase_1_finalize",
    },
    STEP_FINALIZE_FAILURE: {
        "description": "统一记录失败状态，写回 parse_error_message 和失败型 ingest_status，并清理临时目录。",
        "input_keys": ["file_id", "user_id", "error", "temp_dir"],
        "output_keys": ["error"],
        "reads": ["RawFile", "temp_dir"],
        "writes": ["parse_error_message", "RawFile failed state"],
        "routing": "end",
        "phase": "phase_1_finalize",
    },
}


def route_after_step(state: IngestParseState) -> str:
    return "fail" if state.get("error") else "continue"


def route_after_fingerprint(state: IngestParseState) -> str:
    if state.get("error"):
        return "fail"
    if state.get("is_text_fast_path"):
        return "text_fast_path"
    return "continue"


named_route(route_after_step, "ingest_route_after_step")
named_route(route_after_fingerprint, "ingest_route_after_fingerprint")


def build_fast_parse_graph(
    *,
    context: WorkflowContext,
) -> StateGraph:
    """Build the canonical Phase 1 ingest graph."""

    workflow = StateGraph(
        IngestParseState,
        input_schema=IngestParseGraphInput,
        output_schema=IngestParseGraphOutput,
    )
    trace = workflow_tracer(context=context, lane="fast_parse")
    workflow.add_node(
        STEP_LOAD_RAW_FILE,
        traced_ingest_node(
            trace,
            node_key=STEP_LOAD_RAW_FILE,
            display_name=STEP_DISPLAY_NAMES[STEP_LOAD_RAW_FILE],
            details=STEP_DETAILS[STEP_LOAD_RAW_FILE],
            handler=build_load_raw_file_node(context=context),
            timing_field="load_ms",
        ),
    )
    workflow.add_node(
        STEP_COMPUTE_FINGERPRINT,
        traced_ingest_node(
            trace,
            node_key=STEP_COMPUTE_FINGERPRINT,
            display_name=STEP_DISPLAY_NAMES[STEP_COMPUTE_FINGERPRINT],
            details=STEP_DETAILS[STEP_COMPUTE_FINGERPRINT],
            handler=build_compute_fingerprint_node(context=context),
            timing_field="fingerprint_ms",
        ),
    )
    workflow.add_node(
        STEP_CLASSIFY_FILE,
        traced_ingest_node(
            trace,
            node_key=STEP_CLASSIFY_FILE,
            display_name=STEP_DISPLAY_NAMES[STEP_CLASSIFY_FILE],
            details=STEP_DETAILS[STEP_CLASSIFY_FILE],
            handler=build_classify_file_node(context=context),
            timing_field="classify_ms",
        ),
    )
    workflow.add_node(
        STEP_PLAN_PARSE,
        traced_ingest_node(
            trace,
            node_key=STEP_PLAN_PARSE,
            display_name=STEP_DISPLAY_NAMES[STEP_PLAN_PARSE],
            details=STEP_DETAILS[STEP_PLAN_PARSE],
            handler=build_plan_parse_node(context=context),
            timing_field="plan_ms",
        ),
    )
    workflow.add_node(
        STEP_PARSE_FILE,
        traced_ingest_node(
            trace,
            node_key=STEP_PARSE_FILE,
            display_name=STEP_DISPLAY_NAMES[STEP_PARSE_FILE],
            details=STEP_DETAILS[STEP_PARSE_FILE],
            handler=build_parse_file_node(context=context),
            timing_field="parse_ms",
        ),
    )
    workflow.add_node(
        STEP_FINALIZE_SUCCESS,
        traced_ingest_node(
            trace,
            node_key=STEP_FINALIZE_SUCCESS,
            display_name=STEP_DISPLAY_NAMES[STEP_FINALIZE_SUCCESS],
            details=STEP_DETAILS[STEP_FINALIZE_SUCCESS],
            handler=build_finalize_success_node(context=context),
            timing_field="finalize_ms",
        ),
    )
    workflow.add_node(
        STEP_FINALIZE_FAILURE,
        traced_ingest_node(
            trace,
            node_key=STEP_FINALIZE_FAILURE,
            display_name=STEP_DISPLAY_NAMES[STEP_FINALIZE_FAILURE],
            details=STEP_DETAILS[STEP_FINALIZE_FAILURE],
            handler=build_finalize_failure_node(context=context),
            timing_field="finalize_ms",
        ),
    )

    workflow.set_entry_point(STEP_LOAD_RAW_FILE)
    workflow.add_conditional_edges(
        STEP_LOAD_RAW_FILE,
        route_after_step,
        {"continue": STEP_COMPUTE_FINGERPRINT, "fail": STEP_FINALIZE_FAILURE},
    )
    workflow.add_conditional_edges(
        STEP_COMPUTE_FINGERPRINT,
        route_after_fingerprint,
        {
            "continue": STEP_CLASSIFY_FILE,
            "text_fast_path": STEP_PARSE_FILE,
            "fail": STEP_FINALIZE_FAILURE,
        },
    )
    workflow.add_conditional_edges(
        STEP_CLASSIFY_FILE,
        route_after_step,
        {"continue": STEP_PLAN_PARSE, "fail": STEP_FINALIZE_FAILURE},
    )
    workflow.add_conditional_edges(
        STEP_PLAN_PARSE,
        route_after_step,
        {"continue": STEP_PARSE_FILE, "fail": STEP_FINALIZE_FAILURE},
    )
    workflow.add_conditional_edges(
        STEP_PARSE_FILE,
        route_after_step,
        {"continue": STEP_FINALIZE_SUCCESS, "fail": STEP_FINALIZE_FAILURE},
    )
    workflow.add_conditional_edges(
        STEP_FINALIZE_SUCCESS,
        route_after_step,
        {"continue": END, "fail": STEP_FINALIZE_FAILURE},
    )
    workflow.add_edge(STEP_FINALIZE_FAILURE, END)
    return workflow


def create_parse_file_initial_state(*, user_id: str, course_id: str, file_id: str) -> IngestParseState:
    return {
        "user_id": user_id,
        "course_id": course_id,
        "file_id": file_id,
        "error": None,
    }


def get_langgraph_dev_fast_parse_graph() -> StateGraph:
    return build_fast_parse_graph(
        context=create_langgraph_dev_context("ingest.fast_parse.langgraph_dev"),
    )


def _build_export_graph() -> StateGraph:
    return build_fast_parse_graph(
        context=create_langgraph_dev_context("ingest.fast_parse.export"),
    )


def _build_error_metadata(state: IngestParseState) -> dict[str, object]:
    parse_plan = state.get("parse_plan")
    return {
        "user_id": state.get("user_id", ""),
        "course_id": state.get("course_id", ""),
        "file_id": state.get("file_id", ""),
        "filename": state.get("filename", ""),
        "filetype": state.get("filetype", ""),
        "parse_mode": parse_plan.mode if parse_plan else "",
        "parser_chain": parse_plan.parser_chain if parse_plan else [],
        "parser_used": state.get("parser_used", ""),
    }

async def run_parse_file_workflow(
    *,
    user_id: str,
    file_id: str,
    course_id: str = "",
) -> WorkflowResult[IngestParseState]:
    """Run one ingest file parse workflow and normalize result handling."""

    context_course = course_id or f"files:{user_id}"
    logger.info(
        "ingest_workflow_starting",
        course_id=course_id,
        user_id=user_id,
        file_id=file_id,
    )
    context = WorkflowContext(
        workflow_name="ingest.fast_parse",
        course_id=context_course,
        metadata={
            "lane": "fast_parse",
            "langsmith_run_name": RUN_NAME_FAST_PARSE,
            "user_id": user_id,
            "requested_course_id": course_id,
            "file_id": file_id,
        },
    )
    result = await run_state_graph(
        workflow_name="ingest.fast_parse",
        graph_builder=lambda: build_fast_parse_graph(context=context),
        initial_state=create_parse_file_initial_state(user_id=user_id, course_id=course_id, file_id=file_id),
        context=context,
    )
    if result.failed:
        return result

    final_state = result.require_value()
    error = str(final_state.get("error") or "").strip()
    if error:
        mark_parse_workflow_failed(
            user_id=user_id,
            file_id=file_id,
            error=error,
            step="ingest.parse.failed",
            course_id=course_id,
        )
        return err_result(
            "ingest_parse_failed",
            error,
            metadata=_build_error_metadata(final_state),
        )

    logger.info(
        "ingest_workflow_completed",
        course_id=course_id,
        user_id=user_id,
        file_id=file_id,
        parser_used=final_state.get("parser_used"),
        needs_enhance=bool(final_state.get("needs_enhance", False)),
    )
    return ok_result(final_state)


WORKFLOW_EXPORTS = (
    WorkflowGraphExport(
        key="ingest_parse",
        title="Ingest File Parse Workflow",
        description="Single-file ingest parsing workflow.",
        build_graph=_build_export_graph,
        prompts=PROMPTS,
    ),
)


__all__ = [
    "WORKFLOW_EXPORTS",
    "build_fast_parse_graph",
    "create_parse_file_initial_state",
    "get_langgraph_dev_fast_parse_graph",
    "route_after_fingerprint",
    "route_after_step",
    "run_parse_file_workflow",
]
