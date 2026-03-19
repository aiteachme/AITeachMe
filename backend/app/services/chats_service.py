"""聊天服务层。"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import structlog
from fastapi import Request
from sqlmodel import Session

from app.agents.interact.context_builder import build_chat_messages
from app.agents.interact.retriever import retrieve
from app.agents.interact.streamer import format_sse_event, stream_llm_events
from app.core.config import get_settings
from app.models import ChatMessage
from app.repositories.chats_repo import (
    clear_messages_by_subject,
    create_message_pair,
    get_recent_turns,
    list_messages_by_subject,
)
from app.repositories.exams_repo import list_mistakes_by_subject
from app.repositories.knowledge_repo import vector_search
from app.repositories.profile_repo import get_weak_points
from app.schemas.chats import ChatClearData, ChatMessageItem
from app.schemas.common import PaginatedData, build_paginated_data
from app.services.presenters import mastery_to_text, require_id

logger = structlog.get_logger()


def _serialize_contexts(results: list[object]) -> list[dict] | None:
    if not results:
        return None
    payload: list[dict] = []
    for result in results:
        payload.append(
            {
                "chunk_id": result.chunk_id,
                "title": result.title,
                "header_path": result.header_path,
                "score": round(result.score, 4),
            }
        )
    return payload


def list_chat_history(
    session: Session,
    *,
    subject: str,
    page: int,
    size: int,
) -> PaginatedData[ChatMessageItem]:
    """分页读取聊天记录。"""

    items, total = list_messages_by_subject(
        session,
        subject,
        limit=size,
        offset=(page - 1) * size,
    )
    return build_paginated_data(
        items=[_to_chat_message_item(item) for item in items],
        page=page,
        size=size,
        total=total,
    )


def clear_chat_history(session: Session, *, subject: str) -> ChatClearData:
    """清空聊天记录。"""

    deleted_count = clear_messages_by_subject(session, subject)
    return ChatClearData(cleared=True, deleted_count=deleted_count)


def _to_chat_message_item(message: ChatMessage) -> ChatMessageItem:
    return ChatMessageItem(
        id=require_id(message.id, "ChatMessage.id"),
        turn_id=message.turn_id,
        role=message.role,
        content=message.content,
        contexts=message.contexts,
        created_at=message.created_at,
    )


async def chat_stream(
    request: Request,
    session: Session,
    *,
    subject: str,
    question: str,
    selected_context: str | None = None,
    source_chunk_id: int | None = None,
) -> AsyncGenerator[str, None]:
    """执行聊天检索与流式回答。"""

    settings = get_settings()
    retrieval_results = await retrieve(
        query=question,
        subject=subject,
        top_k=settings.rag_top_k,
        similarity_threshold=settings.rag_similarity_threshold,
        search_func=lambda query_embedding, query_subject, top_k: [
            {
                "chunk_id": require_id(result.chunk.id, "DocumentChunk.id"),
                "document_id": result.chunk.document_id,
                "title": result.chunk.title,
                "header_path": result.chunk.header_path,
                "content": result.chunk.content,
                "score": result.score,
            }
            for result in vector_search(
                session,
                query_embedding,
                query_subject,
                top_k=top_k,
            )
        ],
    )

    recent_messages = [
        {"role": item.role, "content": item.content}
        for item in get_recent_turns(session, subject, n_turns=settings.chat_history_turns)
    ]
    weak_points = [
        {
            "knowledge_point": item.knowledge_point,
            "mastery_text": mastery_to_text(item.mastery),
        }
        for item in get_weak_points(session, subject, limit=10)
    ]
    recent_mistakes, _ = list_mistakes_by_subject(session, subject, limit=5, offset=0)
    messages = build_chat_messages(
        subject=subject,
        retrieval_results=retrieval_results,
        recent_messages=recent_messages,
        weak_points=weak_points,
        recent_mistakes=recent_mistakes,
        question=question,
        selected_context=selected_context,
        source_chunk_id=source_chunk_id,
    )

    collected_tokens: list[str] = []
    try:
        async for event in stream_llm_events(request, messages, collected_tokens):
            yield event

        if await request.is_disconnected():
            return

        full_response = "".join(collected_tokens)
        contexts = _serialize_contexts(retrieval_results)
        _, assistant_message = create_message_pair(
            session,
            subject=subject,
            user_content=question,
            assistant_content=full_response,
            contexts=contexts,
        )
        yield format_sse_event(
            "done",
            {
                "turn_id": assistant_message.turn_id,
                "contexts": contexts,
            },
        )
    except Exception as exc:
        logger.error("chat_stream_failed", subject=subject, error=str(exc))
        yield format_sse_event(
            "error",
            {"detail": str(exc), "error_code": "STREAM_ERROR"},
        )
