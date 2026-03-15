"""
RAG 对话编排 �?协调 retriever �?context_builder �?streamer 流水�?
"""

from __future__ import annotations

from typing import AsyncGenerator

import structlog
from fastapi import Request
from sqlmodel import Session

from app.agents.interact.retriever import retrieve
from app.agents.interact.context_builder import build_system_prompt
from app.agents.interact.streamer import stream_chat_response
from app.schemas.llm import ChatMessage, USER

logger = structlog.get_logger()


async def chat_stream(
    request: Request,
    session: Session,
    *,
    subject: str,
    question: str,
    selected_context: str | None = None,
    source_chunk_id: int | None = None,
) -> AsyncGenerator[str, None]:
    """
    RAG 对话完整流水线：检�?�?构建提示�?�?流式生成�?

    Returns:
        SSE 事件的异步生成器
    """
    # 1. 向量检�?
    retrieval_results = await retrieve(session, question, subject)

    # 2. 构建系统提示�?+ 历史对话
    messages = build_system_prompt(
        session,
        subject,
        retrieval_results,
        selected_context=selected_context,
        source_chunk_id=source_chunk_id,
    )

    # 3. 追加用户当前问题
    messages.append(ChatMessage(role=USER, content=question))

    logger.info(
        "chat_pipeline_ready",
        subject=subject,
        num_retrieval_results=len(retrieval_results),
        num_messages=len(messages),
    )

    # 4. 流式生成并保�?
    async for event in stream_chat_response(
        request,
        session,
        messages,
        subject=subject,
        user_question=question,
        retrieval_results=retrieval_results,
    ):
        yield event
