import asyncio
from collections.abc import Iterator

import pytest

from app.workflows.digest.common.models import DigestMaterialContext, DigestMode, DigestModeDecision
from app.workflows.digest.planner.lib.constants import get_planner_mode_contract
from app.workflows.digest.planner.lib.plans import (
    normalize_planner_draft,
    planner_mode_label,
    render_planner_chapter_contract,
)
from app.workflows.digest.planner.lib.store import _ensure_chapter_count_payload
from app.workflows.digest.planner.nodes import compose_planner_draft as plan_draft_node
from app.workflows.digest.planner.prompts.build_plan_composer import (
    CHAPTERS_END,
    CHAPTERS_START,
    PLAN_END,
    PLAN_START,
    SUGGESTION_END,
    SUGGESTION_START,
    build_planner_stream_messages,
)


def _material_context() -> DigestMaterialContext:
    return DigestMaterialContext(
        course_mode_decision=DigestModeDecision(mode=DigestMode.SPRINT),
        material_digest="高数速成资料摘要，重点覆盖极限、导数和积分。",
    )


def _planner_payload(*, chapter_count: int = 3) -> dict[str, object]:
    return {
        "course_name": "高数主线重建",
        "course_icon": "sigma",
        "intent": "用户想把高数混乱知识整理成可执行复习路径。",
        "summary": "资料显示当前重点集中在极限、导数和积分。",
        "suggestion": "如果更偏考试，可以增加题型和易错点密度。",
        "plan": "本课程会先用极限建立函数变化的基础，再进入导数规则与应用，最后把积分计算和综合题串起来。",
        "chapters": [
            {
                "title": f"任务切片 {index}",
                "key_points": [f"切片 {index} 的学习任务", f"切片 {index} 的边界"],
            }
            for index in range(1, chapter_count + 1)
        ],
    }


def test_planner_mode_label_is_student_facing() -> None:
    assert planner_mode_label("sprint") == "快速复习"
    assert planner_mode_label("systematic") == "系统学习"


def test_chapter_contract_mentions_range_and_total_length_budget() -> None:
    config = get_planner_mode_contract("systematic")
    contract = render_planner_chapter_contract("systematic")

    assert f"{config.min_chapters}-{config.max_chapters} 章" in contract
    assert config.target_length in contract
    assert "整份知识文档的预算" in contract
    assert "不使用冒号副标题" in contract
    assert "冻结执行合同" not in contract


def test_normalize_planner_draft_uses_new_planner_fields() -> None:
    draft = normalize_planner_draft(
        _planner_payload(),
        course_id="高数",
        user_prompt="高数速成",
        requested_digest_mode="sprint",
    )

    assert draft.course_name == "高数主线重建"
    assert draft.course_icon == "sigma"
    assert draft.intent.startswith("用户想把高数")
    assert draft.summary.startswith("资料显示")
    assert draft.suggestion.startswith("如果更偏考试")
    assert draft.plan.startswith("本课程会先用极限")
    assert [chapter.title for chapter in draft.chapters] == ["任务切片 1", "任务切片 2", "任务切片 3"]


def test_normalize_planner_draft_caps_over_split_chapters() -> None:
    config = get_planner_mode_contract("sprint")
    draft = normalize_planner_draft(
        _planner_payload(chapter_count=config.max_chapters + 2),
        course_id="Python数据分析",
        user_prompt="Python 数据分析想学到能做作业",
        requested_digest_mode="sprint",
    )

    assert len(draft.chapters) == config.max_chapters
    assert [chapter.chapter_index for chapter in draft.chapters] == list(range(1, config.max_chapters + 1))
    assert any("超出章节预算后合并覆盖" in item for item in draft.chapters[-1].required_elements)
    assert "速成课" not in draft.plan
    assert "快速复习" not in draft.plan


def test_normalize_planner_draft_respects_user_requested_chapter_count() -> None:
    requested_count = get_planner_mode_contract("sprint").max_chapters + 2
    payload = _planner_payload(chapter_count=requested_count)
    payload["build_constraints"] = {
        "requested_chapter_count": requested_count,
        "chapter_count_source": "user_request",
    }

    draft = normalize_planner_draft(
        payload,
        course_id="高数",
        user_prompt="帮我改成定积分的 9 个章节",
        requested_digest_mode="sprint",
    )

    assert len(draft.chapters) == requested_count
    assert draft.build_constraints["requested_chapter_count"] == requested_count
    assert draft.build_constraints["chapter_count_source"] == "user_request"


