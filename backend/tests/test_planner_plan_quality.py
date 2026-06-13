import asyncio
from collections.abc import Iterator

import pytest

from app.workflows.digest.common.models import DigestMaterialContext, DigestMode, DigestModeDecision
from app.workflows.digest.planner.lib.constants import get_planner_mode_contract
from app.workflows.digest.planner.lib.plans import (
    normalize_planner_draft,
    planner_mode_label,
)
from app.workflows.digest.planner.lib.store import _ensure_chapter_count_payload
from app.workflows.digest.planner.nodes import compose_planner_draft as plan_draft_node
from app.workflows.digest.planner.prompts.build_plan_composer import (
    CHAPTERS_END,
    CHAPTERS_START,
    DIAGNOSE_END,
    DIAGNOSE_START,
    PLAN_END,
    PLAN_START,
    SUGGESTION_END,
    SUGGESTION_START,
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
        "planning_note": "用户想把高数混乱知识整理成可执行复习路径。\n资料显示当前重点集中在极限、导数和积分。",
        "suggestion": "如果更偏考试，可以增加题型和易错点密度。",
        "plan": "本课程会先用极限建立函数变化的基础，再进入导数规则与应用，最后把积分计算和综合题串起来。",
        "diagnose": [
            {
                "question": "极限、导数、积分里你现在最怕哪一块？",
                "purpose": "识别高数复习的第一薄弱入口。",
                "sample_answers": ["极限定义", "导数应用", "积分计算"],
            }
        ],
        "chapters": [
            {
                "title": f"任务切片 {index}",
                "key_points": [f"切片 {index} 的学习任务", f"切片 {index} 的边界"],
            }
            for index in range(1, chapter_count + 1)
        ],
    }


def test_planner_mode_label_is_student_facing() -> None:
    assert planner_mode_label("sprint") == "紧凑节奏"
    assert planner_mode_label("systematic") == "系统节奏"


def test_normalize_planner_draft_uses_new_planner_fields() -> None:
    draft = normalize_planner_draft(
        _planner_payload(),
        course_id="高数",
        user_prompt="高数速成",
        requested_digest_mode="sprint",
    )

    assert draft.course_name == "高数主线重建"
    assert draft.course_icon == "sigma"
    assert draft.planning_note.startswith("用户想把高数")
    assert "资料显示" in draft.planning_note
    assert draft.suggestion.startswith("如果更偏考试")
    assert draft.plan.startswith("本课程会先用极限")
    assert [chapter.title for chapter in draft.chapters] == ["任务切片 1", "任务切片 2", "任务切片 3"]
    assert draft.diagnose[0].question == "极限、导数、积分里你现在最怕哪一块？"
    assert draft.diagnose[0].sample_answers == ["极限定义", "导数应用", "积分计算"]


def test_normalize_planner_draft_builds_fallback_diagnose() -> None:
    payload = _planner_payload()
    payload.pop("diagnose")

    draft = normalize_planner_draft(
        payload,
        course_id="高数",
        user_prompt="高数速成",
        requested_digest_mode="sprint",
    )

    assert len(draft.diagnose) == 10
    assert draft.diagnose[0].question.startswith("看到“任务切片 1”")
    assert len(draft.diagnose[0].sample_answers) >= 3


def test_normalize_planner_draft_does_not_use_full_prompt_as_course_name() -> None:
    payload = _planner_payload()
    payload.pop("course_name")

    draft = normalize_planner_draft(
        payload,
        course_id="course_titlefallback",
        user_prompt="我想学习初中几何，按平行线与角、三角形全等、圆与切线生成 3 个章节",
        requested_digest_mode="sprint",
    )

    assert draft.course_name == "初中几何"


def test_normalize_planner_draft_caps_over_split_chapters() -> None:
    config = get_planner_mode_contract("sprint")
    payload = _planner_payload(chapter_count=config.max_chapters + 2)
    payload["plan"] = "这门速成课会先补关键概念，再把典型题串起来。"
    draft = normalize_planner_draft(
        payload,
        course_id="Python数据分析",
        user_prompt="Python 数据分析想学到能做作业",
        requested_digest_mode="sprint",
    )

    assert len(draft.chapters) == config.max_chapters
    assert [chapter.chapter_index for chapter in draft.chapters] == list(range(1, config.max_chapters + 1))
    assert any("超出章节预算后合并覆盖" in item for item in draft.chapters[-1].required_elements)
    assert "速成课" not in draft.plan
    assert "紧凑节奏" in draft.plan


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


def test_normalize_planner_draft_respects_exact_chapter_count_from_user_text() -> None:
    payload = _planner_payload(chapter_count=5)
    payload.pop("course_name")

    draft = normalize_planner_draft(
        payload,
        course_id="course_titlefallback",
        user_prompt="我想学习初中函数，请构建一门 2 章课程，每章要有例题和易错点。",
        requested_digest_mode="sprint",
    )

    assert draft.course_name == "初中函数"
    assert len(draft.chapters) == 2
    assert draft.build_constraints["requested_chapter_count"] == 2
    assert draft.build_constraints["chapter_count_source"] == "user_request"


