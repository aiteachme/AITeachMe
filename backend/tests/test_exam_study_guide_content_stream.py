from __future__ import annotations

import json

import pytest

from app.utils.time import utcnow
from app.workflows.examine.exam_grade import graph as exam_grade_graph
from app.workflows.examine.exam_grade.prompts import build_study_guide_messages
from app.workflows.examine.exam_grade.lib import study_guide as study_guide_module
from app.workflows.examine.exam_grade.lib.study_guide import ExamStudyGuidePayload


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _payload() -> dict[str, object]:
    return {
        "overall_summary": "本次作答整体较为稳定，但矩阵乘法的运算顺序仍需重点巩固并及时复盘。",
        "strengths": ["基础概念掌握较稳", "能够识别常见题型"],
        "focus_units": [
            {
                "knowledge_unit_id": 12,
                "knowledge_unit_name": "矩阵乘法",
                "mastery_score": 0.45,
                "reason": "运算顺序仍不稳定。",
            }
        ],
        "priority_gaps": ["矩阵乘法顺序", "线性映射的几何意义"],
        "action_steps": ["回顾定义", "重做错题", "完成两道变式题"],
    }


@pytest.mark.anyio
async def test_study_guide_stream_emits_partial_content_before_final_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = json.dumps(_payload(), ensure_ascii=False)

    async def fake_stream(*_args, **_kwargs):
        for start in range(0, len(raw), 32):
            yield raw[start : start + 32]

    async def unexpected_structured_call(*_args, **_kwargs):
        raise AssertionError("valid streamed JSON must not invoke structured fallback")

    monkeypatch.setattr(study_guide_module, "acompletion_stream", fake_stream)
    monkeypatch.setattr(
        study_guide_module,
        "acompletion_with_fallback",
        unexpected_structured_call,
    )
    drafts = []

    result = await study_guide_module.generate_exam_study_guide(
        exam_paper_id=42,
        course_name="线性代数",
        exam_title="阶段测验",
        score_summary="得分 80/100",
        wrong_question_summaries=[],
        knowledge_unit_performance=[
            {
                "knowledge_unit_id": 12,
                "knowledge_unit_name": "矩阵乘法",
                "paper_score_rate": 0.5,
                "paper_evidence": "本卷关联 2 题，按分值计 1/2 分。",
                "cumulative_mastery_score": 0.8,
                "profile_context": "累计画像：掌握度 80%，累计练习 10 次，答对 8 次。",
            }
        ],
        pending_reviews=[],
        generated_at=utcnow(),
        content_callback=drafts.append,
    )

    assert len(drafts) >= 2
    assert drafts[0].overall_summary
    assert drafts[0].overall_summary != result.overall_summary
    assert drafts[-1] == result
    assert result.focus_units[0].knowledge_unit_name == "矩阵乘法"
    assert result.review_tasks == []

    first_strengths = next(index for index, draft in enumerate(drafts) if draft.strengths)
    first_focus_units = next(index for index, draft in enumerate(drafts) if draft.focus_units)
    first_priority_gaps = next(index for index, draft in enumerate(drafts) if draft.priority_gaps)
    first_action_steps = next(index for index, draft in enumerate(drafts) if draft.action_steps)
    assert first_strengths <= first_focus_units <= first_priority_gaps <= first_action_steps


@pytest.mark.anyio
async def test_study_guide_stream_splits_sections_returned_in_one_provider_chunk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = json.dumps(_payload(), ensure_ascii=False)

    async def fake_stream(*_args, **_kwargs):
        yield raw

    async def unexpected_structured_call(*_args, **_kwargs):
        raise AssertionError("valid streamed JSON must not invoke structured fallback")

    monkeypatch.setattr(study_guide_module, "acompletion_stream", fake_stream)
    monkeypatch.setattr(
        study_guide_module,
        "acompletion_with_fallback",
        unexpected_structured_call,
    )
    drafts = []

    result = await study_guide_module.generate_exam_study_guide(
        exam_paper_id=42,
        course_name="线性代数",
        exam_title="阶段测验",
        score_summary="得分 80/100",
        wrong_question_summaries=[],
        knowledge_unit_performance=[],
        pending_reviews=[],
        generated_at=utcnow(),
        content_callback=drafts.append,
    )

    priority_index = next(index for index, draft in enumerate(drafts) if draft.priority_gaps)
    action_index = next(index for index, draft in enumerate(drafts) if draft.action_steps)
    assert priority_index < action_index
    assert drafts[priority_index].action_steps == []
    assert drafts[action_index] == result


