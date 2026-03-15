"""
SSE 流式传输与断连检测 — Interact 引擎流式输出层

以 SSE 事件流式传输 LLM 响应：event: token、event: done、event: error。
通过 request.is_disconnected() 检测客户端断连，通过 aclose() 取消 LLM 生成。
完成后保存用户 + 助手 ChatMessage 对，共享 turn_id（UUID）；仅在助手消息上存储 contexts。
"""

from __future__ import annotations

import json
from typing import AsyncGenerator

import structlog
from fastapi import Request
from sqlmodel import Session

from app.core.llm import acompletion_stream
from app.repositories.chat_repo import create_message_pair
from app.agents.interact.retriever import RetrievalResult
from app.schemas.llm import ChatMessage

logger = structlog.get_logger()


def _sse_event(event: str, data: dict) -> str:
    """Format one SSE frame using the standard `event` + `data` shape."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def stream_chat_response(
    request: Request,
    session: Session,
    messages: list[ChatMessage],
    *,
    subject: str,
    user_question: str,
    retrieval_results: list[RetrievalResult],
) -> AsyncGenerator[str, None]:
    """
    Stream a chat response as SSE frames and persist the completed turn.

    Args:
        request: 当前 HTTP 请求对象，用于探测客户端断连。
        session: 数据库会话。
        messages: 发送给 LLM 的完整消息列表。
        subject: 当前学科标识。
        user_question: 用户原始问题。
        retrieval_results: 用于回答的检索结果列表。

    Yields:
        符合 SSE 协议的字符串事件。

    Raises:
        不直接向上抛出异常；遇到错误时会产出 `event: error` 帧。
    """
    collected_content: list[str] = []
    disconnected = False

    try:
        stream = acompletion_stream(messages)
        async for token in stream:
            # 检测客户端断连
            if await request.is_disconnected():
                disconnected = True
                logger.info("client_disconnected", subject=subject)
                await stream.aclose()
                break

            collected_content.append(token)
            yield _sse_event("token", {"content": token})

        if not disconnected:
            # 保存对话记录
            full_response = "".join(collected_content)
            contexts = _serialize_contexts_payload(retrieval_results)

            user_msg, assistant_msg = create_message_pair(
                session,
                subject=subject,
                user_content=user_question,
                assistant_content=full_response,
                contexts=contexts,
            )

            yield _sse_event("done", {
                "turn_id": assistant_msg.turn_id,
                "contexts": contexts,
            })

    except Exception as exc:
        logger.error("stream_error", subject=subject, error=str(exc))
        yield _sse_event("error", {
            "detail": str(exc),
            "error_code": "STREAM_ERROR",
        })


def _serialize_contexts_payload(
    results: list[RetrievalResult],
) -> list[dict] | None:
    """Convert retrieval results into the persisted `contexts` payload shape."""
    if not results:
        return None
    return [
        {
            "chunk_id": r.chunk_id,
            "title": r.title,
            "header_path": r.header_path,
            "score": round(r.score, 4),
        }
        for r in results
    ]
