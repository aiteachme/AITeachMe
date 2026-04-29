from app.workflows.digest.planner.lib.model_policy import PlannerModelStep, get_planner_model_policy
from app.workflows.digest.planner.nodes.generate_course_name import _clean_course_name
from app.workflows.digest.planner.prompts.course_name import build_course_name_prompt


def test_course_name_policy_uses_creative_temperature() -> None:
    policy = get_planner_model_policy(PlannerModelStep.COURSE_NAME)

    kwargs = policy.completion_kwargs()

    assert kwargs["temperature"] == 0.65
    assert kwargs["max_tokens"] == 40


def test_course_name_prompt_has_diverse_examples_and_anti_generic_rule() -> None:
    prompt = build_course_name_prompt(
        user_prompt="Python 数据分析想学到能做作业",
        filenames=["课程PPT.pdf", "作业要求.docx"],
        digest_mode="sprint",
        plan_intent="面向作业完成的实用学习路径",
        planner_brief="用户更需要把概念、代码和调试串起来。",
        topic_hints=["DataFrame", "数据清洗", "可视化"],
    )

    assert "先在心里生成 4 个不同角度的候选" in prompt
    assert "不要总是写成“某某学习”“某某复习”“某某课程”“某某资料”" in prompt
    assert "Python作业通关" in prompt
    assert "心理学入门地图" in prompt
    assert "设计史脉络" in prompt


def test_clean_course_name_handles_numbered_or_labeled_candidates() -> None:
    assert _clean_course_name("标题：Python作业通关。") == "Python作业通关"
    assert _clean_course_name("1. 高数主线重建\n2. 高数复习路线") == "高数主线重建"
    assert _clean_course_name("“心理学入门地图”") == "心理学入门地图"
    assert _clean_course_name("未命名课程") == ""
