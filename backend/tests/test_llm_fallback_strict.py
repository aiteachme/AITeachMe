from __future__ import annotations

import asyncio
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import BaseModel

from app.shared.infra.llm_support.fallback import acompletion_with_fallback
from app.shared.infra.llm_support.routing import TaskType


class _StructuredPayload(BaseModel):
    value: str


def _fake_trace_context() -> SimpleNamespace:
    return SimpleNamespace(
        subject="demo",
        build_session_id="build-1",
        workflow="digest.docgen",
        lane="docgen",
        node="writer",
    )


def test_acompletion_with_fallback_text_raises_after_single_primary_call() -> None:
    failing_completion = AsyncMock(side_effect=RuntimeError("text llm failed"))

    with patch(
        "app.shared.infra.observability.get_llm_trace_context",
        return_value=_fake_trace_context(),
    ), patch(
        "app.shared.infra.observability.langsmith_tracing_scope",
        side_effect=lambda **_kwargs: nullcontext(),
    ), patch(
        "app.shared.infra.llm_support.fallback.acompletion",
        new=failing_completion,
    ):
        with pytest.raises(RuntimeError, match="text llm failed"):
            asyncio.run(
                acompletion_with_fallback(
                    [{"role": "user", "content": "hello"}],
                    task_type=TaskType.DOCGEN,
                )
            )

    assert failing_completion.await_count == 1


def test_acompletion_with_fallback_structured_raises_after_single_primary_call() -> None:
    failing_structured_completion = AsyncMock(side_effect=RuntimeError("structured llm failed"))

    with patch(
        "app.shared.infra.observability.get_llm_trace_context",
        return_value=_fake_trace_context(),
    ), patch(
        "app.shared.infra.observability.langsmith_tracing_scope",
        side_effect=lambda **_kwargs: nullcontext(),
    ), patch(
        "app.shared.infra.llm_support.fallback.acompletion_structured",
        new=failing_structured_completion,
    ):
        with pytest.raises(RuntimeError, match="structured llm failed"):
            asyncio.run(
                acompletion_with_fallback(
                    [{"role": "user", "content": "hello"}],
                    task_type=TaskType.REASONING,
                    response_model=_StructuredPayload,
                )
            )

    assert failing_structured_completion.await_count == 1
