import json

from app.workflows.digest.common.models import DigestMaterialContext, SubjectProfile
from app.workflows.digest.planner.lib.models import PlanIntent, PlannerBrief
from app.workflows.digest.planner.lib.plans import normalize_planner_draft
from app.workflows.digest.planner.nodes.stream_and_parse_plan_draft import (
    PLAN_JSON_END_MARKER,
    PLAN_JSON_MARKER,
    _parse_outline_sketch,
    _sketch_to_plan_payload,
)
from app.workflows.digest.planner.nodes.stream_and_parse_plan_draft import (
    _subject_for_prompt as _composer_subject_for_prompt,
)
from app.workflows.digest.planner.nodes.stream_brief_and_extract_intent import (
    _fallback_plan_queries,
    _normalize_plan_queries,
    _subject_for_prompt as _intent_subject_for_prompt,
)
from app.workflows.digest.planner.prompts.examples import render_composer_examples, render_plan_intent_examples
from app.workflows.digest.planner.prompts.build_plan_composer import build_plan_composer_messages


def test_plan_intent_contract_keeps_only_intent_and_queries():
    intent = PlanIntent.model_validate(
        {
            "plan_intent": "以三年级数学核心考点为主线组织。",
            "plan_queries": ["口算易错点", "图形周长应用"],
        }
    )

    assert intent.plan_intent == "以三年级数学核心考点为主线组织。"
    assert intent.plan_queries == ["口算易错点", "图形周长应用"]
    assert "goal_type" not in intent.model_dump()


def test_plan_queries_are_deduped_and_bounded():
    queries = _normalize_plan_queries([f"抓手 {index}" for index in range(10)] + ["抓手 1"])

    assert queries == [f"抓手 {index}" for index in range(8)]


def test_planner_prompt_subject_uses_display_name_not_subject_id():
    material_context = DigestMaterialContext(
        learning_domain_profile=SubjectProfile(subject_slug="subj_demo", subject_name="数学")
    )
    state = {
        "subject": "subj_demo",
        "user_goal": "介绍下小学数学",
        "digest_mode": "sprint",
        "material_context": material_context,
    }

    assert _intent_subject_for_prompt(state) == "数学"
    assert _composer_subject_for_prompt(state) == "数学"
    assert all("subj_" not in item for item in _fallback_plan_queries(state))


def test_composer_hidden_json_parses_to_initial_outline_payload():
    payload = {
        "plan_text": "本计划以三年级数学核心考点为主线，先计算再图形，最后应用题。",
        "plan_steps": ["归并资料主题", "识别高频题型", "生成初步大纲"],
        "chapters": [
            {"title": "口算与竖式计算", "key_points": ["三位数加减法", "乘法口诀"]},
            {"title": "图形与单位换算", "key_points": ["周长公式", "单位换算"]},
        ],
    }
    raw = "可见计划说明\n" + PLAN_JSON_MARKER + "\n" + json.dumps(payload, ensure_ascii=False) + "\n" + PLAN_JSON_END_MARKER

    sketch = _parse_outline_sketch(raw)
    plan = _sketch_to_plan_payload(sketch)

    assert plan["plan_summary"] == payload["plan_text"]
    assert plan["plan_steps"] == payload["plan_steps"]
    assert [chapter["title"] for chapter in plan["chapter_plan"]] == ["口算与竖式计算", "图形与单位换算"]
    assert plan["chapter_plan"][0]["required_elements"] == ["三位数加减法", "乘法口诀"]


def test_normalized_planner_draft_preserves_plan_steps():
    draft = normalize_planner_draft(
        {
            "plan_summary": "先整理资料，再形成初步大纲。",
            "plan_steps": ["归并资料主题", "判断优先级", "形成大纲"],
            "chapter_plan": [
                {"title": "核心概念", "required_elements": ["定义", "边界"]},
                {"title": "典型题型", "required_elements": ["题眼", "步骤"]},
            ],
        },
        subject="math",
        user_goal="复习高数",
        requested_digest_mode="systematic",
    )

    assert draft.plan_steps == ["归并资料主题", "判断优先级", "形成大纲"]


def test_composer_examples_include_full_plan_and_outline_shape():
    rendered = render_composer_examples()

    assert "plan_text：" in rendered
    assert "plan_steps：" in rendered
    assert "chapters：" in rendered
    assert "查询" in rendered
    assert "搜集" in rendered
    assert "课程范围与学习主线" in rendered
    assert "考试范围与优先级" in rendered
    assert "具体知识内容" not in rendered


def test_composer_prompt_allows_research_plan_without_claiming_done():
    material_context = DigestMaterialContext(
        learning_domain_profile=SubjectProfile(subject_slug="subj_demo", subject_name="数学")
    )
    prompt = build_plan_composer_messages(
        subject="数学",
        user_goal="介绍下小学数学",
        digest_mode="sprint",
        material_context=material_context,
        planner_brief=PlannerBrief(markdown="用户想先了解小学数学整体框架。"),
        plan_intent=PlanIntent(plan_intent="入门理解小学数学", plan_queries=["小学数学核心知识簇"]),
    )[1]["content"]

    assert "可以写“后续会查询/对照/搜集哪些方向”" in prompt
    assert "不能说已经完成检索" in prompt
    assert "plan_steps 是 4-7 条动作步骤" in prompt
    assert "plan_text 和 plan_steps 是重点" in prompt
    assert "chapters 是很初步的粗颗粒骨架" in prompt


def test_plan_intent_examples_include_intent_recognition_shape():
    rendered = render_plan_intent_examples()

    assert "输出 plan_intent：" in rendered
    assert "输出 plan_queries：" in rendered
    assert "资料生成意图" in rendered
    assert "复习资料整理意图" in rendered
    assert "综合题理解与连接能力" in rendered
