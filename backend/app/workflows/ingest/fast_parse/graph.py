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
from app.workflows.ingest.parsing.prompts import PROMPTS
from app.workflows.ingest.fast_parse.nodes import (
    build_classify_file_node,
    build_compute_fingerprint_node,
    build_finalize_failure_node,
    build_finalize_success_node,
    build_load_raw_file_node,
    build_parse_file_node,
    build_plan_parse_node,
)
from app.workflows.ingest.fast_parse.state import (
    IngestParseGraphInput,
    IngestParseGraphOutput,
    IngestParseState,
)
from app.workflows.ingest.fast_parse.lib.lifecycle import mark_parse_workflow_failed

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


def route_after_step(state: IngestParseState) -> str:
    return "fail" if state.get("error") else "continue"


def route_after_fingerprint(state: IngestParseState) -> str:
    if state.get("error"):
        return "fail"
    if state.get("is_text_fast_path"):
        return "text_fast_path"
    return "continue"


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
        trace.node(
            build_load_raw_file_node(context=context),
            name=STEP_DISPLAY_NAMES[STEP_LOAD_RAW_FILE],
            timing_field="load_ms",
        ),
    )
    workflow.add_node(
        STEP_COMPUTE_FINGERPRINT,
        trace.node(
            build_compute_fingerprint_node(context=context),
            name=STEP_DISPLAY_NAMES[STEP_COMPUTE_FINGERPRINT],
            timing_field="fingerprint_ms",
        ),
    )
    workflow.add_node(
        STEP_CLASSIFY_FILE,
        trace.node(
            build_classify_file_node(context=context),
            name=STEP_DISPLAY_NAMES[STEP_CLASSIFY_FILE],
            timing_field="classify_ms",
        ),
    )
    workflow.add_node(
        STEP_PLAN_PARSE,
        trace.node(
            build_plan_parse_node(context=context),
            name=STEP_DISPLAY_NAMES[STEP_PLAN_PARSE],
            timing_field="plan_ms",
        ),
    )
    workflow.add_node(
        STEP_PARSE_FILE,
        trace.node(
            build_parse_file_node(context=context),
            name=STEP_DISPLAY_NAMES[STEP_PARSE_FILE],
            timing_field="parse_ms",
        ),
    )
    workflow.add_node(
        STEP_FINALIZE_SUCCESS,
        trace.node(
            build_finalize_success_node(context=context),
            name=STEP_DISPLAY_NAMES[STEP_FINALIZE_SUCCESS],
            timing_field="finalize_ms",
        ),
    )
    workflow.add_node(
        STEP_FINALIZE_FAILURE,
        trace.node(
            build_finalize_failure_node(context=context),
            name=STEP_DISPLAY_NAMES[STEP_FINALIZE_FAILURE],
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


def create_parse_file_initial_state(*, user_id: str, subject_id: str, file_id: int) -> IngestParseState:
    return {
        "user_id": user_id,
        "subject_id": subject_id,
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
        "subject": state.get("subject_id", ""),
        "file_id": state.get("file_id", 0),
        "filename": state.get("filename", ""),
        "filetype": state.get("filetype", ""),
        "parse_mode": parse_plan.mode if parse_plan else "",
        "parser_chain": parse_plan.parser_chain if parse_plan else [],
        "parser_used": state.get("parser_used", ""),
    }

async def run_parse_file_workflow(
    *,
    user_id: str,
    file_id: int,
    subject_id: str = "",
) -> WorkflowResult[IngestParseState]:
    """Run one ingest file parse workflow and normalize result handling."""

    context_subject = subject_id or f"files:{user_id}"
    logger.info(
        "ingest_workflow_starting",
        subject_id=subject_id,
        user_id=user_id,
        file_id=file_id,
    )
    context = WorkflowContext(
        workflow_name="ingest.fast_parse",
        subject_id=context_subject,
        metadata={
            "lane": "fast_parse",
            "langsmith_run_name": RUN_NAME_FAST_PARSE,
            "user_id": user_id,
            "requested_subject_id": subject_id,
            "file_id": file_id,
        },
    )
    result = await run_state_graph(
        workflow_name="ingest.fast_parse",
        graph_builder=lambda: build_fast_parse_graph(context=context),
        initial_state=create_parse_file_initial_state(user_id=user_id, subject_id=subject_id, file_id=file_id),
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
            subject_id=subject_id,
        )
        return err_result(
            "ingest_parse_failed",
            error,
            metadata=_build_error_metadata(final_state),
        )

    logger.info(
        "ingest_workflow_completed",
        subject_id=subject_id,
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
