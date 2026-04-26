"""SSE helpers for the interact workflow."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from contextlib import suppress

from fastapi import Request

from app.schemas.chats import ChatContextItem


def format_sse_event(event: str, data: dict) -> str:
    """Format one SSE payload."""

    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


class SSEEventEmitter:
    """In-process SSE event queue shared between workflow nodes and the response stream."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[str | None] = asyncio.Queue()
        self._closed = False

    async def emit_event(self, event: str, data: dict) -> None:
        await self._queue.put(format_sse_event(event, data))

    async def emit_token(self, content: str) -> None:
        await self.emit_event("token", {"content": content})

    async def emit_status(self, *, stage: str, detail: str, **extra: object) -> None:
        payload = {
            "stage": stage,
            "detail": detail,
            **extra,
        }
        await self.emit_event("status", payload)

    async def emit_error(self, *, detail: str, error_code: str) -> None:
        await self.emit_event("error", {"detail": detail, "error_code": error_code})

    async def emit_done(
        self,
        *,
        turn_id: str,
        contexts: list[ChatContextItem] | None,
        session_id: str | None = None,
        session_title: str | None = None,
    ) -> None:
        payload = {
            "turn_id": turn_id,
            "contexts": [item.model_dump() for item in contexts] if contexts else None,
        }
        if session_id:
            payload["session_id"] = session_id
        if session_title:
            payload["session_title"] = session_title
        await self.emit_event("done", payload)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._queue.put(None)

    async def stream(
        self,
        *,
        request: Request,
        workflow_task: asyncio.Task[None],
    ) -> AsyncGenerator[str, None]:
        """Yield queued SSE events until the workflow finishes or the client disconnects."""

        try:
            while True:
                if await request.is_disconnected():
                    workflow_task.cancel()
                    break
                try:
                    payload = await asyncio.wait_for(self._queue.get(), timeout=0.25)
                except asyncio.TimeoutError:
                    if workflow_task.done() and self._queue.empty():
                        break
                    continue
                if payload is None:
                    break
                yield payload
        finally:
            if not workflow_task.done():
                workflow_task.cancel()
            with suppress(asyncio.CancelledError):
                await workflow_task
