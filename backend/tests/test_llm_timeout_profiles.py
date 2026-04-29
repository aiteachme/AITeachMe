from app.shared.infra.llm_support.common import build_completion_context, context_request_timeout_s
from app.shared.infra.llm_support.routing import LLMCallPurpose, get_call_profile


def test_heavy_llm_profiles_allow_long_background_calls():
    assert get_call_profile(LLMCallPurpose.DOCGEN).timeout_s >= 300
    assert get_call_profile(LLMCallPurpose.DOCGEN_LIGHT).timeout_s >= 240
    assert get_call_profile(LLMCallPurpose.VISION).timeout_s >= 240


def test_llm_profile_timeout_env_override(monkeypatch):
    monkeypatch.setenv("LLM_TIMEOUT_DOCGEN_S", "420")
    monkeypatch.setenv("LLM_MAX_RETRIES_DOCGEN", "3")

    profile = get_call_profile(LLMCallPurpose.DOCGEN)

    assert profile.timeout_s == 420
    assert profile.max_retries == 3


def test_outer_request_timeout_uses_explicit_call_timeout(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    context = build_completion_context(call_purpose=LLMCallPurpose.DOCGEN)

    assert context_request_timeout_s(context, {"timeout": 420}) == 422


def test_invalid_explicit_timeout_falls_back_to_profile(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    context = build_completion_context(call_purpose=LLMCallPurpose.DOCGEN)

    assert context_request_timeout_s(context, {"timeout": 0}) == context.profile.timeout_s + 2
    assert context_request_timeout_s(context, {"timeout": "bad"}) == context.profile.timeout_s + 2
