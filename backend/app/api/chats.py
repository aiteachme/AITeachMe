"""聊天接口。"""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Path, Request
from fastapi.responses import StreamingResponse
from sqlmodel import Session

from app.api.deps import get_db, normalize_subject_slug
from app.api.openapi import build_error_responses
from app.schemas.chats import ChatClearData, ChatClearRequest, ChatListRequest, ChatMessageItem, ChatSendRequest
from app.schemas.common import ApiResponse, PaginatedData, ok_response
from app.services.chats_service import chat_stream, clear_chat_history, list_chat_history
from app.services.subject_service import get_subject_record

router = APIRouter(prefix="/api/v1/subjects/{subject}/chats", tags=["chats"])


@router.post(
    "/send",
    summary="发送消息",
    description="保留原生 SSE 返回。",
    responses={200: {"description": "SSE 事件流。"}, **build_error_responses([400, 404, 500, 502, 503])},
)
async def send_chat(
    request: Request,
    subject: str = Path(...),
    body: ChatSendRequest = Body(...),
    session: Session = Depends(get_db),
) -> StreamingResponse:
    normalized_subject = normalize_subject_slug(subject)
    direct_mode = bool(body.source and body.source.strip())
    if not direct_mode:
        get_subject_record(session, normalized_subject)
    return StreamingResponse(
        chat_stream(
            request,
            session,
            subject=normalized_subject,
            question=body.question,
            source=body.source,
            selected_context=body.selected_context,
            source_chunk_id=body.source_chunk_id,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post(
    "/list",
    response_model=ApiResponse[PaginatedData[ChatMessageItem]],
    summary="聊天记录列表",
    responses=build_error_responses([400, 404, 500]),
)
async def list_chat_api(
    subject: str = Path(...),
    body: ChatListRequest = Body(default=ChatListRequest()),
    session: Session = Depends(get_db),
) -> ApiResponse[PaginatedData[ChatMessageItem]]:
    normalized_subject = normalize_subject_slug(subject)
    get_subject_record(session, normalized_subject)
    return ok_response(
        list_chat_history(
            session,
            subject=normalized_subject,
            page=body.page,
            size=body.size,
        )
    )


@router.post(
    "/clear",
    response_model=ApiResponse[ChatClearData],
    summary="清空聊天记录",
    responses=build_error_responses([400, 404, 500]),
)
async def clear_chat_api(
    subject: str = Path(...),
    _: ChatClearRequest = Body(default=ChatClearRequest()),
    session: Session = Depends(get_db),
) -> ApiResponse[ChatClearData]:
    normalized_subject = normalize_subject_slug(subject)
    get_subject_record(session, normalized_subject)
    return ok_response(clear_chat_history(session, subject=normalized_subject))
