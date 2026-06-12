from __future__ import annotations

from app.models.build_planner import ConfirmedBuildPlan
from app.shared.infra.llm_support.model_choices import (
    build_runtime_model_override_snapshot,
    normalize_runtime_model_override,
)
from app.workflows.digest.docgen.lib.build_lifecycle import _build_confirmed_plan_payload


def test_confirmed_plan_payload_preserves_model_override() -> None:
    plan = ConfirmedBuildPlan(
        id="plan_1",
        course_id="course_1",
        planner_session_id="planner_1",
        user_id="user_1",
        user_prompt="学习线性代数",
        digest_mode="sprint",
        plan_json={
            "course_name": "线性代数",
            "course_icon": "calculator",
            "user_prompt": "学习线性代数",
            "digest_mode": "sprint",
            "intent": "学习线性代数",
            "summary": "资料围绕矩阵和方程组。",
            "suggestion": "可以继续改成考试冲刺。",
            "plan": "一份线性代数学习计划",
            "chapters": [],
            "build_constraints": {},
            "model_override": "gpt-5.5",
        },
    )

    payload = _build_confirmed_plan_payload(plan, fallback_course_name="线性代数")

    assert payload["model_override"] == "gpt-5.5"


def test_runtime_model_override_snapshot_patches_main_model_slots() -> None:
    snapshot = build_runtime_model_override_snapshot("gpt-5.4-mini")

    assert snapshot is not None
    assert snapshot.settings.models.reason == "gpt-5.4-mini"
    assert snapshot.settings.models.primary == "gpt-5.4-mini"
    assert snapshot.settings.models.light == "gpt-5.4-mini"
    assert {endpoint.role for endpoint in snapshot.primary_endpoints} == {"primary"}


def test_gemini_override_routes_only_to_fallback_endpoint(monkeypatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "primary-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://primary.example.com/v1")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_FALLBACK_API_KEY", "fallback-key")
    monkeypatch.setenv("LLM_FALLBACK_BASE_URL", "https://generativelanguage.googleapis.com/v1beta")

    snapshot = build_runtime_model_override_snapshot("gemini-3.1-flash-lite")

    assert snapshot is not None
    assert snapshot.settings.models.reason == "gemini-3.1-flash-lite"
    assert snapshot.settings.models.primary == "gemini-3.1-flash-lite"
    assert snapshot.settings.models.light == "gemini-3.1-flash-lite"
    assert len(snapshot.primary_endpoints) == 1
    assert snapshot.primary_endpoints[0].role == "fallback"
    assert snapshot.primary_endpoints[0].api_key == "fallback-key"
    assert snapshot.primary_endpoints[0].base_url == "https://generativelanguage.googleapis.com/v1beta"
    assert snapshot.fallback_endpoints == ()


def test_non_primary_override_never_reuses_primary_endpoint_when_fallback_missing(monkeypatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "primary-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://primary.example.com/v1")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_FALLBACK_API_KEY", "")
    monkeypatch.setenv("LLM_FALLBACK_BASE_URL", "")

    snapshot = build_runtime_model_override_snapshot("gemini-3.1-flash-lite")

    assert snapshot is not None
    assert snapshot.api_keys == ()
    assert len(snapshot.primary_endpoints) == 1
    assert snapshot.primary_endpoints[0].role == "fallback"
    assert snapshot.primary_endpoints[0].api_key is None
    assert snapshot.primary_endpoints[0].base_url is None
    assert snapshot.fallback_endpoints == ()


def test_legacy_runtime_model_overrides_are_not_accepted() -> None:
    assert normalize_runtime_model_override("deepseek-v4-flash") is None
    assert normalize_runtime_model_override("qwen-flash") is None