def test_confirm_payload_enforces_max_chapter_count() -> None:
    chapters = [
        {
            "title": f"章节 {index}",
            "objective": f"处理第 {index} 个学习任务",
            "required_elements": [f"任务 {index}", f"边界 {index}"],
        }
        for index in range(1, 6)
    ]

    shaped = _ensure_chapter_count_payload(
        chapters,
        min_chapters=2,
        max_chapters=3,
        digest_mode="systematic",
        user_prompt="测试章节压缩",
        plan={"course": "测试课程"},
    )

    assert len(shaped) == 3
    assert [item["chapter_index"] for item in shaped] == [1, 2, 3]
    assert any("超出章节预算后合并覆盖" in item for item in shaped[-1]["required_elements"])


def test_confirm_payload_does_not_pad_missing_chapters_with_local_titles() -> None:
    shaped = _ensure_chapter_count_payload(
        [
            {
                "title": "矩阵",
                "objective": "讲清矩阵的基本概念。",
                "required_elements": ["矩阵定义", "矩阵运算"],
            }
        ],
        min_chapters=4,
        max_chapters=0,
        digest_mode="systematic",
        user_prompt="线性代数速成入门",
        plan={"course": "线性代数"},
    )

    assert len(shaped) == 1
    assert shaped[0]["title"] == "矩阵"


def test_planner_sse_preview_payload_exposes_new_planner_contract() -> None:
    preview = plan_draft_node._plan_preview_payload(
        {
            "course_id": "course_linear",
            "selected_file_ids": ["file_1"],
            "user_prompt": "线性代数速成入门",
            "digest_mode": "sprint",
            "planner_session_id": "session_1",
            "model_override": "deepseek-v4-flash",
            "intent": "用户要速成线性代数。",
            "summary": "资料重点是矩阵和线性方程组。",
        },
        {
            "suggestion": "可以继续改成考试冲刺。",
            "plan": "按课程目录组织线性代数速成。",
            "chapters": [
                {
                    "chapter_index": 1,
                    "title": "行列式",
                    "objective": "掌握行列式计算。",
                    "required_elements": ["行列式性质", "行列式展开"],
                }
            ],
        },
    )

    assert preview["course_id"] == "course_linear"
    assert preview["planner_session_id"] == "session_1"
    assert preview["chapters"][0]["title"] == "行列式"
    assert preview["plan"] == "按课程目录组织线性代数速成。"
    assert preview["suggestion"] == "可以继续改成考试冲刺。"
    assert preview["intent"] == "用户要速成线性代数。"
    assert preview["summary"] == "资料重点是矩阵和线性方程组。"


def test_parse_planner_response_reads_marker_protocol() -> None:
    parsed = plan_draft_node._parse_planner_response(
        f"""
{PLAN_START}
先补数与式，再进入函数和几何，最后做概率统计综合复盘。
{PLAN_END}
{SUGGESTION_START}
如果更偏中考，可以增加压轴题比例。
{SUGGESTION_END}
{CHAPTERS_START}
[
  {{"title": "数与式基础", "key_points": ["实数与代数式", "方程基本变形"]}},
  {{"title": "函数图像", "key_points": ["一次函数", "二次函数"]}}
]
{CHAPTERS_END}
"""
    )

    assert parsed["plan"].startswith("先补数与式")
    assert parsed["suggestion"].startswith("如果更偏中考")
    assert parsed["chapters"][0]["title"] == "数与式基础"
    assert parsed["chapters"][0]["required_elements"] == ["实数与代数式", "方程基本变形"]


def test_parse_planner_response_rejects_empty_chapter_points() -> None:
    with pytest.raises(ValueError, match="key_points"):
        plan_draft_node._parse_planner_response(
            f"""
{PLAN_START}一段方案。{PLAN_END}
{SUGGESTION_START}一段建议。{SUGGESTION_END}
{CHAPTERS_START}[{{"title": "计算基础", "key_points": []}}]{CHAPTERS_END}
"""
        )


