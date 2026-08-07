from __future__ import annotations

import pytest

from app.models.build_planner import ConfirmedBuildPlan
from app.shared.infra.llm_support.common import (
    LLMEndpoint,
    LLMRuntimeSnapshot,
    build_completion_contexts,
    use_llm_runtime_snapshot,
)
from app.shared.infra.llm_support.model_choices import (
    build_runtime_model_override_snapshot,
    normalize_runtime_model_override,
)
from app.shared.infra.llm_support.routing import TaskType
from app.shared.infra.settings import get_settings
from app.workflows.digest.docgen.lib.build_lifecycle import _build_confirmed_plan_payload


def _configured_runtime_snapshot() -> LLMRuntimeSnapshot:
    settings = get_settings()
    models = settings.models.model_copy(
        update={
            "reason": "main-reason-model",
            "primary": "main-primary-model",
            "light": "main-light-model",
        },
    )
    fallback_models = settings.fallback_models.model_copy(
        update={
            "reason": "fallback-reason-model",
            "primary": None,
            "light": "fallback-light-model",
        },
    )
    reasoning_efforts = settings.llm.reasoning_efforts.model_copy(
        update={"reason": "high", "primary": "medium", "light": "low"},
    )
    llm = settings.llm.model_copy(update={"reasoning_efforts": reasoning_efforts})
    configured_settings = settings.model_copy(
        update={
            "models": models,
            "fallback_models": fallback_models,
            "llm": llm,
        },
        deep=True,
    )
    return LLMRuntimeSnapshot(
        settings=configured_settings,
        primary_endpoints=(
            LLMEndpoint(
                role="primary",
                base_url="https://primary.example.com/v1",
                api_key="primary-key",
                provider="openai_compatible",
                api_version=None,
            ),
        ),
        fallback_endpoints=(
            LLMEndpoint(
                role="fallback",
                base_url="https://fallback.example.com/v1",
                api_key="fallback-key",
                provider="openai_compatible",
                api_version=None,
            ),
        ),
    )


def test_confirmed_plan_payload_preserves_model_tier_override() -> None:
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
            "model_override": "reason",
        },
    )

    payload = _build_confirmed_plan_payload(plan, fallback_course_name="线性代数")

    assert payload["model_override"] == "reason"


@pytest.mark.parametrize(
    ("selector", "main_model", "configured_fallback_model", "effective_fallback_model", "effort"),
    [
        ("reason", "main-reason-model", "fallback-reason-model", "fallback-reason-model", "high"),
        ("primary", "main-primary-model", None, "main-primary-model", "medium"),
        ("light", "main-light-model", "fallback-light-model", "fallback-light-model", "low"),
    ],
)
def test_runtime_model_tier_override_maps_models_fallbacks_and_efforts(
    selector: str,
    main_model: str,
    configured_fallback_model: str | None,
    effective_fallback_model: str,
    effort: str,
) -> None:
    with use_llm_runtime_snapshot(_configured_runtime_snapshot()):
        snapshot = build_runtime_model_override_snapshot(selector)

    assert snapshot is not None
    assert snapshot.settings.models.reason == main_model
    assert snapshot.settings.models.primary == main_model
    assert snapshot.settings.models.light == main_model
    assert snapshot.settings.fallback_models.reason == configured_fallback_model
    assert snapshot.settings.fallback_models.primary == configured_fallback_model
    assert snapshot.settings.fallback_models.light == configured_fallback_model
    assert snapshot.settings.llm.reasoning_efforts.reason == effort
    assert snapshot.settings.llm.reasoning_efforts.primary == effort
    assert snapshot.settings.llm.reasoning_efforts.light == effort
    assert [endpoint.role for endpoint in snapshot.primary_endpoints] == ["primary"]
    assert [endpoint.role for endpoint in snapshot.fallback_endpoints] == ["fallback"]

    with use_llm_runtime_snapshot(snapshot):
        contexts = build_completion_contexts(task_type=TaskType.CHAT, model="light")

    assert [context.endpoint_role for context in contexts] == ["primary", "fallback"]
    assert [context.model for context in contexts] == [main_model, effective_fallback_model]
    assert [
        context.settings.llm.reasoning_efforts.for_selector(context.model_selector)
        for context in contexts
    ] == [effort, effort]


def test_runtime_model_override_accepts_only_semantic_tiers() -> None:
    assert normalize_runtime_model_override(" REASON ") == "reason"
    assert normalize_runtime_model_override("primary") == "primary"
    assert normalize_runtime_model_override("light") == "light"
    assert normalize_runtime_model_override("settings") is None
    assert normalize_runtime_model_override("gpt-5.6-sol") is None
