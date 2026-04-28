"""KG docs-sync graph definition and runtime entrypoint.

这里定义 LangGraph 节点、路由、初始 state 和单次运行入口。
API 触发后的后台任务、构建锁和 graph lane runtime 由 builds.py 处理。
"""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from app.shared.infra.workflow import workflow_tracer
from app.shared.infra.workflow.context import WorkflowContext, create_langgraph_dev_context
from app.shared.infra.workflow.result import WorkflowResult, err_result, ok_result
from app.shared.infra.workflow.runtime import run_state_graph
from app.workflows.digest.common.node_tracing import named_route, node_metadata, traced_digest_node
from app.workflows.digest.kg_doc_sync.lib.models import KnowledgeSyncReport
from app.workflows.digest.kg_doc_sync.nodes.extract_node import extract_node
from app.workflows.digest.kg_doc_sync.nodes.fail_node import fail_node
from app.workflows.digest.kg_doc_sync.nodes.finalize_node import finalize_node
from app.workflows.digest.kg_doc_sync.nodes.init_run_node import init_run_node
from app.workflows.digest.kg_doc_sync.nodes.persist_node import persist_node
from app.workflows.digest.kg_doc_sync.nodes.prepare_node import prepare_node
from app.workflows.digest.kg_doc_sync.state import DocsSyncState

RUN_NAME_KG_DOC_SYNC = "知识图谱同步：根据知识文档更新图谱"

NODE_PREPARE = "prepare"
NODE_INIT_RUN = "init_run"
NODE_EXTRACT = "extract"
NODE_PERSIST = "persist"
NODE_FINALIZE = "finalize"
NODE_FAIL = "fail"

NODE_DISPLAY_NAMES = {
    NODE_PREPARE: "校验同步输入",
    NODE_INIT_RUN: "初始化同步批次",
    NODE_EXTRACT: "抽取图谱候选",
    NODE_PERSIST: "写入图谱变更",
    NODE_FINALIZE: "收口同步结果",
    NODE_FAIL: "记录同步失败",
}

NODE_TRACE_DETAILS: dict[str, dict[str, object]] = {
    NODE_PREPARE: {
        "description": (
            "校验 kg_doc_sync 的正式输入：必须有学科名和最新知识文档 Markdown，并保留 structured_context。"
            "structured_context 里会带 docgen_manifest、document_backbone、章节来源映射和文档版本等结构化信号，"
            "这些内容后续用于稳定节点身份、来源追踪和图谱质量指标。"
        ),
        "reads": ["KnowledgeDoc markdown", "structured_context", "Subject.document_summary_json"],
        "writes": ["validated docs-sync state", "node_metrics.prepare", "error"],
        "input_keys": ["subject", "markdown", "structured_context", "subject_context", "build_revision_no"],
        "output_keys": ["subject", "markdown", "structured_context", "node_metrics", "error"],
    },
    NODE_INIT_RUN: {
        "description": (
            "校验 Markdown carried KnowledgeUnit anchors，确定本轮图谱 revision 和知识文档版本，"
            "创建 knowledge_graph_sync_run running 记录，并把 sync_run_context 放入 state。"
        ),
        "reads": [
            "KnowledgeDoc markdown anchors",
            "structured_context.doc_version_no",
            "knowledge_graph_sync_run",
            "knowledge_unit",
            "knowledge_edge",
        ],
        "writes": ["knowledge_graph_sync_run", "sync_run_context", "node_metrics.init_run", "error"],
        "input_keys": ["subject", "markdown", "structured_context", "build_revision_no", "build_session_id"],
        "output_keys": ["sync_run_context", "build_revision_no", "structured_context", "node_metrics", "error"],
    },
    NODE_EXTRACT: {
        "description": (
            "把知识文档切成章节任务，特别长的大章会继续拆成子章节任务，并以最多 10 路并发调用结构化 LLM "
            "抽取候选 KnowledgeUnit 和关系；随后合并 DocGen backbone、标题结构边和跨章节语义边。"
            "本节点只产出 extraction_payload，不写图谱表；缺失 payload 会直接进入 fail，不会继续写入。"
            "语义候选必须来自 LLM/LLM 修复或显式结构化来源。"
        ),
        "reads": ["markdown", "subject_context", "structured_context", "sync_run_context", "Subject.document_summary_json"],
        "writes": ["extraction_payload", "subject_context", "node_metrics.extract", "error"],
        "input_keys": ["subject", "markdown", "subject_context", "sync_run_context"],
        "output_keys": ["extraction_payload", "subject_context", "node_metrics", "error"],
        "fanout": "节点内部按章节/子章节构造抽取任务，async gather + semaphore 并发执行，完成后 fan-in 为 extraction_payload。",
    },
    NODE_PERSIST: {
        "description": (
            "把 extraction_payload 写入 knowledge_unit、knowledge_edge、knowledge_graph_source_ref，"
            "执行稳定 anchor 去重、可选 RAG 去重和旧节点/旧边 deprecated 标记，最后完成 sync run。"
        ),
        "reads": ["extraction_payload", "sync_run_context", "knowledge_unit", "knowledge_edge"],
        "writes": [
            "knowledge_unit",
            "knowledge_edge",
            "knowledge_graph_source_ref",
            "knowledge_graph_sync_run",
            "KnowledgeSyncReport",
            "node_metrics.persist",
        ],
        "input_keys": ["sync_run_context", "extraction_payload"],
        "output_keys": ["report", "node_metrics", "error"],
    },
    NODE_FINALIZE: {
        "description": (
            "检查同步报告是否存在，并把成功状态交给上层 graph lane runtime。"
            "报告里包含 unit/edge 变更数、章节/子章节任务数、LLM 空结果修复统计、source_ref 数量、"
            "backbone 命中数、稳定 anchor 数和废弃实体数。"
        ),
        "reads": ["KnowledgeSyncReport"],
        "writes": ["final docs-sync state", "node_metrics.finalize", "error"],
        "input_keys": ["report", "error"],
        "output_keys": ["report", "node_metrics", "error"],
    },
    NODE_FAIL: {
        "description": (
            "统一记录 kg_doc_sync 失败状态。上游可能来自输入缺失、增量同步异常、DB 写入异常或报告缺失；"
            "这里不再吞掉错误，只把 error 留在 state 中让 workflow result 和 graph runtime 显示失败。"
        ),
        "reads": ["error", "subject", "build_session_id", "sync_run_context"],
        "writes": ["error", "knowledge_graph_sync_run", "node_metrics.fail"],
        "input_keys": ["subject", "build_session_id", "sync_run_context", "error"],
        "output_keys": ["node_metrics", "error"],
    },
}


