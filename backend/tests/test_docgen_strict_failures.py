from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.shared.infra.execution import TracedExecutionContext
from app.workflows.digest.docgen.runtime.assets import _MermaidPlaceholderRuntime
from app.workflows.digest.docgen.runtime.writer import DocGenWriterRuntime


def test_docgen_writer_runtime_raises_when_main_llm_fails() -> None:
    async def failing_llm(*_args, **_kwargs) -> str:
        raise RuntimeError("writer llm failed")

    runtime = DocGenWriterRuntime(
        TracedExecutionContext(
            subject="demo",
            llm_caller=failing_llm,
        )
    )

    with pytest.raises(RuntimeError, match="writer llm failed"):
        asyncio.run(
            runtime.execute(
                chapter_plan={
                    "chapter_index": 1,
                    "title": "Partial Derivatives",
                    "objective": "Explain the core idea",
                    "required_elements": ["intuition"],
                },
                dense_context="partial derivatives describe local rate of change",
                tone="encouraging",
                digest_mode="systematic",
            )
        )


def test_mermaid_placeholder_runtime_raises_when_llm_fails() -> None:
    async def failing_llm(*_args, **_kwargs) -> str:
        raise RuntimeError("mermaid llm failed")

    runtime = _MermaidPlaceholderRuntime(
        TracedExecutionContext(
            subject="demo",
            llm_caller=failing_llm,
        )
    )

    with patch(
        "app.workflows.digest.docgen.runtime.assets.get_settings",
        return_value=SimpleNamespace(
            mermaid_generation_enabled=True,
            mermaid_generation_model="",
        ),
    ):
        with pytest.raises(RuntimeError, match="mermaid llm failed"):
            asyncio.run(
                runtime.execute(
                    topic="Partial Derivatives",
                    context="Explain the geometric intuition",
                )
            )