def test_planner_node_streams_plan_and_builds_new_draft(monkeypatch: pytest.MonkeyPatch) -> None:
    emitted_tokens: list[str] = []
    emitted_events: list[str] = []
    raw_output = (
        f"{PLAN_START}本轮先识别目标，再组织章节和练习。{PLAN_END}"
        f"{SUGGESTION_START}可以继续改成考试冲刺。{SUGGESTION_END}"
        f'{CHAPTERS_START}[{{"title":"目标拆解","key_points":["学习范围","练习边界"]}}]{CHAPTERS_END}'
    )

    def fake_acompletion_stream(*args, **kwargs) -> Iterator[str]:
        del args, kwargs

        async def _gen():
            yield raw_output

        return _gen()

    async def fake_emit_token(state, token: str) -> None:
        del state
        emitted_tokens.append(token)

    async def fake_emit_event(state, *, event: str, detail: str, payload=None) -> None:
        del state, detail, payload
        emitted_events.append(event)

    monkeypatch.setattr(plan_draft_node, "acompletion_stream", fake_acompletion_stream)
    monkeypatch.setattr(plan_draft_node, "emit_planner_token", fake_emit_token)
    monkeypatch.setattr(plan_draft_node, "emit_planner_event", fake_emit_event)

    node = plan_draft_node.build_compose_planner_draft_node(context=object())
    result = asyncio.run(
        node(
            {
                "course_id": "course_test",
                "planner_session_id": "session_test",
                "material_context": _material_context(),
                "intent": "用户希望整理三年级数学。",
                "summary": "没有绑定上传资料，只能按目标规划。",
                "user_prompt": "三年级数学",
                "digest_mode": "sprint",
                "message_history": ["用户：三年级数学"],
            }
        )
    )

    assert "".join(emitted_tokens) == "\n\n本轮先识别目标，再组织章节和练习。"
    assert result["build_plan_draft"]["plan"] == "本轮先识别目标，再组织章节和练习。"
    assert result["build_plan_draft"]["suggestion"] == "可以继续改成考试冲刺。"
    assert result["build_plan_draft"]["chapters"][0]["title"] == "目标拆解"
    assert emitted_events == ["planner.plan.started", "planner.plan.ready"]


def test_planner_prompt_marks_revision_as_single_composer_call() -> None:
    messages = build_planner_stream_messages(
        course_name="高数",
        user_prompt="高数",
        digest_mode="sprint",
        material_context=_material_context(),
        intent="上一轮意图。",
        summary="上一轮摘要。",
        message_history=["用户：高数", "用户：帮我改成定积分的 5 个章节"],
        latest_feedback="帮我改成定积分的 5 个章节",
        latest_plan={
            "course_name": "高数主线重建",
            "course_icon": "sigma",
            "intent": "上一轮意图。",
            "summary": "上一轮摘要。",
            "suggestion": "上一轮建议。",
            "plan": "上一轮 plan。",
            "chapters": [{"title": "极限与连续", "required_elements": ["极限基础"]}],
        },
    )
    prompt = "\n".join(message["content"] for message in messages)

    assert "这是调整已有 planner，不是重新识别 intent/summary/course_name/course_icon" in prompt
    assert "你只能生成新的 suggestion、plan、chapters" in prompt
    assert "chapters 数量必须等于 N" in prompt
    assert "帮我改成定积分的 5 个章节" in prompt


def test_planner_prompt_uses_intent_summary_for_first_generation() -> None:
    messages = build_planner_stream_messages(
        course_name="初中数学",
        user_prompt="我想系统复习初中数学，请构建一门 14 天课程",
        digest_mode="systematic",
        material_context=_material_context(),
        intent="用户要按 14 天重建初中数学知识体系。",
        summary="资料覆盖数与式、方程、函数、几何和统计概率。",
        message_history=["用户：我想系统复习初中数学，请构建一门 14 天课程"],
    )
    prompt = "\n".join(message["content"] for message in messages)

    assert "这是第一次生成 planner 的第二阶段" in prompt
    assert "intent：" in prompt
    assert "summary：" in prompt
    assert "用户要按 14 天重建初中数学知识体系" in prompt
    assert PLAN_START in prompt
    assert SUGGESTION_START in prompt
    assert CHAPTERS_START in prompt
