import asyncio

import pytest

from app.workflows.digest.common.models import DigestMaterialContext, FastTopicHints, SourcePacket
from app.shared.infra.llm_support.common import build_completion_context, prepare_completion_attempt
from app.shared.infra.llm_support.native_tools import PROVIDER_NATIVE_TOOLS_KWARG
from app.shared.infra.llm_support.responses_adapter import resolve_provider_call
from app.shared.infra.settings import set_system_settings_override
from app.workflows.digest.planner.lib.model_policy import PlannerModelStep, get_planner_model_policy
from app.workflows.digest.planner.lib.model_policy import planner_completion_kwargs
from app.workflows.digest.planner.nodes import generate_course_identity as identity_node
from app.workflows.digest.planner.nodes.generate_course_identity import _clean_course_name


def test_course_identity_policy_uses_structured_light_model() -> None:
    policy = get_planner_model_policy(PlannerModelStep.COURSE_IDENTITY)

    kwargs = policy.completion_kwargs()

    assert kwargs["max_tokens"] == 240
    assert kwargs["timeout"] == 60
    assert kwargs["overall_timeout_s"] == 60
    assert kwargs["max_retries"] == 3
    assert 0 <= kwargs["temperature"] <= 1
    assert "task_type" not in kwargs


def test_planner_policy_uses_step_specific_budgets() -> None:
    expected = {
        PlannerModelStep.MATERIAL_BATCH_SUMMARY: (45, 45),
        PlannerModelStep.STREAM_PLANNING_NOTE: (45, 45),
        PlannerModelStep.SUMMARIZE_MATERIALS: (45, 45),
        PlannerModelStep.DIAGNOSE_QUESTIONS: (60, 60),
        PlannerModelStep.DRAFT_PLAN: (120, 180),
    }

    for step, (timeout_s, overall_timeout_s) in expected.items():
        kwargs = get_planner_model_policy(step).completion_kwargs()

        assert kwargs["timeout"] == timeout_s
        assert kwargs["overall_timeout_s"] == overall_timeout_s


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
            assert provider_call.requested_api_mode == "responses"
            assert provider_call.route_reason == "forced_responses"
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


def test_course_identity_falls_back_when_llm_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fail_identity(*args, **kwargs):
        raise TimeoutError("identity timed out")

    events: list[dict[str, object]] = []

    async def record_event(payload: dict[str, object]) -> None:
        events.append(payload)

    monkeypatch.setattr(identity_node, "acompletion_with_fallback", fail_identity)

    node = identity_node.build_generate_course_identity_node(context=None)
    result = asyncio.run(
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

    assert result["generated_course_name"]
    assert result["generated_course_icon_key"]
    stages = [str(event.get("stage") or "") for event in events]
    assert "planner.identity.fallback" in stages


def test_course_identity_fallback_skips_generic_plan_title(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fail_identity(*args, **kwargs):
        raise TimeoutError("identity timed out")

    monkeypatch.setattr(identity_node, "acompletion_with_fallback", fail_identity)

    node = identity_node.build_generate_course_identity_node(context=None)
    result = asyncio.run(
        node(
            {
                "course_id": "course_test",
                "planner_session_id": "planner_test",
                "planner_operation": "create",
                "user_prompt": "请基于每日验收资料生成一个极简学习方案，只需要 2 章。",
                "material_context": DigestMaterialContext(
                    material_hints=FastTopicHints(chapter_candidates=["方案"]),
                    source_documents=[
                        SourcePacket(
                            file_id="file_test",
                            filename="高等数学期末复习.md",
                            filetype="md",
                            markdown_path="",
                            asset_dir="",
                            normalized_content="",
                            char_count=0,
                            has_formulas=False,
                            has_tables=False,
                            has_images=False,
                        )
                    ],
                ),
            }
        )
    )

    assert result["generated_course_name"] == "高等数学期末复习"
