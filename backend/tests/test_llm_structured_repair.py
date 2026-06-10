from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from app.shared.infra.llm_support import structured_calls
from app.shared.infra.llm_support.structured import _build_structured_fallback_messages
from app.shared.infra.llm_support.structured_calls import _structured_failure_feedback
from app.shared.infra.llm_support.routing import TaskType
from app.shared.infra.settings import set_system_settings_override


def teardown_function() -> None:
    set_system_settings_override({})


class _RepairChapter(BaseModel):
    title: str
    key_points: list[str]


class _RepairOutline(BaseModel):
    chapters: list[_RepairChapter]


def test_structured_repair_prompt_includes_invalid_response_context() -> None:
    messages = [{"role": "user", "content": "生成课程大纲"}]

    repaired = _build_structured_fallback_messages(
        _RepairOutline,
        messages,
        failure_reason="chapters.1 Input should be an object",
        invalid_response='{"chapters":[{"title":"函数","key_points":["定义"]},-1]}',
    )

    assert repaired[:-1] == messages
    repair_prompt = repaired[-1]["content"]
    assert "Previous structured output did not validate." in repair_prompt
    assert "chapters.1 Input should be an object" in repair_prompt
    assert '"chapters":[{"title":"函数","key_points":["定义"]},-1]' in repair_prompt
    assert "sentinel, null, primitive, or omitted placeholder values" in repair_prompt
    assert "Regenerate the full JSON object from scratch" in repair_prompt


def test_structured_failure_feedback_extracts_instructor_failed_completion() -> None:
    completion = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content='{"chapters":[{"title":"函数","key_points":["定义"]},-1]}',
                    tool_calls=None,
                )
            )
        ]
    )
    failed_attempt = SimpleNamespace(
        exception=ValueError("chapters.1 Input should be an object"),
        completion=completion,
    )
    exc = SimpleNamespace(failed_attempts=[failed_attempt], last_completion=None)

    reason, raw_text = _structured_failure_feedback(exc)  # type: ignore[arg-type]

    assert reason == "chapters.1 Input should be an object"
    assert raw_text == '{"chapters":[{"title":"函数","key_points":["定义"]},-1]}'


@pytest.mark.anyio
async def test_structured_completion_strips_provider_native_tools(monkeypatch) -> None:
    calls: list[dict] = []

    class FakeLiteLLM:
        @staticmethod
        def get_supported_openai_params(*args, **kwargs):
            return []

        async def aresponses(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                output_text='{"title":"函数","key_points":["定义"]}',
                usage=SimpleNamespace(input_tokens=2, output_tokens=3, total_tokens=5),
            )

        async def acompletion(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content='{"title":"函数","key_points":["定义"]}',
                            tool_calls=None,
                        )
                    )
                ],
                usage=SimpleNamespace(prompt_tokens=2, completion_tokens=3, total_tokens=5),
            )

    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://gateway.example.com")
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setattr(structured_calls, "load_litellm", lambda: FakeLiteLLM())
    monkeypatch.setattr(structured_calls, "_load_instructor", lambda: None)
    set_system_settings_override({
        "models": {"primary": "gpt-5.5"},
        "llm": {"api_mode": "auto"},
    })

    result = await structured_calls.acompletion_structured(
        _RepairChapter,
        [{"role": "user", "content": "生成章节"}],
        task_type=TaskType.CHAT,
        model="primary",
        provider_native_tools=[{"type": "web_search", "mode": "force"}],
    )

    assert result.title == "函数"
    assert calls
    assert "input" in calls[0]
    assert "messages" not in calls[0]
    assert "provider_native_tools" not in calls[0]
    assert "tools" not in calls[0]


@pytest.mark.anyio
async def test_structured_completion_uses_responses_for_gpt55_gateway_without_v1(monkeypatch) -> None:
    calls: list[dict] = []

    class FakeLiteLLM:
        async def aresponses(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                output_text='{"title":"函数","key_points":["定义"]}',
                usage=SimpleNamespace(input_tokens=2, output_tokens=3, total_tokens=5),
            )

        async def acompletion(self, **kwargs):  # pragma: no cover - should not be called
            raise AssertionError("Chat Completions should not be used")

    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://sub2api-psqajklu.sealosbja.site")
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setattr(structured_calls, "load_litellm", lambda: FakeLiteLLM())
    monkeypatch.setattr(structured_calls, "_load_instructor", lambda: None)
    set_system_settings_override({
        "models": {"primary": "gpt-5.5"},
        "llm": {"api_mode": "auto"},
    })

    result = await structured_calls.acompletion_structured(
        _RepairChapter,
        [{"role": "user", "content": "生成章节"}],
        task_type=TaskType.CHAT,
        model="primary",
    )

    assert result.title == "函数"
    assert calls[0]["api_base"] == "https://sub2api-psqajklu.sealosbja.site"
    assert calls[0]["input"]
    assert "messages" not in calls[0]


@pytest.mark.anyio
async def test_structured_completion_repairs_responses_parse_failure_without_chat(monkeypatch) -> None:
    calls: list[dict] = []

    class FakeLiteLLM:
        async def aresponses(self, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                return SimpleNamespace(
                    output_text="not json",
                    usage=SimpleNamespace(input_tokens=2, output_tokens=1, total_tokens=3),
                )
            return SimpleNamespace(
                    output_text='{"title":"函数","key_points":["定义"]}',
                usage=SimpleNamespace(input_tokens=3, output_tokens=4, total_tokens=7),
            )

        async def acompletion(self, **kwargs):  # pragma: no cover - should not be called
            raise AssertionError("Chat Completions should not be used")

    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://gateway.example.com")
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setattr(structured_calls, "load_litellm", lambda: FakeLiteLLM())
    monkeypatch.setattr(structured_calls, "_load_instructor", lambda: None)
    set_system_settings_override({
        "models": {"primary": "gpt-5.5"},
        "llm": {"api_mode": "auto"},
    })

    result = await structured_calls.acompletion_structured(
        _RepairChapter,
        [{"role": "user", "content": "生成章节"}],
        task_type=TaskType.CHAT,
        model="primary",
        max_retries=1,
    )

    assert result.title == "函数"
    assert len(calls) == 2
    assert "Previous structured output did not validate." in calls[1]["input"][-1]["content"]
