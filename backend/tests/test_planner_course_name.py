import asyncio

import pytest

from app.workflows.digest.common.models import DigestMaterialContext
from app.shared.infra.llm_support.common import build_completion_context, prepare_completion_attempt
from app.shared.infra.llm_support.native_tools import PROVIDER_NATIVE_TOOLS_KWARG
from app.shared.infra.llm_support.responses_adapter import resolve_provider_call
from app.shared.infra.settings import set_system_settings_override
from app.workflows.digest.planner.lib.model_policy import PlannerModelStep
from app.workflows.digest.planner.lib.model_policy import planner_completion_kwargs
from app.workflows.digest.planner.nodes import generate_course_identity as identity_node
from app.workflows.digest.planner.nodes.generate_course_identity import _clean_course_name


def test_planner_policy_uses_light_tier_with_bounded_timeouts() -> None:
    for step in PlannerModelStep:
        kwargs = planner_completion_kwargs(step)

        assert kwargs["model"] == "light"
        assert kwargs["timeout"] > 0
        assert kwargs["overall_timeout_s"] >= kwargs["timeout"]
        assert kwargs[PROVIDER_NATIVE_TOOLS_KWARG] == []
        assert "task_type" not in kwargs


def test_planner_stream_policy_keeps_gpt55_auto_on_responses_without_native_tools(monkeypatch) -> None:
    monkeypatch.setenv("LLM_BASE_URL", "https://gateway.example.com")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    try:
        set_system_settings_override(
            {
                "models": {
                    "primary": "gpt-5.5",
                    "light": "gpt-5.5",
                    "reason": "gpt-5.5",
                },
                "llm": {"api_mode": "auto", "native_web_search": "force", "native_file_search": "force"},
            }
        )
        for step in (PlannerModelStep.STREAM_PLANNING_NOTE, PlannerModelStep.DRAFT_PLAN):
            policy_kwargs = planner_completion_kwargs(step)
            assert int(policy_kwargs.pop("overall_timeout_s")) >= int(policy_kwargs["timeout"])
            assert policy_kwargs[PROVIDER_NATIVE_TOOLS_KWARG] == []
            model_selector = str(policy_kwargs.pop("model"))
            context = build_completion_context(model=model_selector)
            prepared = prepare_completion_attempt(
                context=context,
                messages=[{"role": "user", "content": "构建 14 天初中数学复习课"}],
                extra_kwargs=policy_kwargs,
                attempt=1,
                override_kwargs={"stream": True},
            )

            provider_call = resolve_provider_call(context=context, call_kwargs=prepared.call_kwargs)

            assert provider_call.api_mode == "responses"
            assert provider_call.requested_api_mode == "auto"
            assert provider_call.auto_chat_fallback_kwargs is not None
            assert provider_call.route_reason == "auto_model_catalog_responses"
            assert provider_call.kwargs["model"] == "gpt-5.5"
            assert provider_call.provider_native_tool_types == ()
    finally:
        set_system_settings_override({})


def test_clean_course_name_handles_numbered_or_labeled_candidates() -> None:
    assert _clean_course_name("标题：Python作业通关。") == "Python作业通关"
    assert _clean_course_name("1. 高数主线重建\n2. 高数复习路线") == "高数主线重建"
    assert _clean_course_name("“心理学入门地图”") == "心理学入门地图"
    assert _clean_course_name("未命名课程") == ""
    assert _clean_course_name("方案") == ""
    assert _clean_course_name("学习方案") == ""


def test_course_identity_raises_when_llm_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fail_identity(*args, **kwargs):
        raise TimeoutError("identity timed out")

    events: list[dict[str, object]] = []

    async def record_event(payload: dict[str, object]) -> None:
        events.append(payload)

    monkeypatch.setattr(identity_node, "acompletion_with_fallback", fail_identity)

    node = identity_node.build_generate_course_identity_node(context=None)
    with pytest.raises(TimeoutError, match="identity timed out"):
        asyncio.run(
            node(
                {
                    "course_id": "course_test",
                    "planner_session_id": "planner_test",
                    "planner_operation": "create",
                    "user_prompt": "我想学习线性代数",
                    "material_context": DigestMaterialContext(),
                    "progress_callback": record_event,
                }
            )
        )

    stages = [str(event.get("stage") or "") for event in events]
    assert "planner.identity.started" in stages
    assert "planner.identity.failed" in stages
    assert "planner.identity.fallback" not in stages
    assert "planner.identity.ready" not in stages
