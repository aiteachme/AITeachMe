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
from app.workflows.digest.common.node_tracing import named_route, node_metadata, traced_digest_node
from app.workflows.digest.docgen.lib.defaults import DEFAULT_DOCGEN_MAX_PARALLEL_CHAPTERS
from app.workflows.digest.docgen.lib.reporting import build_docgen_lane_summary
from app.workflows.digest.docgen.nodes.assemble_chapter_tasks import (
    build_assemble_chapter_tasks_node,
)
from app.workflows.digest.docgen.nodes.build_chapter_execution_briefs import (
    build_chapter_execution_briefs_node,
)
from app.workflows.digest.docgen.nodes.build_document_backbone import build_document_backbone_node
from app.workflows.digest.docgen.nodes.confirm_and_seed_backbone import build_confirm_and_seed_backbone_node
from app.workflows.digest.docgen.nodes.enhance_chapters import build_enhance_chapters_node
from app.workflows.digest.docgen.nodes.generate_chapters import build_generate_chapters_node
from app.workflows.digest.docgen.nodes.generate_cover import build_generate_cover_node
from app.workflows.digest.docgen.nodes.load_context import build_load_context_node
from app.workflows.digest.docgen.nodes.lock_titles_for_chapters import build_lock_titles_for_chapters_node
from app.workflows.digest.docgen.nodes.merge_review import build_merge_review_node
from app.workflows.digest.docgen.nodes.prepare_global_seed import build_prepare_global_seed_node
from app.workflows.digest.docgen.nodes.publish_document import build_publish_document_node
from app.workflows.digest.docgen.nodes.repair_or_route import build_repair_or_route_node
from app.workflows.digest.docgen.nodes.review_content import (
    build_document_consistency_review_node,
    build_review_chapter_node,
)
from app.workflows.digest.docgen.nodes.sync_locked_titles import build_sync_locked_titles_node
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
NODE_SYNC_LOCKED_TITLES = "同步锁定标题"
NODE_PUBLISH = "发布知识文档"
RUN_NAME_DOCGEN = "织网引擎：生成知识文档"

