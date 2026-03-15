"""
LangGraph 状态机 — Digest 引擎工作流

连接节点：clean → outline → store_knowledge → chunk → embed
错误时条件路由到 error 节点。
支持断点恢复：根据当前 pipeline_stage 确定入口节点。

workflow 节点不自行重试 LLM，仅处理 success/fail；
LLM 重试统一由 core/llm.py 负责。
重试耗尽后设置 pipeline_stage 为 failed。
"""

from __future__ import annotations

from typing import TypedDict, Literal

from langgraph.graph import StateGraph, END
import structlog

from app.repositories.models import PipelineStage

logger = structlog.get_logger()


# ─── 状态定义 ───


class DigestState(TypedDict):
    knowledge_id: int
    subject: str
    raw_markdown: str
    cleaned_markdown: str
    outline_nodes: list[dict]
    chunks: list[dict]
    embeddings: list[list[float]]
    current_stage: str
    error: str | None
    error_stage: str | None


# ─── 阶段顺序与入口映射 ───

STAGE_ORDER = [
    PipelineStage.PENDING,
    PipelineStage.CLEANED,
    PipelineStage.OUTLINED,
    PipelineStage.STORED,
    PipelineStage.CHUNKED,
    PipelineStage.EMBEDDED,
]

_STAGE_TO_NODE: dict[str, str] = {
    PipelineStage.PENDING: "clean",
    PipelineStage.CLEANED: "outline",
    PipelineStage.OUTLINED: "store_knowledge",
    PipelineStage.STORED: "chunk",
    PipelineStage.CHUNKED: "embed",
    PipelineStage.FAILED: "clean",  # failed 从头重试
}


def determine_entry_point(current_stage: str) -> str:
    """根据当前 pipeline_stage 确定恢复入口节点名。"""
    return _STAGE_TO_NODE.get(current_stage, "clean")


# ─── 节点实现 ───


async def clean_node(state: DigestState) -> DigestState:
    """清洗 Markdown，更新 pipeline_stage=cleaned。"""
    from app.agents.digest.cleaner import clean_markdown
    from app.core.database import get_session
    from app.repositories.knowledge_repo import update_pipeline_stage

    try:
        cleaned = clean_markdown(state["raw_markdown"])
        state["cleaned_markdown"] = cleaned

        with get_session() as session:
            update_pipeline_stage(session, state["knowledge_id"], PipelineStage.CLEANED)

        state["current_stage"] = PipelineStage.CLEANED
        logger.info("digest_clean_done", knowledge_id=state["knowledge_id"])
    except Exception as exc:
        state["error"] = str(exc)
        state["error_stage"] = "clean"
        logger.error("digest_clean_failed", knowledge_id=state["knowledge_id"], error=str(exc))
    return state


async def outline_node(state: DigestState) -> DigestState:
    """LLM 提取大纲，写入 KnowledgeGraphNode，更新 pipeline_stage=outlined。"""
    from app.agents.digest.outliner import extract_outline, bulk_insert_outline
    from app.core.database import get_session
    from app.repositories.knowledge_repo import update_pipeline_stage

    try:
        outline_items = await extract_outline(state["cleaned_markdown"])

        with get_session() as session:
            db_nodes = bulk_insert_outline(session, outline_items, state["knowledge_id"])
            update_pipeline_stage(session, state["knowledge_id"], PipelineStage.OUTLINED)

        state["outline_nodes"] = [
            {"id": n.id, "title": n.title, "level": n.level, "parent_id": n.parent_id}
            for n in db_nodes
        ]
        state["current_stage"] = PipelineStage.OUTLINED
        logger.info("digest_outline_done", knowledge_id=state["knowledge_id"], num_nodes=len(db_nodes))
    except Exception as exc:
        state["error"] = str(exc)
        state["error_stage"] = "outline"
        logger.error("digest_outline_failed", knowledge_id=state["knowledge_id"], error=str(exc))
    return state


