import json

from app.workflows.digest.planner.lib.models import PlanIntent
from app.workflows.digest.planner.lib.plans import normalize_planner_draft
from app.workflows.digest.planner.nodes.stream_and_parse_plan_draft import (
    PLAN_JSON_END_MARKER,
    PLAN_JSON_MARKER,
    _parse_outline_sketch,
    _sketch_to_plan_payload,
)
from app.workflows.digest.planner.nodes.stream_brief_and_extract_intent import _normalize_plan_queries
from app.workflows.digest.planner.prompts.examples import render_composer_examples, render_plan_intent_examples


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
    assert "口算与竖式计算" in rendered
    assert "特征值与对角化" in rendered


def test_plan_intent_examples_include_intent_recognition_shape():
    rendered = render_plan_intent_examples()

    assert "输出 plan_intent：" in rendered
    assert "输出 plan_queries：" in rendered
    assert "资料生成意图" in rendered
    assert "复习资料整理意图" in rendered
    assert "综合题理解与连接能力" in rendered