NODE_TRACE_DETAILS: dict[str, dict[str, Any]] = {
    NODE_LOAD_CONTEXT: {
        "description": (
            "读取用户已经确认的构建方案、资料理解包和 Planner 会话上下文，校验章节合同是否完整，"
            "并组装 DocGenContext、document_context、chapter_assignments 与检索画像。这个节点只做入口合同冻结，"
            "不调用 LLM，也不静默改写用户确认过的章节语义。"
        ),
        "reads": ["confirmed_plan", "shared_inputs", "planner_context", "build_session"],
        "writes": ["docgen_context", "document_context", "chapter_assignments", "retrieval_profile"],
        "input_keys": [
            "subject",
            "file_ids",
            "user_prompt",
            "confirmed_plan",
            "shared_inputs",
            "planner_session_id",
            "confirmed_plan_id",
            "digest_mode",
        ],
        "output_keys": ["docgen_context", "document_context", "chapter_assignments", "retrieval_profile", "error"],
    },
    NODE_PREPARE_GLOBAL_SEED: {
        "description": (
            "做 DocGen 全局轻准备：并行推断文档级 intent_core，并按文件生成材料摘要、章节亲和度和高置信证据候选。"
            "这一步只把资料压缩成后续可用的结构化信号，不生成整本大纲，也不提前写章节正文。"
        ),
        "reads": ["docgen_context", "chapter_assignments", "shared_inputs", "source_packets", "section_packets"],
        "writes": [
            "intent_core",
            "intent_profile",
            "file_summaries",
            "source_affinity_by_chapter",
            "high_confidence_evidence_units",
        ],
        "input_keys": ["subject", "docgen_context", "chapter_assignments", "shared_inputs", "digest_mode"],
        "output_keys": [
            "intent_core",
            "intent_profile",
            "file_summaries",
            "source_affinity_by_chapter",
            "high_confidence_evidence_units",
            "plan_mismatch_warnings",
            "prepare_ms",
        ],
    },
    NODE_GENERATE_COVER: {
        "description": (
            "根据学科、用户目标、confirmed plan、资料摘要和 intent_profile 生成可选封面 sidecar。"
            "封面是 best-effort 辅助资产，失败或未配置图像模型时不阻断正文生成链路。"
        ),
        "reads": ["subject", "user_prompt", "document_context", "confirmed_plan", "file_summaries", "intent_profile"],
        "writes": ["cover_artifact", "cover_markdown"],
        "input_keys": [
            "subject",
            "build_session_id",
            "user_prompt",
            "document_context",
            "digest_mode",
            "confirmed_plan",
            "file_summaries",
            "intent_profile",
        ],
        "output_keys": ["cover_artifact", "cover_markdown", "cover_ms"],
    },
    NODE_LOCK_TITLES: {
        "description": (
            "在单节点内部按章节并行锁定最终章节标题。每个子任务只允许基于 confirmed plan、用户目标和课程模式优化标题表达，"
            "不能生成教学大纲、检索 query 或媒体需求，避免后续节点反复改标题导致章节身份漂移。"
        ),
        "reads": ["chapter_assignments", "docgen_context", "confirmed_plan"],
        "writes": ["locked_titles"],
        "input_keys": ["subject", "chapter_assignments", "docgen_context", "build_session_id"],
        "output_keys": ["locked_titles", "title_lock_ms", "llm_calls_total", "error"],
        "fanout": "internal_async_per_chapter",
    },
    NODE_CONFIRM_BACKBONE_SEED: {
        "description": (
            "用纯规则合并 confirmed plan、锁定标题、文件摘要、章节亲和度和高置信证据，生成整本文档骨架 seed。"
            "这里确定每章的目标、required elements、初始检索方向和 backbone_research_agenda，是进入全局知识骨架前的规则收口。"
        ),
        "reads": [
            "confirmed_plan",
            "locked_titles",
            "file_summaries",
            "source_affinity_by_chapter",
            "high_confidence_evidence_units",
        ],
        "writes": ["chapter_generation_plan_seed", "chapter_task_seeds", "backbone_research_agenda", "locked_titles"],
        "input_keys": [
            "confirmed_plan",
            "locked_titles",
            "file_summaries",
            "source_affinity_by_chapter",
            "high_confidence_evidence_units",
        ],
        "output_keys": ["chapter_generation_plan_seed", "chapter_task_seeds", "backbone_research_agenda", "seed_backbone_ms"],
    },
    NODE_BUILD_BACKBONE: {
        "description": (
            "构建整本文档级知识骨架，包括 canonical glossary、概念依赖、符号规范、核心主张池和易混点。"
            "当前实现以规则和 DocGen 结构化信号为主，用来约束后续章节写作和图谱同步，而不是直接产出正文。"
        ),
        "reads": ["chapter_task_seeds", "shared_inputs", "high_confidence_evidence_units", "backbone_research_agenda"],
        "writes": ["document_backbone", "backbone_conflict_warnings"],
        "input_keys": ["chapter_task_seeds", "shared_inputs", "high_confidence_evidence_units", "backbone_research_agenda"],
        "output_keys": ["document_backbone", "backbone_conflict_warnings", "backbone_ms"],
    },
    NODE_BUILD_CHAPTER_BRIEFS: {
        "description": (
            "在单节点内部按章节并行生成最小执行简报。每个 brief 只给本章 teaching_outline、目标概念/定义/公式/例题/易错点"
            "和少量检索 query，不允许改标题或扩展成完整大纲。"
        ),
        "reads": ["chapter_task_seeds", "document_backbone", "intent_core"],
        "writes": ["chapter_execution_briefs"],
        "input_keys": ["subject", "chapter_task_seeds", "document_backbone", "intent_core", "digest_mode"],
        "output_keys": ["chapter_execution_briefs", "chapter_prepare_ms", "llm_calls_total", "error"],
        "fanout": "internal_async_per_chapter",
    },
    NODE_ASSEMBLE_CHAPTER_TASKS: {
        "description": (
            "用纯规则把 locked titles、intent_core、document_backbone、文件摘要和章节 brief 合并成最终 ChapterGenerationPlan"
            "与 ChapterGenerationTask 列表。后续章节 fan-out 只消费这里冻结的单章执行合同。"
        ),
        "reads": [
            "confirmed_plan",
            "locked_titles",
            "intent_core",
            "chapter_task_seeds",
            "chapter_execution_briefs",
            "document_backbone",
            "file_summaries",
        ],
        "writes": ["chapter_generation_plan", "chapter_tasks", "chapter_execution_briefs"],
        "input_keys": [
            "confirmed_plan",
            "locked_titles",
            "intent_core",
            "chapter_task_seeds",
            "chapter_execution_briefs",
            "document_backbone",
            "file_summaries",
        ],
        "output_keys": ["chapter_generation_plan", "chapter_tasks", "chapter_execution_briefs", "assemble_tasks_ms", "error"],
        "routing": "next step sends one branch per chapter",
    },
    NODE_GENERATE_CHAPTERS: {
        "description": (
            "LangGraph Send fan-out 后的单章生成节点。每个分支独立执行本地/外部检索、上下文压缩、claim/evidence/conflict 账本构建、"
            "章节正文写作、轻量 critique 和必要 rewrite；输出通过 reducer 汇总回整本 state。"
        ),
        "reads": ["chapter_task", "shared_inputs", "document_context", "docgen_context", "document_backbone"],
        "writes": ["chapter_drafts", "research_traces", "claim_ledgers", "claim_evidence_maps", "evidence_ledgers", "conflict_reports"],
        "input_keys": [
            "chapter_task",
            "shared_inputs",
            "document_context",
            "docgen_context",
            "document_backbone",
            "total_chapters",
        ],
        "output_keys": [
            "chapter_drafts",
            "research_traces",
            "claim_ledgers",
            "claim_evidence_maps",
            "evidence_ledgers",
            "conflict_reports",
            "research_ms",
            "draft_ms",
            "llm_calls_total",
            "error",
        ],
        "fanout": "langgraph_send_per_chapter",
    },
    NODE_ENHANCE_CHAPTERS: {
        "description": (
            "对单章草稿做增强处理：生成或修复 Mermaid、交互 HTML sidecar、公式/Markdown 结构，并按模式补充必要例题或练习。"
            "该节点不重写核心知识，不改变 claim/evidence 绑定，只做发布前内容增强。"
        ),
        "reads": ["chapter_drafts", "claim_ledgers", "document_backbone", "digest_mode"],
        "writes": ["enhanced_chapter_drafts", "asset_manifests", "practice_manifests"],
        "input_keys": ["chapter_drafts", "claim_ledgers", "document_backbone", "digest_mode"],
        "output_keys": ["enhanced_chapter_drafts", "asset_manifests", "practice_manifests", "enhance_ms", "error"],
    },
    NODE_REVIEW_CHAPTERS: {
        "description": (
            "LangGraph Send fan-out 后的单章复核节点。每个分支检查章节合同覆盖、证据支撑、写作质量和风险信号，"
            "产出 reviewed draft、review report 和后续 repair action，随后 fan-in 到整本一致性复核。"
        ),
        "reads": ["enhanced_chapter_draft", "chapter_tasks", "claim_ledgers", "claim_evidence_maps", "conflict_reports"],
        "writes": ["reviewed_chapter_draft_items", "chapter_review_report_items", "review_action_items"],
        "input_keys": [
            "enhanced_chapter_draft",
            "chapter_tasks",
            "claim_ledgers",
            "claim_evidence_maps",
            "conflict_reports",
            "total_chapters",
        ],
        "output_keys": [
            "reviewed_chapter_draft_items",
            "chapter_review_report_items",
            "review_action_items",
            "review_ms",
            "llm_calls_total",
            "error",
        ],
        "fanout": "langgraph_send_per_chapter",
    },
    NODE_DOCUMENT_CONSISTENCY_REVIEW: {
        "description": (
            "在所有章节复核 fan-in 后执行整本文档一致性检查，重点看跨章术语、符号、定义、前置关系、重复讲解和风格断裂。"
            "当前主要是规则复核，不检索、不改正文，只产出 document_consistency_report 和整本 review_decision。"
        ),
        "reads": ["reviewed_chapter_draft_items", "chapter_review_report_items", "review_action_items", "document_backbone"],
        "writes": ["reviewed_chapter_drafts", "chapter_review_reports", "review_actions", "document_consistency_report", "review_decision"],
        "input_keys": [
            "reviewed_chapter_draft_items",
            "chapter_review_report_items",
            "review_action_items",
            "document_backbone",
        ],
        "output_keys": [
            "reviewed_chapter_drafts",
            "chapter_review_reports",
            "review_actions",
            "document_consistency_report",
            "review_decision",
            "review_ms",
            "error",
        ],
    },
    NODE_REPAIR_OR_ROUTE: {
        "description": (
            "根据 review_actions 执行有限回流：surface_patch/section_patch 会做局部 Markdown patch，"
            "evidence_patch、regenerate_chapter、re_dispatch、rebuild_backbone 等重动作先结构化记录为 unresolved warnings。"
            "这个节点负责把复核问题转成可追踪的修补记录，不重新展开整本生成。"
        ),
        "reads": ["review_actions", "reviewed_chapter_drafts", "enhanced_chapter_drafts", "chapter_tasks", "document_backbone"],
        "writes": ["reviewed_chapter_drafts", "unresolved_warnings", "repair_trace", "repair_loop_state"],
        "input_keys": [
            "review_actions",
            "reviewed_chapter_drafts",
            "enhanced_chapter_drafts",
            "chapter_tasks",
            "document_backbone",
        ],
        "output_keys": ["reviewed_chapter_drafts", "unresolved_warnings", "repair_trace", "repair_loop_state", "repair_ms", "error"],
    },
    NODE_MERGE_REVIEW: {
        "description": (
            "把 reviewed chapter drafts 按 chapter_index 去重排序并合并为整本文档 Markdown，生成章节发布 metadata，"
            "同时做发布前完整性检查。这里不再重写知识内容，只负责 fan-in 后的结构收口。"
        ),
        "reads": ["reviewed_chapter_drafts", "chapter_generation_plan", "document_backbone", "asset_manifests", "practice_manifests"],
        "writes": ["merged_markdown", "chapter_metadatas", "merge_review_report"],
        "input_keys": [
            "reviewed_chapter_drafts",
            "chapter_generation_plan",
            "document_backbone",
            "claim_ledgers",
            "claim_evidence_maps",
            "evidence_ledgers",
            "conflict_reports",
            "document_consistency_report",
            "review_actions",
        ],
        "output_keys": ["merged_markdown", "chapter_metadatas", "merge_review_report", "merge_review_ms", "error"],
    },
    NODE_SYNC_LOCKED_TITLES: {
        "description": (
            "把标题锁定阶段已经确定的标题同步到章节 metadata、每章 Markdown 一级标题和整本 Markdown。"
            "该节点不会调用 LLM 重新起标题，也不会推翻用户 confirmed plan 的章节语义。"
        ),
        "reads": ["chapter_metadatas", "locked_titles", "merged_markdown", "merge_review_report"],
        "writes": ["final_chapter_titles", "chapter_metadatas", "title_review_report", "merged_markdown"],
        "input_keys": ["chapter_metadatas", "locked_titles", "merged_markdown", "merge_review_report"],
        "output_keys": ["final_chapter_titles", "chapter_metadatas", "title_review_report", "merged_markdown", "finalize_ms", "error"],
    },
    NODE_PUBLISH: {
        "description": (
            "发布 DocGen 产物：写出章节 Markdown、整本 Markdown、docgen_manifest、版本归档和 KnowledgeDoc rows。"
            "如果 sync_after_docgen 开启，后续由构建生命周期触发 kg_doc_sync；本节点自身只负责文档持久化。"
        ),
        "reads": ["merged_markdown", "chapter_metadatas", "docgen_artifacts", "document_context", "cover_artifact"],
        "writes": ["doc_ids", "built_paths", "merged_path", "enriched_markdown"],
        "input_keys": ["merged_markdown", "chapter_metadatas", "document_context", "build_session_id"],
        "output_keys": ["doc_ids", "built_paths", "merged_path", "enriched_markdown", "error"],
    },
}