async def store_knowledge_node(state: DigestState) -> DigestState:
    """填充 Knowledge.markdown_content，更新 pipeline_stage=stored。"""
    from app.core.database import get_session
    from app.repositories.knowledge_repo import update_knowledge_content, update_pipeline_stage

    try:
        with get_session() as session:
            update_knowledge_content(session, state["knowledge_id"], state["cleaned_markdown"])
            update_pipeline_stage(session, state["knowledge_id"], PipelineStage.STORED)

        state["current_stage"] = PipelineStage.STORED
        logger.info("digest_store_done", knowledge_id=state["knowledge_id"])
    except Exception as exc:
        state["error"] = str(exc)
        state["error_stage"] = "store_knowledge"
        logger.error("digest_store_failed", knowledge_id=state["knowledge_id"], error=str(exc))
    return state


async def chunk_node(state: DigestState) -> DigestState:
    """按标题层级切块，更新 pipeline_stage=chunked。"""
    from app.agents.digest.chunker import chunk_markdown
    from app.core.database import get_session
    from app.repositories.knowledge_repo import update_pipeline_stage

    try:
        chunk_data_list = chunk_markdown(state["cleaned_markdown"])
        state["chunks"] = [
            {
                "title": c.title,
                "level": c.level,
                "header_path": c.header_path,
                "chunk_index": c.chunk_index,
                "content": c.content,
            }
            for c in chunk_data_list
        ]

        with get_session() as session:
            update_pipeline_stage(session, state["knowledge_id"], PipelineStage.CHUNKED)

        state["current_stage"] = PipelineStage.CHUNKED
        logger.info("digest_chunk_done", knowledge_id=state["knowledge_id"], num_chunks=len(chunk_data_list))
    except Exception as exc:
        state["error"] = str(exc)
        state["error_stage"] = "chunk"
        logger.error("digest_chunk_failed", knowledge_id=state["knowledge_id"], error=str(exc))
    return state


async def embed_node(state: DigestState) -> DigestState:
    """批量计算 embedding，写入 Chunk 表和 chunk_embeddings 虚表，更新 pipeline_stage=embedded。"""
    from app.agents.digest.chunker import ChunkData
    from app.agents.digest.embedder import embed_chunks, save_chunks_and_embeddings
    from app.core.database import get_session
    from app.repositories.knowledge_repo import update_pipeline_stage

    try:
        # 从 state 重建 ChunkData
        chunk_data_list = [
            ChunkData(
                title=c["title"],
                level=c["level"],
                header_path=c["header_path"],
                chunk_index=c["chunk_index"],
                content=c["content"],
            )
            for c in state["chunks"]
        ]

        embeddings = await embed_chunks(chunk_data_list)
        state["embeddings"] = embeddings

        with get_session() as session:
            save_chunks_and_embeddings(session, state["knowledge_id"], chunk_data_list, embeddings)
            update_pipeline_stage(session, state["knowledge_id"], PipelineStage.EMBEDDED)

        state["current_stage"] = PipelineStage.EMBEDDED
        logger.info("digest_embed_done", knowledge_id=state["knowledge_id"])
    except Exception as exc:
        state["error"] = str(exc)
        state["error_stage"] = "embed"
        logger.error("digest_embed_failed", knowledge_id=state["knowledge_id"], error=str(exc))
    return state


async def error_node(state: DigestState) -> DigestState:
    """错误处理节点：记录错误日志，将 pipeline_stage 更新为 failed。"""
    from app.core.database import get_session
    from app.repositories.knowledge_repo import update_pipeline_stage

    logger.error(
        "digest_pipeline_error",
        knowledge_id=state["knowledge_id"],
        error_stage=state.get("error_stage"),
        error=state.get("error"),
    )

    try:
        with get_session() as session:
            update_pipeline_stage(session, state["knowledge_id"], PipelineStage.FAILED)
    except Exception as exc:
        logger.error("digest_error_node_db_fail", error=str(exc))

    return state


# ─── 条件路由 ───


def _check_error(state: DigestState) -> Literal["error", "continue"]:
    """条件路由：检查 state 中是否有 error。"""
    if state.get("error"):
        return "error"
    return "continue"


# ─── 工作流构建 ───


