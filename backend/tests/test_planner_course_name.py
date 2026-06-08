from app.workflows.digest.planner.lib.model_policy import PlannerModelStep, get_planner_model_policy
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
