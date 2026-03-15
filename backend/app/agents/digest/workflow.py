"""
Digest 引擎的 LangGraph 工作流定义。

本模块保留现有的流水线阶段与恢复语义：

- `pending -> cleaned -> outlined -> stored -> chunked -> embedded`
- `failed` 会从 `clean` 节点重新开始
- 每个步骤负责更新内存状态，数据库中的 `pipeline_stage` 由统一辅助函数写回

与旧实现相比，这里将流程改为声明式步骤注册，以便更清楚地表达：

- 每个步骤对应哪个图节点
- 每个步骤成功后推进到哪个阶段
- 每个步骤失败时如何统一记录错误和写回 `failed`
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Awaitable, Callable, Literal, TypedDict

import structlog
from langgraph.graph import END, StateGraph
from sqlmodel import Session

from app.repositories.models import PipelineStage

logger = structlog.get_logger()


class OutlineNodeState(TypedDict):
    """Serialized outline node state stored between workflow steps."""

    id: int
    title: str
    level: int
    parent_id: int | None


class ChunkState(TypedDict):
    """Serialized chunk state stored between workflow steps."""

    title: str
    level: int
    header_path: str
    chunk_index: int
    content: str


class DigestState(TypedDict):
    """Mutable workflow state passed between LangGraph digest nodes."""

    knowledge_id: int
    subject: str
    raw_markdown: str
    cleaned_markdown: str
    outline_nodes: list[OutlineNodeState]
    chunks: list[ChunkState]
    embeddings: list[list[float]]
    current_stage: str
    error: str | None
    error_stage: str | None


DigestAction = Callable[[DigestState, Session], Awaitable[None] | None]


@dataclass(frozen=True)
class DigestStep:
    """Declarative description of a single digest pipeline step."""

    node_name: str
    success_stage: str
    action: DigestAction


def _serialize_outline_nodes(db_nodes: list[object]) -> list[OutlineNodeState]:
    """Convert inserted outline ORM nodes into JSON-serializable workflow state."""

    serialized: list[OutlineNodeState] = []
    for node in db_nodes:
        node_id = getattr(node, "id", None)
        if node_id is None:
            raise ValueError("KnowledgeGraphNode.id is unexpectedly None after insertion")
        serialized.append(
            {
                "id": node_id,
                "title": node.title,
                "level": node.level,
                "parent_id": node.parent_id,
            }
        )
    return serialized


def _serialize_chunks(chunks: list[object]) -> list[ChunkState]:
    """Convert chunk dataclasses into JSON-serializable workflow state."""

    return [
        {
            "title": chunk.title,
            "level": chunk.level,
            "header_path": chunk.header_path,
            "chunk_index": chunk.chunk_index,
            "content": chunk.content,
        }
        for chunk in chunks
    ]


def _deserialize_chunks(state: DigestState) -> list[object]:
    """Rebuild `ChunkData` objects from serialized workflow state."""

    from app.agents.digest.chunker import ChunkData

    return [
        ChunkData(
            title=chunk["title"],
            level=chunk["level"],
            header_path=chunk["header_path"],
            chunk_index=chunk["chunk_index"],
            content=chunk["content"],
        )
        for chunk in state["chunks"]
    ]


def _update_pipeline_stage(session: Session, knowledge_id: int, stage: str) -> None:
    """Persist the digest stage transition for one knowledge document."""

    from app.repositories.knowledge_repo import update_pipeline_stage

    updated = update_pipeline_stage(session, knowledge_id, stage)
    if updated is None:
        raise ValueError(f"Knowledge.id={knowledge_id} 不存在，无法更新流水线阶段为 {stage}")


def _mark_step_success(state: DigestState, step: DigestStep) -> None:
    """Update in-memory workflow state after one successful pipeline step."""

    state["current_stage"] = step.success_stage
    state["error"] = None
    state["error_stage"] = None


def _mark_step_failure(state: DigestState, step_name: str, exc: Exception) -> None:
    """Store unified error information in workflow state."""

    state["error"] = str(exc)
    state["error_stage"] = step_name


async def _execute_step(state: DigestState, step: DigestStep) -> DigestState:
    """Run one digest step, persist its stage on success, and capture failures uniformly."""

    from app.core.database import get_session

    try:
        with get_session() as session:
            result = step.action(state, session)
            if inspect.isawaitable(result):
                await result
            _update_pipeline_stage(session, state["knowledge_id"], step.success_stage)

        _mark_step_success(state, step)
        logger.info(
            "digest_step_done",
            knowledge_id=state["knowledge_id"],
            step=step.node_name,
            current_stage=step.success_stage,
        )
    except Exception as exc:
        _mark_step_failure(state, step.node_name, exc)
        logger.error(
            "digest_step_failed",
            knowledge_id=state["knowledge_id"],
            step=step.node_name,
            error=str(exc),
        )
    return state


def _clean_action(state: DigestState, session: Session) -> None:
    """Clean raw markdown and store the normalized result in workflow state."""

    del session
    from app.agents.digest.cleaner import clean_markdown

    state["cleaned_markdown"] = clean_markdown(state["raw_markdown"])


async def _outline_action(state: DigestState, session: Session) -> None:
    """Extract outline nodes with the LLM and persist the knowledge graph tree."""

    from app.agents.digest.outliner import bulk_insert_outline, extract_outline

    outline_items = await extract_outline(state["cleaned_markdown"])
    db_nodes = bulk_insert_outline(session, outline_items, state["knowledge_id"])
    state["outline_nodes"] = _serialize_outline_nodes(db_nodes)


def _store_knowledge_action(state: DigestState, session: Session) -> None:
    """Persist cleaned markdown into the `Knowledge` record."""

    from app.repositories.knowledge_repo import update_knowledge_content

    updated = update_knowledge_content(session, state["knowledge_id"], state["cleaned_markdown"])
    if updated is None:
        raise ValueError(f"Knowledge.id={state['knowledge_id']} 不存在，无法写入 Markdown 内容")


def _chunk_action(state: DigestState, session: Session) -> None:
    """Split cleaned markdown into title-based chunks and store them in workflow state."""

    del session
    from app.agents.digest.chunker import chunk_markdown

    state["chunks"] = _serialize_chunks(chunk_markdown(state["cleaned_markdown"]))


async def _embed_action(state: DigestState, session: Session) -> None:
    """Generate embeddings for chunks and persist both chunk rows and vector rows."""

    from app.agents.digest.embedder import embed_chunks, save_chunks_and_embeddings

    chunk_data_list = _deserialize_chunks(state)
    embeddings = await embed_chunks(chunk_data_list)
    save_chunks_and_embeddings(session, state["knowledge_id"], chunk_data_list, embeddings)
    state["embeddings"] = embeddings


_DIGEST_STEPS: tuple[DigestStep, ...] = (
    DigestStep(node_name="clean", success_stage=PipelineStage.CLEANED, action=_clean_action),
    DigestStep(node_name="outline", success_stage=PipelineStage.OUTLINED, action=_outline_action),
    DigestStep(node_name="store_knowledge", success_stage=PipelineStage.STORED, action=_store_knowledge_action),
    DigestStep(node_name="chunk", success_stage=PipelineStage.CHUNKED, action=_chunk_action),
    DigestStep(node_name="embed", success_stage=PipelineStage.EMBEDDED, action=_embed_action),
)

_STEP_BY_NODE: dict[str, DigestStep] = {step.node_name: step for step in _DIGEST_STEPS}

_STAGE_TO_ENTRY_NODE: dict[str, str | None] = {
    PipelineStage.PENDING: "clean",
    PipelineStage.CLEANED: "outline",
    PipelineStage.OUTLINED: "store_knowledge",
    PipelineStage.STORED: "chunk",
    PipelineStage.CHUNKED: "embed",
    PipelineStage.EMBEDDED: None,
    PipelineStage.FAILED: "clean",
}


def resolve_entry_node(current_stage: str) -> str | None:
    """Resolve the next graph node to run for the given persisted pipeline stage."""

    return _STAGE_TO_ENTRY_NODE.get(current_stage, "clean")


def determine_entry_point(current_stage: str) -> str:
    """Backward-compatible helper returning the graph entry node name."""

    return resolve_entry_node(current_stage) or "clean"


async def error_node(state: DigestState) -> DigestState:
    """Persist a failed digest stage after any node error and return final state."""

    from app.core.database import get_session

    logger.error(
        "digest_pipeline_error",
        knowledge_id=state["knowledge_id"],
        error_stage=state.get("error_stage"),
        error=state.get("error"),
    )

    try:
        with get_session() as session:
            _update_pipeline_stage(session, state["knowledge_id"], PipelineStage.FAILED)
        state["current_stage"] = PipelineStage.FAILED
    except Exception as exc:
        logger.error("digest_error_node_db_fail", knowledge_id=state["knowledge_id"], error=str(exc))

    return state


def _route_on_error(state: DigestState) -> Literal["error", "continue"]:
    """Route to `error` when any previous step stored an error in workflow state."""

    return "error" if state.get("error") else "continue"


def _make_step_node(step: DigestStep) -> Callable[[DigestState], Awaitable[DigestState]]:
    """Create a LangGraph-compatible node function for a declarative digest step."""

    async def _node(state: DigestState) -> DigestState:
        return await _execute_step(state, step)

    return _node


def _build_workflow(entry_node: str) -> object:
    """Compile a digest workflow starting from the requested node."""

    workflow = StateGraph(DigestState)
    workflow.add_node("error", error_node)

    node_sequence = [step.node_name for step in _DIGEST_STEPS]
    start_index = node_sequence.index(entry_node)
    active_steps = _DIGEST_STEPS[start_index:]

    for step in active_steps:
        workflow.add_node(step.node_name, _make_step_node(step))

    workflow.set_entry_point(active_steps[0].node_name)

    for index, step in enumerate(active_steps):
        next_node = END if index == len(active_steps) - 1 else active_steps[index + 1].node_name
        workflow.add_conditional_edges(
            step.node_name,
            _route_on_error,
            {"error": "error", "continue": next_node},
        )

    workflow.add_edge("error", END)
    return workflow.compile()


def build_digest_workflow() -> object:
    """Build the full digest workflow from the initial `clean` node."""

    return _build_workflow("clean")


def _build_partial_workflow(entry: str) -> object:
    """Build a digest subgraph beginning at the requested resume node."""

    return _build_workflow(entry)


async def run_digest_workflow(
    knowledge_id: int,
    subject: str,
    raw_markdown: str,
    current_stage: str = PipelineStage.PENDING,
) -> DigestState:
    """Run the digest workflow and support resuming from any persisted stage.

    Args:
        knowledge_id: Knowledge 记录 ID。
        subject: 学科标识。
        raw_markdown: 原始 Markdown 文本；恢复时也可传入已经清洗过的文本。
        current_stage: 当前数据库中的 digest 阶段。

    Returns:
        最终的 `DigestState`，包含阶段信息、序列化切块结果和错误上下文。
    """

    entry_node = resolve_entry_node(current_stage)
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

    logger.info(
        "digest_workflow_start",
        knowledge_id=knowledge_id,
        subject=subject,
        current_stage=current_stage,
        entry_node=entry_node,
    )

    if entry_node is None:
        logger.info("digest_workflow_skip", knowledge_id=knowledge_id, reason="already_embedded")
        return initial_state

    graph = build_digest_workflow() if entry_node == "clean" else _build_partial_workflow(entry_node)
    result = await graph.ainvoke(initial_state)

    if result.get("error"):
        logger.error(
            "digest_workflow_failed",
            knowledge_id=knowledge_id,
            error_stage=result.get("error_stage"),
            error=result.get("error"),
        )
    else:
        logger.info("digest_workflow_complete", knowledge_id=knowledge_id, final_stage=result["current_stage"])

    return result
