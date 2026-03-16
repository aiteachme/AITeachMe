"""Digest workflow that builds cleaned markdown, outlines, chunks, and embeddings for one document."""

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
    id: int
    title: str
    level: int
    parent_id: int | None


class ChunkState(TypedDict):
    title: str
    level: int
    header_path: str
    chunk_index: int
    content: str


class DigestState(TypedDict):
    document_id: int
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
    node_name: str
    success_stage: str
    action: DigestAction


def _serialize_outline_nodes(db_nodes: list[object]) -> list[OutlineNodeState]:
    serialized: list[OutlineNodeState] = []
    for node in db_nodes:
        node_id = getattr(node, "id", None)
        if node_id is None:
            raise ValueError("DocumentOutlineNode.id is unexpectedly None after insertion")
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


def _update_pipeline_stage(session: Session, document_id: int, stage: str) -> None:
    from app.repositories.knowledge_repo import update_document_stage

    updated = update_document_stage(session, document_id, stage)
    if updated is None:
        raise ValueError(f"Document.id={document_id} does not exist, cannot set stage to {stage}")


def _mark_step_success(state: DigestState, step: DigestStep) -> None:
    state["current_stage"] = step.success_stage
    state["error"] = None
    state["error_stage"] = None


def _mark_step_failure(state: DigestState, step_name: str, exc: Exception) -> None:
    state["error"] = str(exc)
    state["error_stage"] = step_name


async def _execute_step(state: DigestState, step: DigestStep) -> DigestState:
    from app.core.database import get_session

    try:
        with get_session() as session:
            result = step.action(state, session)
            if inspect.isawaitable(result):
                await result
            _update_pipeline_stage(session, state["document_id"], step.success_stage)

        _mark_step_success(state, step)
        logger.info(
            "digest_step_done",
            document_id=state["document_id"],
            step=step.node_name,
            current_stage=step.success_stage,
        )
    except Exception as exc:
        _mark_step_failure(state, step.node_name, exc)
        logger.error(
            "digest_step_failed",
            document_id=state["document_id"],
            step=step.node_name,
            error=str(exc),
        )
    return state


def _clean_action(state: DigestState, session: Session) -> None:
    del session
    from app.agents.digest.cleaner import clean_markdown

    state["cleaned_markdown"] = clean_markdown(state["raw_markdown"])


async def _outline_action(state: DigestState, session: Session) -> None:
    from app.agents.digest.outliner import bulk_insert_outline, extract_outline

    outline_items = await extract_outline(state["cleaned_markdown"])
    db_nodes = bulk_insert_outline(session, outline_items, state["document_id"])
    state["outline_nodes"] = _serialize_outline_nodes(db_nodes)


def _store_document_action(state: DigestState, session: Session) -> None:
    from app.repositories.knowledge_repo import update_document_content

    updated = update_document_content(session, state["document_id"], state["cleaned_markdown"])
    if updated is None:
        raise ValueError(f"Document.id={state['document_id']} does not exist, cannot save markdown")


def _chunk_action(state: DigestState, session: Session) -> None:
    del session
    from app.agents.digest.chunker import chunk_markdown

    state["chunks"] = _serialize_chunks(chunk_markdown(state["cleaned_markdown"]))


async def _embed_action(state: DigestState, session: Session) -> None:
    from app.agents.digest.embedder import embed_chunks, save_chunks_and_embeddings

    chunk_data_list = _deserialize_chunks(state)
    embeddings = await embed_chunks(chunk_data_list)
    save_chunks_and_embeddings(session, state["document_id"], chunk_data_list, embeddings)
    state["embeddings"] = embeddings


_DIGEST_STEPS: tuple[DigestStep, ...] = (
    DigestStep("clean", PipelineStage.CLEANED, _clean_action),
    DigestStep("outline", PipelineStage.OUTLINED, _outline_action),
    DigestStep("store_document", PipelineStage.STORED, _store_document_action),
    DigestStep("chunk", PipelineStage.CHUNKED, _chunk_action),
    DigestStep("embed", PipelineStage.EMBEDDED, _embed_action),
)

_STAGE_TO_ENTRY_NODE: dict[str, str | None] = {
    PipelineStage.PENDING: "clean",
    PipelineStage.CLEANED: "outline",
    PipelineStage.OUTLINED: "store_document",
    PipelineStage.STORED: "chunk",
    PipelineStage.CHUNKED: "embed",
    PipelineStage.EMBEDDED: None,
    PipelineStage.FAILED: "clean",
}


def resolve_entry_node(current_stage: str) -> str | None:
    return _STAGE_TO_ENTRY_NODE.get(current_stage, "clean")


async def error_node(state: DigestState) -> DigestState:
    from app.core.database import get_session

    logger.error(
        "digest_pipeline_error",
        document_id=state["document_id"],
        error_stage=state.get("error_stage"),
        error=state.get("error"),
    )

    try:
        with get_session() as session:
            _update_pipeline_stage(session, state["document_id"], PipelineStage.FAILED)
        state["current_stage"] = PipelineStage.FAILED
    except Exception as exc:
        logger.error("digest_error_node_db_fail", document_id=state["document_id"], error=str(exc))

    return state


def _route_on_error(state: DigestState) -> Literal["error", "continue"]:
    return "error" if state.get("error") else "continue"


def _make_step_node(step: DigestStep) -> Callable[[DigestState], Awaitable[DigestState]]:
    async def _node(state: DigestState) -> DigestState:
        return await _execute_step(state, step)

    return _node


def _build_workflow(entry_node: str) -> object:
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


async def run_digest_workflow(
    document_id: int,
    subject: str,
    raw_markdown: str,
    current_stage: str = PipelineStage.PENDING,
) -> DigestState:
    entry_node = resolve_entry_node(current_stage)
    initial_state: DigestState = {
        "document_id": document_id,
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
        document_id=document_id,
        subject=subject,
        current_stage=current_stage,
        entry_node=entry_node,
    )

    if entry_node is None:
        logger.info("digest_workflow_skip", document_id=document_id, reason="already_embedded")
        return initial_state

    graph = _build_workflow(entry_node)
    result = await graph.ainvoke(initial_state)

    if result.get("error"):
        logger.error(
            "digest_workflow_failed",
            document_id=document_id,
            error_stage=result.get("error_stage"),
            error=result.get("error"),
        )
    else:
        logger.info(
            "digest_workflow_complete",
            document_id=document_id,
            final_stage=result["current_stage"],
        )

    return result