def route_after_prepare(state: DocsSyncState) -> str:
    return "init_run" if not state.get("error") else "fail"


def route_after_init_run(state: DocsSyncState) -> str:
    return "extract" if not state.get("error") else "fail"


def route_after_extract(state: DocsSyncState) -> str:
    if state.get("error"):
        return "fail"
    return "persist" if state.get("extraction_payload") is not None else "fail"


def route_after_persist(state: DocsSyncState) -> str:
    return "finalize" if not state.get("error") else "fail"


def route_after_finalize(state: DocsSyncState) -> str:
    return "end" if not state.get("error") else "fail"


route_after_prepare_for_trace = named_route(route_after_prepare, "检查输入后继续同步")
route_after_init_run_for_trace = named_route(route_after_init_run, "检查同步批次是否初始化")
route_after_extract_for_trace = named_route(route_after_extract, "检查图谱候选是否抽取成功")
route_after_persist_for_trace = named_route(route_after_persist, "检查图谱写入是否成功")
route_after_finalize_for_trace = named_route(route_after_finalize, "检查是否完成")


def _trace_docs_sync_node(trace, node_key: str, handler):
    details = NODE_TRACE_DETAILS[node_key]
    return traced_digest_node(
        trace,
        node_key=node_key,
        display_name=NODE_DISPLAY_NAMES[node_key],
        details=details,
        handler=handler,
    )


def _langgraph_node_metadata(node_key: str) -> dict[str, object]:
    return node_metadata(
        node_key=node_key,
        display_name=NODE_DISPLAY_NAMES[node_key],
        details=NODE_TRACE_DETAILS[node_key],
    )


def build_docs_sync_graph(*, context: WorkflowContext) -> StateGraph:
    workflow = StateGraph(DocsSyncState)
    trace = workflow_tracer(context=context, lane="kg_doc_sync")
    workflow.add_node(
        NODE_PREPARE,
        _trace_docs_sync_node(trace, NODE_PREPARE, prepare_node),
        metadata=_langgraph_node_metadata(NODE_PREPARE),
    )
    workflow.add_node(
        NODE_INIT_RUN,
        _trace_docs_sync_node(trace, NODE_INIT_RUN, init_run_node),
        metadata=_langgraph_node_metadata(NODE_INIT_RUN),
    )
    workflow.add_node(
        NODE_EXTRACT,
        _trace_docs_sync_node(trace, NODE_EXTRACT, extract_node),
        metadata=_langgraph_node_metadata(NODE_EXTRACT),
    )
    workflow.add_node(
        NODE_PERSIST,
        _trace_docs_sync_node(trace, NODE_PERSIST, persist_node),
        metadata=_langgraph_node_metadata(NODE_PERSIST),
    )
    workflow.add_node(
        NODE_FINALIZE,
        _trace_docs_sync_node(trace, NODE_FINALIZE, finalize_node),
        metadata=_langgraph_node_metadata(NODE_FINALIZE),
    )
    workflow.add_node(
        NODE_FAIL,
        _trace_docs_sync_node(trace, NODE_FAIL, fail_node),
        metadata=_langgraph_node_metadata(NODE_FAIL),
    )

    workflow.set_entry_point(NODE_PREPARE)
    workflow.add_conditional_edges(
        NODE_PREPARE,
        route_after_prepare_for_trace,
        {"init_run": NODE_INIT_RUN, "fail": NODE_FAIL},
    )
    workflow.add_conditional_edges(
        NODE_INIT_RUN,
        route_after_init_run_for_trace,
        {"extract": NODE_EXTRACT, "fail": NODE_FAIL},
    )
    workflow.add_conditional_edges(
        NODE_EXTRACT,
        route_after_extract_for_trace,
        {"persist": NODE_PERSIST, "fail": NODE_FAIL},
    )
    workflow.add_conditional_edges(
        NODE_PERSIST,
        route_after_persist_for_trace,
        {"finalize": NODE_FINALIZE, "fail": NODE_FAIL},
    )
    workflow.add_conditional_edges(
        NODE_FINALIZE,
        route_after_finalize_for_trace,
        {"end": END, "fail": NODE_FAIL},
    )
    workflow.add_edge(NODE_FAIL, END)
    return workflow


