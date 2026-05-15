from __future__ import annotations

from types import SimpleNamespace

from pydantic import BaseModel

from app.shared.infra.llm_support.structured import _build_structured_fallback_messages
from app.shared.infra.llm_support.structured_calls import _structured_failure_feedback


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
    assert "do not output placeholder values such as -1" in repair_prompt
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
