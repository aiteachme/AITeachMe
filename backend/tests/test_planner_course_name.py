from app.shared.infra.llm_support.common import build_completion_context, prepare_completion_attempt
from app.shared.infra.llm_support.native_tools import PROVIDER_NATIVE_TOOLS_KWARG
from app.shared.infra.llm_support.responses_adapter import resolve_provider_call
from app.shared.infra.settings import set_system_settings_override
from app.workflows.digest.planner.lib.model_policy import PlannerModelStep, get_planner_model_policy
from app.workflows.digest.planner.lib.model_policy import planner_completion_kwargs
from app.workflows.digest.planner.nodes.generate_course_identity import _clean_course_name
from app.workflows.digest.planner.prompts.course_name import build_course_identity_messages


def test_course_identity_policy_uses_structured_light_model() -> None:
    policy = get_planner_model_policy(PlannerModelStep.COURSE_IDENTITY)

    kwargs = policy.completion_kwargs()

    assert kwargs["temperature"] == 0.35
    assert kwargs["max_tokens"] == 240
    assert kwargs["timeout"] == 300
    assert kwargs["max_retries"] == 3
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
            assert provider_call.route_reason == "auto_reasoning_model"
            assert provider_call.kwargs["model"] == "gpt-5.5"
            assert provider_call.provider_native_tool_types == ()
    finally:
        set_system_settings_override({})


def test_course_identity_prompt_generates_name_and_icon_together() -> None:
    messages = build_course_identity_messages(
        user_prompt="Python 数据分析想学到能做作业",
        filenames=["课程PPT.pdf", "作业要求.docx"],
        digest_mode="sprint",
        planning_note="面向作业完成的实用学习路径",
        material_note="用户更需要把概念、代码和调试串起来。",
        topic_hints=["DataFrame", "数据清洗", "可视化"],
    )
    prompt = "\n".join(message["content"] for message in messages)

    assert "course_name" in prompt
    assert "course_icon" in prompt
    assert "不要总是套“学习/课程/资料”后缀" in prompt
    assert "Python作业通关" in prompt
    assert "心理学入门地图" in prompt
    assert "财管重点清单" in prompt


def test_clean_course_name_handles_numbered_or_labeled_candidates() -> None:
    assert _clean_course_name("标题：Python作业通关。") == "Python作业通关"
    assert _clean_course_name("1. 高数主线重建\n2. 高数复习路线") == "高数主线重建"
    assert _clean_course_name("“心理学入门地图”") == "心理学入门地图"
    assert _clean_course_name("未命名课程") == ""