def create_docs_sync_initial_state(
    *,
    subject: str,
    markdown: str,
    build_revision_no: int | None,
    build_session_id: str | None = None,
    subject_context: str | None = None,
    structured_context: dict[str, object] | None = None,
) -> DocsSyncState:
    return {
        "subject": subject,
        "markdown": markdown,
        "subject_context": subject_context or "",
        "structured_context": dict(structured_context or {}),
        "build_revision_no": build_revision_no,
        "build_session_id": build_session_id or "",
        "node_metrics": {},
        "sync_run_context": None,
        "extraction_payload": None,
        "report": None,
        "error": None,
    }


def _normalize_docs_sync_inputs(
    *,
    subject: str,
    markdown: str,
    build_revision_no: int | None = None,
) -> tuple[str, str, int | None]:
    return str(subject or "").strip(), str(markdown or ""), build_revision_no


async def run_graph_docs_sync_workflow(
    *,
    subject: str,
    markdown: str,
    build_revision_no: int | None = None,
    build_session_id: str | None = None,
    subject_context: str | None = None,
    structured_context: dict[str, object] | None = None,
) -> WorkflowResult[KnowledgeSyncReport]:
    error_subject = str(subject or "").strip()
    try:
        normalized_subject, normalized_markdown, normalized_revision = _normalize_docs_sync_inputs(
            subject=subject,
            markdown=markdown,
            build_revision_no=build_revision_no,
        )
        error_subject = normalized_subject
        context = WorkflowContext(
            workflow_name="digest.kg_doc_sync",
            subject=normalized_subject,
            metadata={
                "build_session_id": build_session_id or "",
                "lane": "kg_doc_sync",
                "langsmith_run_name": RUN_NAME_KG_DOC_SYNC,
                "build_revision_no": normalized_revision,
            },
        )
        result = await run_state_graph(
            workflow_name="digest.kg_doc_sync",
            graph_builder=lambda: build_docs_sync_graph(context=context),
            initial_state=create_docs_sync_initial_state(
                subject=normalized_subject,
                markdown=normalized_markdown,
                build_revision_no=normalized_revision,
                build_session_id=build_session_id,
                subject_context=subject_context,
                structured_context=structured_context,
            ),
            context=context,
        )
        if result.failed:
            return err_result(
                "digest_graph_docs_sync_failed",
                result.error.detail,
                metadata={"subject": normalized_subject},
            )

        final_state: DocsSyncState = result.require_value()
        state_error = str(final_state.get("error") or "").strip()
        if state_error:
            return err_result(
                "digest_graph_docs_sync_failed",
                state_error,
                metadata={"subject": normalized_subject},
            )
        report = final_state.get("report")
        if report is None:
            return err_result(
                "digest_graph_docs_sync_failed",
                "docs_sync_report_missing",
                metadata={"subject": normalized_subject},
            )
        return ok_result(report)
    except ValueError as exc:
        return err_result(
            "digest_graph_docs_sync_invalid_markdown",
            str(exc),
            metadata={"subject": error_subject},
        )
    except Exception as exc:
        return err_result(
            "digest_graph_docs_sync_failed",
            str(exc),
            metadata={"subject": error_subject},
        )


def get_langgraph_dev_kg_doc_sync_graph() -> StateGraph:
    return build_docs_sync_graph(context=create_langgraph_dev_context("digest.kg_doc_sync.langgraph_dev"))


__all__ = [
    "RUN_NAME_KG_DOC_SYNC",
    "build_docs_sync_graph",
    "create_docs_sync_initial_state",
    "get_langgraph_dev_kg_doc_sync_graph",
    "run_graph_docs_sync_workflow",
]
