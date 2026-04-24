"""DocGen graph definition and runtime entrypoint.

这个文件对齐 Planner 的组织方式：上半部分定义 LangGraph 节点与
fan-out/fan-in 路由，下半部分提供单次 `run_docgen_workflow` 运行入口。
构建锁、后台任务和 API 装配仍在 `lib/build_lifecycle.py`。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from langgraph.graph import END, StateGraph
from langgraph.types import Send
from app.shared.infra.workflow import workflow_tracer
from app.shared.infra.workflow.context import WorkflowContext, create_langgraph_dev_context
from app.shared.infra.workflow.events import InProcessEventBus
from app.shared.infra.workflow.result import WorkflowResult, err_result
from app.shared.infra.workflow.runtime import run_state_graph
from app.workflows.digest.common.events import (
    DocGenCompletedEvent,
    DocGenFailedEvent,
    DocGenRequestedEvent,
)
from app.workflows.digest.common.metrics import build_token_summary
from app.workflows.digest.docgen.lib.defaults import DEFAULT_DOCGEN_MAX_PARALLEL_CHAPTERS
from app.workflows.digest.docgen.lib.reporting import build_docgen_lane_summary
from app.workflows.digest.docgen.nodes import (
    build_assemble_chapter_tasks_node,
    build_chapter_execution_briefs_node,
    build_confirm_and_seed_backbone_node,
    build_document_backbone_node,
    build_document_consistency_review_node,
    build_enhance_chapters_node,
    build_finalize_titles_node,
    build_generate_cover_node,
    build_generate_chapters_node,
    build_lock_titles_for_chapters_node,
    build_load_context_node,
    build_merge_review_node,
    build_prepare_global_seed_node,
    build_publish_document_node,
    build_repair_or_route_node,
    build_review_chapter_node,
)
from app.workflows.digest.docgen.nodes.common import resolve_docgen_retrieval_profile
from app.workflows.digest.docgen.state import DocGenState

NODE_LOAD_CONTEXT = "读取确认方案"
NODE_PREPARE_GLOBAL_SEED = "准备全局种子"
NODE_GENERATE_COVER = "生成封面"
NODE_LOCK_TITLES = "锁定章节标题"
NODE_CONFIRM_BACKBONE_SEED = "确认骨架种子"
NODE_BUILD_BACKBONE = "构建文档知识骨架"
NODE_BUILD_CHAPTER_BRIEFS = "生成章节执行简报"
NODE_ASSEMBLE_CHAPTER_TASKS = "组装最终章节任务"
NODE_GENERATE_CHAPTERS = "生成章节草稿"
NODE_ENHANCE_CHAPTERS = "增强章节内容"
NODE_REVIEW_CHAPTERS = "复核章节内容"
NODE_DOCUMENT_CONSISTENCY_REVIEW = "复核整本一致性"
NODE_REPAIR_OR_ROUTE = "记录复核回流动作"
NODE_MERGE_REVIEW = "合并检查整本文档"
NODE_FINALIZE_TITLES = "收口章节标题"
NODE_PUBLISH = "发布知识文档"
RUN_NAME_DOCGEN = "织网引擎：生成知识文档"


def _named_route(fn, name: str):
    """给 LangGraph 条件路由函数设置可读名称，方便图导出和 LangSmith 展示。"""

    fn.__name__ = name
    fn.__qualname__ = name
    return fn


def build_docgen_graph(*, context: WorkflowContext) -> StateGraph:
    """Build the rewritten DocGen graph."""

    workflow = StateGraph(DocGenState)
    trace = workflow_tracer(context=context, lane="docgen")
    workflow.add_node(
        NODE_LOAD_CONTEXT,
        trace.node(build_load_context_node(context=context), name=NODE_LOAD_CONTEXT, timing_field="load_ms"),
    )
    workflow.add_node(
        NODE_PREPARE_GLOBAL_SEED,
        trace.node(
            build_prepare_global_seed_node(context=context),
            name=NODE_PREPARE_GLOBAL_SEED,
            timing_field="prepare_ms",
        ),
    )
    workflow.add_node(
        NODE_GENERATE_COVER,
        trace.node(
            build_generate_cover_node(context=context),
            name=NODE_GENERATE_COVER,
            timing_field="cover_ms",
        ),
    )
    workflow.add_node(
        NODE_LOCK_TITLES,
        trace.node(
            build_lock_titles_for_chapters_node(context=context),
            name=NODE_LOCK_TITLES,
            timing_field="title_lock_ms",
        ),
    )
    workflow.add_node(
        NODE_CONFIRM_BACKBONE_SEED,
        trace.node(
            build_confirm_and_seed_backbone_node(context=context),
            name=NODE_CONFIRM_BACKBONE_SEED,
            timing_field="seed_backbone_ms",
        ),
    )
    workflow.add_node(
        NODE_BUILD_BACKBONE,
        trace.node(
            build_document_backbone_node(context=context),
            name=NODE_BUILD_BACKBONE,
            timing_field="backbone_ms",
        ),
    )
    workflow.add_node(
        NODE_BUILD_CHAPTER_BRIEFS,
        trace.node(
            build_chapter_execution_briefs_node(context=context),
            name=NODE_BUILD_CHAPTER_BRIEFS,
            timing_field="chapter_prepare_ms",
        ),
    )
    workflow.add_node(
        NODE_ASSEMBLE_CHAPTER_TASKS,
        trace.node(
            build_assemble_chapter_tasks_node(context=context),
            name=NODE_ASSEMBLE_CHAPTER_TASKS,
            timing_field="assemble_tasks_ms",
        ),
    )
    workflow.add_node(
        NODE_GENERATE_CHAPTERS,
        trace.node(build_generate_chapters_node(context=context), name=NODE_GENERATE_CHAPTERS),
    )
    workflow.add_node(
        NODE_ENHANCE_CHAPTERS,
        trace.node(build_enhance_chapters_node(context=context), name=NODE_ENHANCE_CHAPTERS),
    )
    workflow.add_node(
        NODE_REVIEW_CHAPTERS,
        trace.node(build_review_chapter_node(context=context), name=NODE_REVIEW_CHAPTERS, timing_field="review_ms"),
    )
    workflow.add_node(
        NODE_DOCUMENT_CONSISTENCY_REVIEW,
        trace.node(
            build_document_consistency_review_node(context=context),
            name=NODE_DOCUMENT_CONSISTENCY_REVIEW,
            timing_field="review_ms",
        ),
    )
    workflow.add_node(
        NODE_REPAIR_OR_ROUTE,
        trace.node(build_repair_or_route_node(context=context), name=NODE_REPAIR_OR_ROUTE, timing_field="repair_ms"),
    )
    workflow.add_node(
        NODE_MERGE_REVIEW,
        trace.node(build_merge_review_node(context=context), name=NODE_MERGE_REVIEW, timing_field="merge_review_ms"),
    )
    workflow.add_node(
        NODE_FINALIZE_TITLES,
        trace.node(build_finalize_titles_node(context=context), name=NODE_FINALIZE_TITLES, timing_field="finalize_ms"),
    )
    workflow.add_node(
        NODE_PUBLISH,
        trace.node(build_publish_document_node(context=context), name=NODE_PUBLISH),
    )

    workflow.set_entry_point(NODE_LOAD_CONTEXT)
    workflow.add_conditional_edges(
        NODE_LOAD_CONTEXT,
        route_after_step_for_trace,
        {"continue": NODE_PREPARE_GLOBAL_SEED, "fail": END},
    )
    workflow.add_conditional_edges(
        NODE_PREPARE_GLOBAL_SEED,
        route_after_step_for_trace,
        {"continue": NODE_GENERATE_COVER, "fail": END},
    )
    workflow.add_conditional_edges(
        NODE_GENERATE_COVER,
        route_after_step_for_trace,
        {"continue": NODE_LOCK_TITLES, "fail": END},
    )
    workflow.add_conditional_edges(
        NODE_LOCK_TITLES,
        route_after_step_for_trace,
        {"continue": NODE_CONFIRM_BACKBONE_SEED, "fail": END},
    )
    workflow.add_conditional_edges(
        NODE_CONFIRM_BACKBONE_SEED,
        route_after_step_for_trace,
        {"continue": NODE_BUILD_BACKBONE, "fail": END},
    )
    workflow.add_conditional_edges(
        NODE_BUILD_BACKBONE,
        route_after_step_for_trace,
        {"continue": NODE_BUILD_CHAPTER_BRIEFS, "fail": END},
    )
    workflow.add_conditional_edges(
        NODE_BUILD_CHAPTER_BRIEFS,
        route_after_step_for_trace,
        {"continue": NODE_ASSEMBLE_CHAPTER_TASKS, "fail": END},
    )
    workflow.add_conditional_edges(
        NODE_ASSEMBLE_CHAPTER_TASKS,
        build_generation_sends_for_trace,
        {"fail": END},
    )
    workflow.add_edge(NODE_GENERATE_CHAPTERS, NODE_ENHANCE_CHAPTERS)
    workflow.add_conditional_edges(
        NODE_ENHANCE_CHAPTERS,
        build_review_sends_for_trace,
        {"fail": END},
    )
    workflow.add_edge(NODE_REVIEW_CHAPTERS, NODE_DOCUMENT_CONSISTENCY_REVIEW)
    workflow.add_conditional_edges(
        NODE_DOCUMENT_CONSISTENCY_REVIEW,
        route_after_step_for_trace,
        {"continue": NODE_REPAIR_OR_ROUTE, "fail": END},
    )
    workflow.add_conditional_edges(
        NODE_REPAIR_OR_ROUTE,
        route_after_step_for_trace,
        {"continue": NODE_MERGE_REVIEW, "fail": END},
    )
    workflow.add_conditional_edges(
        NODE_MERGE_REVIEW,
        route_after_step_for_trace,
        {"continue": NODE_FINALIZE_TITLES, "fail": END},
    )
    workflow.add_conditional_edges(
        NODE_FINALIZE_TITLES,
        route_after_step_for_trace,
        {"continue": NODE_PUBLISH, "fail": END},
    )
    workflow.add_edge(NODE_PUBLISH, END)
    return workflow


def create_docgen_initial_state(
    *,
    subject: str,
    file_ids: list[int],
    user_prompt: str | None,
    requested_at: datetime,
    build_session_id: str | None,
    shared_inputs: Any | None = None,
    confirmed_plan: dict[str, Any] | None = None,
    planner_session_id: str | None = None,
    confirmed_plan_id: str | None = None,
    digest_mode: str | None = None,
) -> DocGenState:
    """Create initial state for the DocGen graph."""

    return {
        "subject": subject,
        "file_ids": file_ids,
        "user_prompt": user_prompt,
        "requested_at": requested_at,
        "build_session_id": build_session_id or "",
        "shared_inputs": shared_inputs,
        "confirmed_plan": confirmed_plan,
        "planner_session_id": planner_session_id or "",
        "confirmed_plan_id": confirmed_plan_id or "",
        "digest_mode": digest_mode or "",
        "retrieval_profile": resolve_docgen_retrieval_profile(digest_mode),
        "teaching_action": "docgen_build",
        "document_context": None,
        "docgen_context": {},
        "error": None,
    }


def route_after_step(state: DocGenState) -> Literal["fail", "continue"]:
    return "fail" if state.get("error") else "continue"


def route_after_step_for_trace(state: DocGenState) -> Literal["fail", "continue"]:
    return route_after_step(state)


route_after_step_for_trace = _named_route(route_after_step_for_trace, "检查是否继续")


def build_generation_sends(state: DocGenState) -> list[Send] | Literal["fail"]:
    if state.get("error"):
        return "fail"
    tasks = sorted(
        list(state.get("chapter_tasks", [])),
        key=lambda item: int(item.get("chapter_index", 0) or 0),
    )
    if not tasks:
        return "fail"
    total = len(tasks)
    return [
        Send(
            NODE_GENERATE_CHAPTERS,
            {
                "subject": state["subject"],
                "requested_at": state["requested_at"],
                "build_session_id": state.get("build_session_id", ""),
                "planner_session_id": state.get("planner_session_id", ""),
                "confirmed_plan_id": state.get("confirmed_plan_id", ""),
                "digest_mode": state.get("digest_mode", ""),
                "retrieval_profile": state.get("retrieval_profile", ""),
                "teaching_action": "chapter_generate",
                "shared_inputs": state.get("shared_inputs"),
                "document_context": state.get("document_context"),
                "docgen_context": state.get("docgen_context"),
                "document_backbone": state.get("document_backbone"),
                "chapter_task": task,
                "total_chapters": total,
            },
        )
        for task in tasks
    ]


def build_generation_sends_for_trace(state: DocGenState) -> list[Send] | Literal["fail"]:
    return build_generation_sends(state)


build_generation_sends_for_trace = _named_route(build_generation_sends_for_trace, "按章节分发生成任务")


def build_review_sends(state: DocGenState) -> list[Send] | Literal["fail"]:
    if state.get("error"):
        return "fail"
    enhanced = sorted(
        list(state.get("enhanced_chapter_drafts", [])),
        key=lambda item: int(item.get("chapter_index", 0) or 0),
    )
    if not enhanced:
        return "fail"
    total = len(enhanced)
    return [
        Send(
            NODE_REVIEW_CHAPTERS,
            {
                "subject": state["subject"],
                "requested_at": state["requested_at"],
                "build_session_id": state.get("build_session_id", ""),
                "planner_session_id": state.get("planner_session_id", ""),
                "confirmed_plan_id": state.get("confirmed_plan_id", ""),
                "digest_mode": state.get("digest_mode", ""),
                "retrieval_profile": state.get("retrieval_profile", ""),
                "teaching_action": "chapter_review",
                "enhanced_chapter_draft": draft,
                "chapter_tasks": list(state.get("chapter_tasks") or []),
                "claim_ledgers": list(state.get("claim_ledgers") or []),
                "claim_evidence_maps": list(state.get("claim_evidence_maps") or []),
                "conflict_reports": list(state.get("conflict_reports") or []),
                "total_chapters": total,
            },
        )
        for draft in enhanced
    ]


def build_review_sends_for_trace(state: DocGenState) -> list[Send] | Literal["fail"]:
    return build_review_sends(state)


build_review_sends_for_trace = _named_route(build_review_sends_for_trace, "按章节分发复核任务")


def get_langgraph_dev_docgen_graph() -> StateGraph:
    """Create the DocGen graph used only by ``langgraph dev`` / graph visualization."""

    return build_docgen_graph(context=create_langgraph_dev_context("digest.docgen.langgraph_dev"))


async def run_docgen_workflow(
    *,
    subject: str,
    file_ids: list[int],
    user_prompt: str | None = None,
    requested_at: datetime,
    event_bus: InProcessEventBus | None = None,
    build_session_id: str | None = None,
    shared_inputs: object | None = None,
    confirmed_plan: dict | None = None,
    planner_session_id: str | None = None,
    confirmed_plan_id: str | None = None,
    digest_mode: str | None = None,
) -> WorkflowResult[DocGenState]:
    """运行一次 DocGen LangGraph。

    这里只负责创建 workflow context、装配初始 state、执行图、汇总 token /
    timing 并发布完成或失败事件。构建锁、文件选择和后台任务生命周期不在
    这里处理，而是在 `lib.build_lifecycle`。
    """

    bus = event_bus or InProcessEventBus()
    await bus.publish(DocGenRequestedEvent(subject=subject, requested_at=requested_at, file_ids=file_ids))

    context = WorkflowContext(
        workflow_name="digest.docgen",
        subject=subject,
        event_bus=bus,
        metadata={
            "requested_at": requested_at.isoformat(),
            "lane": "docgen",
            "langsmith_run_name": RUN_NAME_DOCGEN,
            "build_session_id": build_session_id or "",
            "planner_session_id": planner_session_id or "",
            "confirmed_plan_id": confirmed_plan_id or "",
            "digest_mode": digest_mode or "",
            "max_concurrency": max(1, int(DEFAULT_DOCGEN_MAX_PARALLEL_CHAPTERS)),
        },
    )
    result = await run_state_graph(
        workflow_name="digest.docgen",
        graph_builder=lambda: build_docgen_graph(context=context),
        initial_state=create_docgen_initial_state(
            subject=subject,
            file_ids=file_ids,
            user_prompt=user_prompt,
            requested_at=requested_at,
            build_session_id=build_session_id,
            shared_inputs=shared_inputs,
            confirmed_plan=confirmed_plan,
            planner_session_id=planner_session_id,
            confirmed_plan_id=confirmed_plan_id,
            digest_mode=digest_mode,
        ),
        context=context,
    )
    if result.failed:
        token_summary = build_token_summary(build_session_id=build_session_id or None, lane="docgen")
        context.get_logger().bind(node="runtime").info(
            "docgen_timing_summary",
            **build_docgen_lane_summary(
                {},
                token_summary=token_summary,
                status="failed",
                error_message=result.error.detail,
            ),
        )
        await bus.publish(
            DocGenFailedEvent(
                subject=subject,
                requested_at=requested_at,
                error_message=result.error.detail,
            )
        )
        return result

    final_state = result.require_value()
    docgen_token_summary = build_token_summary(
        build_session_id=final_state.get("build_session_id") or build_session_id or None,
        lane="docgen",
    )
    final_state["token_summary"] = docgen_token_summary.model_dump()
    final_state["timing_summary"] = build_docgen_lane_summary(
        final_state,
        token_summary=docgen_token_summary,
    )
    context.get_logger().bind(node="runtime").info(
        "docgen_timing_summary",
        **final_state["timing_summary"],
    )
    error_message = final_state.get("error")
    if error_message:
        await bus.publish(
            DocGenFailedEvent(
                subject=subject,
                requested_at=requested_at,
                error_message=error_message,
            )
        )
        return err_result(
            "digest_docgen_failed",
            error_message,
            metadata={"requested_at": requested_at.isoformat(), "subject": subject},
        )

    await bus.publish(
        DocGenCompletedEvent(
            subject=subject,
            requested_at=requested_at,
            staged_chapter_count=len(final_state.get("chapter_metadatas", [])),
            draft_available=bool(str(final_state.get("merged_markdown", "")).strip()),
            published_doc_count=len(final_state.get("doc_ids", [])),
        )
    )
    return result


__all__ = [
    "build_docgen_graph",
    "build_generation_sends",
    "build_review_sends",
    "create_docgen_initial_state",
    "get_langgraph_dev_docgen_graph",
    "route_after_step",
    "run_docgen_workflow",
]
