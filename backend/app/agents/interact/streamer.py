"""聊天流式输出工具。"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator

from fastapi import Request

from app.core.llm import acompletion_stream
from app.schemas.llm import ChatMessage


def format_sse_event(event: str, data: dict) -> str:
    """格式化 SSE 事件。"""

    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def stream_llm_events(
    request: Request,
    messages: list[ChatMessage],
    collected_tokens: list[str],
) -> AsyncGenerator[str, None]:
    """把 LLM 流式结果转换为 SSE token 事件。"""

    stream = acompletion_stream(messages)
    async for token in stream:
        if await request.is_disconnected():
            await stream.aclose()
            return
        collected_tokens.append(token)
        yield format_sse_event("token", {"content": token})
