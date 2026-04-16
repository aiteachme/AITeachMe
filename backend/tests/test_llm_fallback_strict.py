from __future__ import annotations

import asyncio
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import BaseModel

from app.shared.infra.llm_support.common import build_completion_context
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
        "app.shared.infra.observability.trace.get_llm_trace_context",
        return_value=_fake_trace_context(),
    ), patch(
        "app.shared.infra.observability.trace.langsmith_tracing_scope",
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
        "app.shared.infra.observability.trace.get_llm_trace_context",
        return_value=_fake_trace_context(),
    ), patch(
        "app.shared.infra.observability.trace.langsmith_tracing_scope",
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


def test_acompletion_with_fallback_passes_model_selector_to_text_completion() -> None:
    successful_completion = AsyncMock(return_value="ok")

    with patch(
        "app.shared.infra.observability.trace.get_llm_trace_context",
        return_value=_fake_trace_context(),
    ), patch(
        "app.shared.infra.observability.trace.langsmith_tracing_scope",
        side_effect=lambda **_kwargs: nullcontext(),
    ), patch(
        "app.shared.infra.llm_support.fallback.acompletion",
        new=successful_completion,
    ):
        result = asyncio.run(
            acompletion_with_fallback(
                [{"role": "user", "content": "hello"}],
                task_type=TaskType.DOCGEN_LIGHT,
                model="reason",
            )
        )

    assert result == "ok"
    assert successful_completion.await_args.kwargs["model"] == "reason"


def test_build_completion_context_uses_reason_model_when_model_selected() -> None:
    fake_settings = SimpleNamespace(
        models=SimpleNamespace(
            primary="primary-model",
            reason="reason-model",
            light="light-model",
            extract=None,
            overrides={},
        ),
    )

    with patch("app.shared.infra.llm_support.common.get_settings", return_value=fake_settings), patch(
        "app.shared.infra.llm_support.common.get_env",
        return_value="test-key",
    ):
        context = build_completion_context(TaskType.DOCGEN_LIGHT, model="reason")

    assert context.model == "reason-model"


def test_settings_exposes_yaml_shaped_models() -> None:
    from app.shared.infra.settings import Settings

    settings = Settings(
        models={
            "primary": "primary-model",
            "reason": "reason-model",
            "light": "light-model",
            "extract": "extract-model",
            "embedding": "embedding-model",
        },
    )

    assert settings.models.primary == "primary-model"
    assert settings.models.reason == "reason-model"
    assert settings.models.light == "light-model"
    assert settings.models.fast == "light-model"
    assert settings.models.extract == "extract-model"
    assert settings.models.embedding == "embedding-model"


def test_settings_rejects_legacy_flat_model_fields() -> None:
    from pydantic import ValidationError

    from app.shared.infra.settings import Settings

    with pytest.raises(ValidationError):
        Settings(llm_model="legacy-model")
