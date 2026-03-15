"""Chat streaming and chat history routes."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import StreamingResponse
from sqlmodel import Session

from app.api.docs import build_error_responses
from app.api.deps import get_db, validate_subject, PaginationParams
from app.repositories.chat_repo import list_messages_by_subject
from app.schemas.chat import ChatHistoryResponse, ChatRequest
from app.services.chat_service import chat_stream
from app.services.presenters import to_chat_history_response

router = APIRouter(prefix="/api/v1/subjects", tags=["chat"])


@router.post(
    "/{subject}/chat",
    summary="发起流式对话",
    description=(
        "结合学科资料、检索结果、近期对话、错题和薄弱项生成 SSE 流式回答。"
        "响应会依次发送 `token`、`done` 或 `error` 事件。"
    ),
    response_description="SSE 事件流。",
    responses={
        200: {"description": "SSE 事件流，事件类型包括 token / done / error。"},
        **build_error_responses([400, 500, 502, 503]),
    },
)
async def chat(
    request: Request,
    body: ChatRequest = Body(..., description="对话请求体。"),
    subject: str = Depends(validate_subject),
    session: Session = Depends(get_db),
) -> StreamingResponse:
    """Stream an assistant response for the current subject using SSE."""
    generator = chat_stream(
        request,
        session,
        subject=subject,
        question=body.question,
        selected_context=body.selected_context,
        source_chunk_id=body.source_chunk_id,
    )
    return StreamingResponse(generator, media_type="text/event-stream")


@router.post(
    "/{subject}/chat/history",
    response_model=ChatHistoryResponse,
    summary="获取对话历史",
    description="分页返回指定学科的历史聊天消息列表。",
    response_description="聊天记录分页列表。",
    responses=build_error_responses([400, 500]),
)
async def get_chat_history(
    body: PaginationParams = Body(..., description="分页参数。"),
    subject: str = Depends(validate_subject),
    session: Session = Depends(get_db),
) -> ChatHistoryResponse:
    """Return paginated chat history for one subject."""
    items, total = list_messages_by_subject(
        session, subject, limit=body.limit, offset=body.offset
    )
    return to_chat_history_response(items, total)