def test_normalize_planner_draft_aligns_explicit_chapter_titles() -> None:
    payload = _planner_payload(chapter_count=5)
    payload.pop("course_name")

    draft = normalize_planner_draft(
        payload,
        course_id="course_titlefallback",
        user_prompt=(
            "我想学习初中函数，请构建一门 2 章课程："
            "第 1 章函数概念与自变量取值，第 2 章一次函数图像与斜率截距。"
            "每章要有清晰图示、例题、易错点和单元测试。"
        ),
        requested_digest_mode="sprint",
    )

    assert draft.course_name == "初中函数"
    assert [chapter.title for chapter in draft.chapters] == [
        "函数概念与自变量取值",
        "一次函数图像与斜率截距",
    ]
    assert len(draft.chapters) == 2
    assert "函数概念与自变量取值" in draft.plan
    assert "一次函数图像与斜率截距" in draft.plan


def test_normalize_planner_draft_respects_user_requested_chapter_range() -> None:
    payload = _planner_payload(chapter_count=9)

    draft = normalize_planner_draft(
        payload,
        course_id="高数",
        user_prompt="我要学习大学高等数学上册，请拆成 8-10 章，每章给出知识框架和练习。",
        requested_digest_mode="sprint",
    )

    assert len(draft.chapters) == 9
    assert draft.build_constraints["requested_chapter_min"] == 8
    assert draft.build_constraints["requested_chapter_max"] == 10
    assert draft.build_constraints["chapter_count_source"] == "user_request_range"
    assert not any("超出章节预算后合并覆盖" in item for item in draft.chapters[-1].required_elements)


def test_normalize_planner_draft_does_not_treat_duration_as_chapter_range() -> None:
    config = get_planner_mode_contract("sprint")

    draft = normalize_planner_draft(
        _planner_payload(chapter_count=config.max_chapters + 2),
        course_id="高数",
        user_prompt="我要学习大学高等数学上册，请构建一门 4 周系统课程。",
        requested_digest_mode="sprint",
    )

    assert len(draft.chapters) == config.max_chapters
    assert draft.build_constraints.get("chapter_count_source") != "user_request_range"


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
            "model_override": "gpt-5.5",
            "planning_note": "用户要速成线性代数。",
            "material_note": "资料重点是矩阵和线性方程组。",
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
    assert preview["planning_note"] == "用户要速成线性代数。\n资料重点是矩阵和线性方程组。"


def test_parse_planner_response_reads_marker_protocol() -> None:
    parsed = plan_draft_node._parse_planner_response(
        f"""
{PLAN_START}
先补数与式，再进入函数和几何，最后完成概率统计应用。
{PLAN_END}
{SUGGESTION_START}
如果更偏中考，可以增加压轴题比例。
{SUGGESTION_END}
{DIAGNOSE_START}
[
  {{"question": "函数图像里你最容易混淆什么？", "purpose": "定位函数薄弱点", "sample_answers": ["一次函数", "二次函数", "图像变换"]}}
]
{DIAGNOSE_END}
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
    assert parsed["diagnose"][0]["question"] == "函数图像里你最容易混淆什么？"
    assert parsed["diagnose"][0]["sample_answers"] == ["一次函数", "二次函数", "图像变换"]
    assert parsed["chapters"][0]["title"] == "数与式基础"
    assert parsed["chapters"][0]["required_elements"] == ["实数与代数式", "方程基本变形"]


def test_partial_chapters_supports_streaming_preview() -> None:
    chapters = plan_draft_node._partial_chapters(
        f'{CHAPTERS_START}[{{"title":"数与式","key_points":["代数式","方程"]}},{{"title":"函数图像","key_points":["一次函数"'
    )

    assert [chapter["title"] for chapter in chapters] == ["数与式", "函数图像"]
    assert chapters[0]["required_elements"] == ["代数式", "方程"]
    assert chapters[1]["objective"] == "一次函数"


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
    emitted_events: list[tuple[str, dict | None]] = []
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
        del state, detail
        emitted_events.append((event, payload))

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
                "planning_note": "用户希望整理三年级数学。",
                "material_note": "没有绑定上传资料，只能按目标规划。",
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
    assert [event for event, _payload in emitted_events] == [
        "planner.plan.started",
        "planner.suggestion.started",
        "planner.chapters.started",
        "planner.chapters.progress",
        "planner.plan.ready",
    ]
    progress_payload = emitted_events[3][1]
    assert progress_payload is not None
    assert progress_payload["partial_chapter_count"] == 1
    assert progress_payload["plan_preview"]["plan"] == "本轮先识别目标，再组织章节和练习。"
    assert progress_payload["plan_preview"]["chapters"][0]["title"] == "目标拆解"
