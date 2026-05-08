from app.shared.infra.llm_support.common import (
    build_completion_context,
    build_completion_kwargs,
    context_request_timeout_s,
    effective_max_retries,
)
from app.shared.infra.llm_support.routing import TaskType, get_task_profile


def test_heavy_llm_profiles_allow_long_background_calls():
    assert get_task_profile(TaskType.DOCGEN).timeout_s >= 600
    assert get_task_profile(TaskType.DOCGEN).max_retries >= 3
    assert get_task_profile(TaskType.DOCGEN_LIGHT).timeout_s >= 480
    assert get_task_profile(TaskType.EXTRACT).timeout_s >= 300
    assert get_task_profile(TaskType.VISION).timeout_s >= 480


def test_llm_profile_timeout_env_override(monkeypatch):
    monkeypatch.setenv("LLM_TIMEOUT_DOCGEN_S", "420")
    monkeypatch.setenv("LLM_MAX_RETRIES_DOCGEN", "3")

    profile = get_task_profile(TaskType.DOCGEN)

    assert profile.timeout_s == 420
    assert profile.max_retries == 3


def test_task_type_profile_does_not_inject_generation_kwargs(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    context = build_completion_context(task_type=TaskType.CHAT)
    messages = [{"role": "user", "content": "hello"}]

    default_kwargs = build_completion_kwargs(
        context=context,
        messages=messages,
        extra_kwargs={},
    )
    explicit_kwargs = build_completion_kwargs(
        context=context,
        messages=messages,
        extra_kwargs={"temperature": 0.2},
    )
    explicit_token_kwargs = build_completion_kwargs(
        context=context,
        messages=messages,
        extra_kwargs={"max_tokens": 1234},
    )
    explicit_retry_kwargs = build_completion_kwargs(
        context=context,
        messages=messages,
        extra_kwargs={"max_retries": 2},
    )

    assert "temperature" not in default_kwargs
    assert "max_tokens" not in default_kwargs
    assert "max_retries" not in explicit_retry_kwargs
    assert explicit_kwargs["temperature"] == 0.2
    assert explicit_token_kwargs["max_tokens"] == 1234


def test_explicit_max_retries_overrides_profile_without_provider_passthrough(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    context = build_completion_context(task_type=TaskType.CHAT)

    assert effective_max_retries(context, {"max_retries": 2}) == 2
    assert effective_max_retries(context, {"max_retries": 0}) == 1
    assert effective_max_retries(context, {"max_retries": 99}) == 10
    assert effective_max_retries(context, {"max_retries": "bad"}) == context.profile.max_retries


def test_outer_request_timeout_uses_explicit_call_timeout(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    context = build_completion_context(task_type=TaskType.DOCGEN)

    assert context_request_timeout_s(context, {"timeout": 420}) == 422


def test_invalid_explicit_timeout_falls_back_to_profile(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    context = build_completion_context(task_type=TaskType.DOCGEN)

    assert context_request_timeout_s(context, {"timeout": 0}) == context.profile.timeout_s + 2
    assert context_request_timeout_s(context, {"timeout": "bad"}) == context.profile.timeout_s + 2