def build_digest_workflow() -> StateGraph:
    """构建 Digest 引擎的 LangGraph 状态机工作流。"""
    workflow = StateGraph(DigestState)

    workflow.add_node("clean", clean_node)
    workflow.add_node("outline", outline_node)
    workflow.add_node("store_knowledge", store_knowledge_node)
    workflow.add_node("chunk", chunk_node)
    workflow.add_node("embed", embed_node)
    workflow.add_node("error", error_node)

    workflow.set_entry_point("clean")

    workflow.add_conditional_edges("clean", _check_error, {"error": "error", "continue": "outline"})
    workflow.add_conditional_edges("outline", _check_error, {"error": "error", "continue": "store_knowledge"})
    workflow.add_conditional_edges("store_knowledge", _check_error, {"error": "error", "continue": "chunk"})
    workflow.add_conditional_edges("chunk", _check_error, {"error": "error", "continue": "embed"})
    workflow.add_conditional_edges("embed", _check_error, {"error": "error", "continue": END})
    workflow.add_edge("error", END)

    return workflow.compile()


async def run_digest_workflow(
    knowledge_id: int,
    subject: str,
    raw_markdown: str,
    current_stage: str = PipelineStage.PENDING,
) -> DigestState:
    """运行 Digest 工作流，支持断点恢复。

    Args:
        knowledge_id: Knowledge 记录 ID。
        subject: 学科标识。
        raw_markdown: 原始 Markdown 文本（或已清洗的，取决于恢复阶段）。
        current_stage: 当前 pipeline_stage，用于断点恢复。

    Returns:
        最终的 DigestState。
    """
    entry = determine_entry_point(current_stage)
    logger.info(
        "digest_workflow_start",
        knowledge_id=knowledge_id,
        subject=subject,
        current_stage=current_stage,
        entry_node=entry,
    )

    initial_state: DigestState = {
        "knowledge_id": knowledge_id,
        "subject": subject,
        "raw_markdown": raw_markdown,
        "cleaned_markdown": raw_markdown if current_stage != PipelineStage.PENDING else "",
        "outline_nodes": [],
        "chunks": [],
        "embeddings": [],
        "current_stage": current_stage,
        "error": None,
        "error_stage": None,
    }

    # 构建工作流并执行
    # 对于断点恢复，我们需要跳过已完成的节点
    # LangGraph 的 entry_point 是固定的，所以通过节点内部检查 current_stage 来跳过
    # 更简单的方式：根据 entry 构建不同的子图
    if entry == "clean":
        graph = build_digest_workflow()
    else:
        # 构建从 entry 开始的子工作流
        graph = _build_partial_workflow(entry)

    result = await graph.ainvoke(initial_state)

    if result.get("error"):
        logger.error(
            "digest_workflow_failed",
            knowledge_id=knowledge_id,
            error_stage=result.get("error_stage"),
            error=result.get("error"),
        )
    else:
        logger.info("digest_workflow_complete", knowledge_id=knowledge_id)

    return result


def _build_partial_workflow(entry: str) -> StateGraph:
    """构建从指定节点开始的部分工作流（用于断点恢复）。"""
    node_sequence = ["clean", "outline", "store_knowledge", "chunk", "embed"]
    start_idx = node_sequence.index(entry) if entry in node_sequence else 0

    node_funcs = {
        "clean": clean_node,
        "outline": outline_node,
        "store_knowledge": store_knowledge_node,
        "chunk": chunk_node,
        "embed": embed_node,
    }

    workflow = StateGraph(DigestState)
    workflow.add_node("error", error_node)

    remaining = node_sequence[start_idx:]
    for name in remaining:
        workflow.add_node(name, node_funcs[name])

    workflow.set_entry_point(remaining[0])

    for i, name in enumerate(remaining):
        if i < len(remaining) - 1:
            next_name = remaining[i + 1]
            workflow.add_conditional_edges(name, _check_error, {"error": "error", "continue": next_name})
        else:
            workflow.add_conditional_edges(name, _check_error, {"error": "error", "continue": END})

    workflow.add_edge("error", END)

    return workflow.compile()