def _trace_docgen_node(trace, node_key: str, handler, *, timing_field: str | None = None):
    details = NODE_TRACE_DETAILS[node_key]
    return traced_digest_node(
        trace,
        node_key=node_key,
        display_name=node_key,
        details=details,
        handler=handler,
        timing_field=timing_field,
    )


def _langgraph_node_metadata(node_key: str) -> dict[str, object]:
    return node_metadata(
        node_key=node_key,
        display_name=node_key,
        details=NODE_TRACE_DETAILS[node_key],
    )


def build_docgen_graph(*, context: WorkflowContext) -> StateGraph:
    """Build the rewritten DocGen graph."""

    workflow = StateGraph(DocGenState)
    trace = workflow_tracer(context=context, lane="docgen")
    workflow.add_node(
        NODE_LOAD_CONTEXT,
        _trace_docgen_node(
            trace,
            NODE_LOAD_CONTEXT,
            build_load_context_node(context=context),
            timing_field="load_ms",
        ),
        metadata=_langgraph_node_metadata(NODE_LOAD_CONTEXT),
    )
    workflow.add_node(
        NODE_PREPARE_GLOBAL_SEED,
        _trace_docgen_node(
            trace,
            NODE_PREPARE_GLOBAL_SEED,
            build_prepare_global_seed_node(context=context),
            timing_field="prepare_ms",
        ),
        metadata=_langgraph_node_metadata(NODE_PREPARE_GLOBAL_SEED),
    )
    workflow.add_node(
        NODE_GENERATE_COVER,
        _trace_docgen_node(
            trace,
            NODE_GENERATE_COVER,
            build_generate_cover_node(context=context),
            timing_field="cover_ms",
        ),
        metadata=_langgraph_node_metadata(NODE_GENERATE_COVER),
    )
    workflow.add_node(
        NODE_LOCK_TITLES,
        _trace_docgen_node(
            trace,
            NODE_LOCK_TITLES,
            build_lock_titles_for_chapters_node(context=context),
            timing_field="title_lock_ms",
        ),
        metadata=_langgraph_node_metadata(NODE_LOCK_TITLES),
    )
    workflow.add_node(
        NODE_CONFIRM_BACKBONE_SEED,
        _trace_docgen_node(
            trace,
            NODE_CONFIRM_BACKBONE_SEED,
            build_confirm_and_seed_backbone_node(context=context),
            timing_field="seed_backbone_ms",
        ),
        metadata=_langgraph_node_metadata(NODE_CONFIRM_BACKBONE_SEED),
    )
    workflow.add_node(
        NODE_BUILD_BACKBONE,
        _trace_docgen_node(
            trace,
            NODE_BUILD_BACKBONE,
            build_document_backbone_node(context=context),
            timing_field="backbone_ms",
        ),
        metadata=_langgraph_node_metadata(NODE_BUILD_BACKBONE),
    )
    workflow.add_node(
        NODE_BUILD_CHAPTER_BRIEFS,
        _trace_docgen_node(
            trace,
            NODE_BUILD_CHAPTER_BRIEFS,
            build_chapter_execution_briefs_node(context=context),
            timing_field="chapter_prepare_ms",
        ),
        metadata=_langgraph_node_metadata(NODE_BUILD_CHAPTER_BRIEFS),
    )
    workflow.add_node(
        NODE_ASSEMBLE_CHAPTER_TASKS,
        _trace_docgen_node(
            trace,
            NODE_ASSEMBLE_CHAPTER_TASKS,
            build_assemble_chapter_tasks_node(context=context),
            timing_field="assemble_tasks_ms",
        ),
        metadata=_langgraph_node_metadata(NODE_ASSEMBLE_CHAPTER_TASKS),
    )
    workflow.add_node(
        NODE_GENERATE_CHAPTERS,
        _trace_docgen_node(trace, NODE_GENERATE_CHAPTERS, build_generate_chapters_node(context=context)),
        metadata=_langgraph_node_metadata(NODE_GENERATE_CHAPTERS),
    )
    workflow.add_node(
        NODE_ENHANCE_CHAPTERS,
        _trace_docgen_node(trace, NODE_ENHANCE_CHAPTERS, build_enhance_chapters_node(context=context)),
        metadata=_langgraph_node_metadata(NODE_ENHANCE_CHAPTERS),
    )
    workflow.add_node(
        NODE_REVIEW_CHAPTERS,
        _trace_docgen_node(
            trace,
            NODE_REVIEW_CHAPTERS,
            build_review_chapter_node(context=context),
            timing_field="review_ms",
        ),
        metadata=_langgraph_node_metadata(NODE_REVIEW_CHAPTERS),
    )
    workflow.add_node(
        NODE_DOCUMENT_CONSISTENCY_REVIEW,
        _trace_docgen_node(
            trace,
            NODE_DOCUMENT_CONSISTENCY_REVIEW,
            build_document_consistency_review_node(context=context),
            timing_field="review_ms",
        ),
        metadata=_langgraph_node_metadata(NODE_DOCUMENT_CONSISTENCY_REVIEW),
    )
    workflow.add_node(
        NODE_REPAIR_OR_ROUTE,
        _trace_docgen_node(
            trace,
            NODE_REPAIR_OR_ROUTE,
            build_repair_or_route_node(context=context),
            timing_field="repair_ms",
        ),
        metadata=_langgraph_node_metadata(NODE_REPAIR_OR_ROUTE),
    )
    workflow.add_node(
        NODE_MERGE_REVIEW,
        _trace_docgen_node(
            trace,
            NODE_MERGE_REVIEW,
            build_merge_review_node(context=context),
            timing_field="merge_review_ms",
        ),
        metadata=_langgraph_node_metadata(NODE_MERGE_REVIEW),
    )
    workflow.add_node(
        NODE_SYNC_LOCKED_TITLES,
        _trace_docgen_node(
            trace,
            NODE_SYNC_LOCKED_TITLES,
            build_sync_locked_titles_node(context=context),
            timing_field="finalize_ms",
        ),
        metadata=_langgraph_node_metadata(NODE_SYNC_LOCKED_TITLES),
    )
    workflow.add_node(
        NODE_PUBLISH,
        _trace_docgen_node(trace, NODE_PUBLISH, build_publish_document_node(context=context)),
        metadata=_langgraph_node_metadata(NODE_PUBLISH),
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
        {"continue": NODE_SYNC_LOCKED_TITLES, "fail": END},
    )
    workflow.add_conditional_edges(
        NODE_SYNC_LOCKED_TITLES,
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
        "retrieval_profile": resolve_docgen_retrieval_profile(
            digest_mode,
            user_prompt=user_prompt,
            subject_name=subject,
        ),
        "teaching_action": "docgen_build",
        "document_context": None,
        "docgen_context": {},
        "error": None,
    }


def route_after_step(state: DocGenState) -> Literal["fail", "continue"]:
    return "fail" if state.get("error") else "continue"


def route_after_step_for_trace(state: DocGenState) -> Literal["fail", "continue"]:
    return route_after_step(state)


route_after_step_for_trace = named_route(route_after_step_for_trace, "检查是否继续")


def _child_state_base(state: DocGenState, *, teaching_action: str) -> dict[str, Any]:
    return {
        "subject": state["subject"],
        "requested_at": state["requested_at"],
        "build_session_id": state.get("build_session_id", ""),
        "planner_session_id": state.get("planner_session_id", ""),
        "confirmed_plan_id": state.get("confirmed_plan_id", ""),
        "digest_mode": state.get("digest_mode", ""),
        "retrieval_profile": state.get("retrieval_profile", ""),
        "teaching_action": teaching_action,
    }


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
                **_child_state_base(state, teaching_action="chapter_generate"),
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


build_generation_sends_for_trace = named_route(build_generation_sends_for_trace, "按章节分发生成任务")


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
                **_child_state_base(state, teaching_action="chapter_review"),
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


build_review_sends_for_trace = named_route(build_review_sends_for_trace, "按章节分发复核任务")


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