@pytest.mark.anyio
async def test_invalid_stream_falls_back_to_structured_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def invalid_stream(*_args, **_kwargs):
        yield "模型正在思考，但没有返回 JSON"

    expected = ExamStudyGuidePayload.model_validate(_payload())

    async def fake_structured(*_args, **_kwargs):
        return expected

    monkeypatch.setattr(study_guide_module, "acompletion_stream", invalid_stream)
    monkeypatch.setattr(study_guide_module, "acompletion_with_fallback", fake_structured)
    drafts = []

    result = await study_guide_module.generate_exam_study_guide(
        exam_paper_id=42,
        course_name="线性代数",
        exam_title="阶段测验",
        score_summary="得分 80/100",
        wrong_question_summaries=[],
        knowledge_unit_performance=[],
        pending_reviews=[],
        generated_at=utcnow(),
        content_callback=drafts.append,
    )

    assert drafts
    assert drafts[-1] == result
    priority_index = next(index for index, draft in enumerate(drafts) if draft.priority_gaps)
    action_index = next(index for index, draft in enumerate(drafts) if draft.action_steps)
    assert priority_index < action_index
    assert result.overall_summary == expected.overall_summary


@pytest.mark.anyio
async def test_study_guide_workflow_forwards_content_callback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generated_at = utcnow()
    expected = study_guide_module._response_from_payload(
        ExamStudyGuidePayload.model_validate(_payload()),
        exam_paper_id=42,
        course_name="线性代数",
        generated_at=generated_at,
    )
    drafts = []

    async def fake_generate(**kwargs):
        callback = kwargs.get("content_callback")
        assert callable(callback)
        callback(expected)
        return expected

    monkeypatch.setattr(exam_grade_graph, "generate_exam_study_guide", fake_generate)

    result = await exam_grade_graph.run_exam_study_guide_workflow(
        exam_paper_id=42,
        course_id="course_linear_algebra",
        course_name="线性代数",
        exam_title="阶段测验",
        score_summary="得分 80/100",
        wrong_question_summaries=[],
        knowledge_unit_performance=[],
        pending_reviews=[],
        generated_at=generated_at,
        content_callback=drafts.append,
    )

    assert result == expected
    assert drafts == [expected]


def test_study_guide_generation_contract_matches_display_order() -> None:
    assert list(ExamStudyGuidePayload.model_fields) == [
        "overall_summary",
        "strengths",
        "focus_units",
        "priority_gaps",
        "action_steps",
    ]

    messages = build_study_guide_messages(
        course_name="线性代数",
        exam_title="阶段测验",
        score_summary="得分 80/100",
        wrong_question_summaries=[],
        knowledge_unit_performance=[
            {
                "knowledge_unit_id": 12,
                "knowledge_unit_name": "矩阵乘法",
                "paper_score_rate": 0.5,
                "paper_evidence": "本卷关联 2 题，按分值计 1/2 分。",
                "cumulative_mastery_score": 0.8,
                "profile_context": "累计画像：掌握度 80%，累计练习 10 次，答对 8 次。",
            }
        ],
        pending_reviews=[],
    )
    prompt = messages[-1]["content"]
    assert prompt.index("`strengths`") < prompt.index("`focus_units`")
    assert prompt.index("`focus_units`") < prompt.index("`priority_gaps`")
    assert prompt.index("`priority_gaps`") < prompt.index("`action_steps`")
    assert "不要另行输出 `review_tasks`" in prompt
    assert "`action_steps`：2-3条" in prompt
    assert "累计画像：掌握度 80%" in prompt
    assert "累计画像只用于判断问题是偶发还是持续" in prompt
    assert "`reason`只概括本卷关联题目的作答、得分与暴露的问题" in prompt
    assert "不得向学生展示 repeated_wrong" in messages[0]["content"]


def test_study_guide_payload_caps_sections_and_hides_internal_labels() -> None:
    payload = _payload()
    payload["strengths"] = ["优势一", "优势二", "优势三"]
    payload["focus_units"] = [
        {
            "knowledge_unit_id": index,
            "knowledge_unit_name": f"知识点{index}",
            "mastery_score": 0.2,
            "reason": "待复习任务中标记为 repeated_wrong",
        }
        for index in range(1, 6)
    ]
    payload["priority_gaps"] = [f"缺口{index}" for index in range(5)]
    payload["action_steps"] = [f"步骤{index}" for index in range(6)]

    result = ExamStudyGuidePayload.model_validate(payload)

    assert len(result.strengths) == 2
    assert len(result.focus_units) == 3
    assert len(result.priority_gaps) == 3
    assert len(result.action_steps) == 3
    assert "repeated_wrong" not in result.focus_units[0].reason
    assert "近期同类题连续出错" in result.focus_units[0].reason
