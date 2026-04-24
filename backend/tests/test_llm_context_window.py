from __future__ import annotations

import asyncio

import pytest

from app.shared.infra.llm_support.context_window import ContextWindowManager
from app.shared.infra.llm_support.stream import _stream_chunks_with_timeout


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def test_context_window_does_not_invent_ellipsis_for_empty_sections() -> None:
    manager = ContextWindowManager()

    messages = manager.build_context(
        system_prompt="",
        retrieval_chunks=[],
        chat_history=[],
        user_query="",
    )

    assert messages == [
        {"role": "system", "content": ""},
        {"role": "user", "content": ""},
    ]
    assert manager.truncate_text("", 0) == ""
    assert manager.estimate_tokens("") == 0


class _SlowStream:
    def __init__(self) -> None:
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        await asyncio.sleep(0.05)
        return {"chunk": "late"}

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.anyio
async def test_stream_chunks_with_timeout_applies_to_each_upstream_read() -> None:
    stream = _SlowStream()
    chunks = _stream_chunks_with_timeout(stream, timeout_s=0.001)

    with pytest.raises(asyncio.TimeoutError):
        async for _chunk in chunks:
            pass
    assert stream.closed
