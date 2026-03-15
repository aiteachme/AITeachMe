"""
对话端点

POST /api/v1/subjects/{subject}/chat — SSE 流式对话
GET  /api/v1/subjects/{subject}/chat/history — 分页对话历史

需求：8.1, 8.4, 8.8
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlmodel import Session

from app.api.deps import get_db, validate_subject, PaginationParams
from app.repositories.chat_repo import list_messages_by_subject
from app.schemas.chat import (
    ChatRequest,
    ChatMessageItem,
    ChatHistoryResponse,
)
from app.services.chat_service import chat_stream

router = APIRouter(prefix="/api/v1/subjects", tags=["chat"])


@router.post("/{subject}/chat")
async def chat(
    request: Request,
    body: ChatRequest,
    subject: str = Depends(validate_subject),
    session: Session = Depends(get_db),
) -> StreamingResponse:
    """发送提问，通过 SSE 流式返回回复。"""
    generator = chat_stream(
        request,
        session,
        subject=subject,
        question=body.question,
        selected_context=body.selected_context,
        source_chunk_id=body.source_chunk_id,
    )
    return StreamingResponse(generator, media_type="text/event-stream")


@router.get("/{subject}/chat/history", response_model=ChatHistoryResponse)
async def get_chat_history(
    subject: str = Depends(validate_subject),
    pagination: PaginationParams = Depends(),
    session: Session = Depends(get_db),
) -> ChatHistoryResponse:
    """分页对话历史。"""
    items, total = list_messages_by_subject(
        session, subject, limit=pagination.limit, offset=pagination.offset
    )
    return ChatHistoryResponse(
        items=[
            ChatMessageItem(
                id=m.id,  # type: ignore[arg-type]
                turn_id=m.turn_id,
                role=m.role,
                content=m.content,
                contexts=m.contexts,
                created_at=m.created_at,
            )
            for m in items
        ],
        total=total,
    )
