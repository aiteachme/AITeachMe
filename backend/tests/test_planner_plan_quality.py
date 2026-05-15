import asyncio

import pytest

from app.workflows.digest.common.models import DigestMaterialContext, DigestModeDecision, DigestMode
from app.workflows.digest.planner.nodes import stream_and_parse_plan_draft as plan_draft_node
from app.workflows.digest.planner.lib.constants import get_planner_mode_contract
from app.workflows.digest.planner.lib.models import PlanIntent, PlannerBrief
from app.workflows.digest.planner.lib.plans import (
    normalize_planner_draft,
    planner_mode_label,
    render_planner_chapter_contract,
)
from app.workflows.digest.planner.lib.store import _ensure_chapter_count_payload
from app.workflows.digest.planner.prompts.build_plan_composer import build_plan_structured_messages
from app.workflows.digest.planner.prompts.plan_intent import build_plan_intent_messages
from app.workflows.digest.planner.prompts.plan_sketch import build_plan_sketch_prompt


def test_planner_mode_label_is_student_facing() -> None:
    assert planner_mode_label("sprint") == "快速复习"
    assert planner_mode_label("systematic") == "系统学习"


def test_chapter_contract_mentions_range_and_total_length_budget() -> None:
    config = get_planner_mode_contract("systematic")
    contract = render_planner_chapter_contract("systematic")

    assert f"{config.min_chapters}-{config.max_chapters} 章" in contract
    assert config.target_length in contract
    assert "整份知识文档的预算" in contract
    assert "冻结执行合同" not in contract


def test_normalize_planner_draft_caps_over_split_chapters() -> None:
    config = get_planner_mode_contract("sprint")
    raw_chapters = [
        {
            "title": f"任务切片 {index}",
            "key_points": [f"切片 {index} 的学习任务", f"切片 {index} 的边界"],
        }
        for index in range(1, config.max_chapters + 3)
    ]

    draft = normalize_planner_draft(
        {
            "plan_summary": "围绕 Python 数据分析作业目标生成一份可确认的速成课计划。",
            "plan_steps": ["确认目标", "拆分任务", "整理边界", "形成大纲"],
            "chapter_plan": raw_chapters,
        },
        course_id="Python数据分析",
        user_prompt="Python 数据分析想学到能做作业",
        requested_digest_mode="sprint",
    )

    assert len(draft.chapter_plan) == config.max_chapters
    assert [chapter.chapter_index for chapter in draft.chapter_plan] == list(range(1, config.max_chapters + 1))
    assert any("超出章节预算后合并覆盖" in item for item in draft.chapter_plan[-1].required_elements)
    assert "速成课" not in draft.plan_summary
    assert "快速复习" in draft.plan_summary


def test_normalize_planner_draft_respects_user_requested_chapter_count() -> None:
    config = get_planner_mode_contract("sprint")
    requested_count = config.max_chapters + 2
    raw_chapters = [
        {
            "title": f"定积分专题 {index}",
            "key_points": [f"定积分任务 {index}", f"定积分边界 {index}"],
        }
        for index in range(1, requested_count + 1)
    ]

    draft = normalize_planner_draft(
        {
            "plan_summary": "按用户指定把定积分专题拆成多章。",
            "build_constraints": {
                "requested_chapter_count": requested_count,
                "chapter_count_source": "user_request",
            },
            "chapter_plan": raw_chapters,
        },
        course_id="高数",
        user_prompt="帮我改成定积分的 9 个章节",
        requested_digest_mode="sprint",
    )

    assert len(draft.chapter_plan) == requested_count
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


def test_planner_sse_preview_payload_exposes_structured_plan() -> None:
    preview = plan_draft_node._plan_preview_payload(
        {
            "course_id": "course_linear",
            "selected_file_ids": ["file_1"],
            "user_prompt": "线性代数速成入门",
            "digest_mode": "sprint",
            "planner_session_id": "session_1",
            "model_override": "deepseek-v4-flash",
        },
        {
            "plan_summary": "按课程目录组织线性代数速成。",
            "plan_steps": ["确认课程范围", "按课时主题拆分"],
            "adjustment_questions": ["如果更偏考试，我会增加题型入口。"],
            "chapter_plan": [
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
    assert preview["chapter_plan"][0]["title"] == "行列式"
    assert preview["plan_steps"] == ["确认课程范围", "按课时主题拆分"]
    assert preview["adjustment_questions"] == ["如果更偏考试，我会增加题型入口。"]


def test_planner_outline_model_rejects_empty_chapter_contract() -> None:
    with pytest.raises(ValueError, match="key_points"):
        plan_draft_node.PlannerOutlineSketch.model_validate(
            {
                "plan_text": "围绕三年级数学生成一份可确认的速成计划。",
                "plan_steps": ["判断学习目标", "划定章节边界"],
                "chapters": [{"title": "计算基础", "key_points": []}],
            }
        )


def test_planner_node_uses_structured_outline_without_hidden_json(monkeypatch) -> None:
    async def fake_visible_stream(*args, **kwargs) -> str:
        return "我会先判断学习目标，再给出可调整的大纲。"

    async def fake_structured_outline(*args, **kwargs) -> plan_draft_node.PlannerOutlineSketch:
        return plan_draft_node.PlannerOutlineSketch.model_validate(
            {
                "plan_text": "围绕三年级数学生成一份可确认的速成计划。",
                "plan_steps": ["判断学习目标", "划定章节边界", "形成初步大纲"],
                "chapters": [
                    {
                        "title": "万以内加减法进退位",
                        "key_points": ["讲清数位对齐", "练习连续进位和退位"],
                    }
                ],
            }
        )

    async def fake_emit(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr(plan_draft_node, "_stream_visible_plan_response", fake_visible_stream)
    monkeypatch.setattr(plan_draft_node, "_compose_outline_sketch_with_llm", fake_structured_outline)
    monkeypatch.setattr(plan_draft_node, "emit_planner_event", fake_emit)

    node = plan_draft_node.build_stream_and_parse_plan_draft_node(context=object())
    result = asyncio.run(
        node(
            {
                "course_id": "course_test",
                "planner_session_id": "session_test",
                "material_context": object(),
                "planner_brief": {"markdown": "可见规划判断"},
                "plan_intent": {
                    "plan_intent": "内部规划意图",
                    "plan_queries": ["判断学习目标"],
                    "adjustment_options": ["如果更偏考试冲刺，我会增加题型和易错边界。"],
                },
                "user_prompt": "三年级数学",
            }
        )
    )

    assert result["plan_outline_markdown"] == "我会先判断学习目标，再给出可调整的大纲。"
    assert result["build_plan_draft"]["plan_steps"] == ["判断学习目标", "划定章节边界", "形成初步大纲"]
    assert result["build_plan_draft"]["adjustment_questions"] == [
        "如果更偏考试冲刺，我会增加题型和易错边界。"
    ]
    assert result["build_plan_draft"]["chapter_plan"][0]["title"] == "万以内加减法进退位"


def test_revision_intent_prompt_distinguishes_replacement_outline() -> None:
    material_context = DigestMaterialContext(
        course_mode_decision=DigestModeDecision(mode=DigestMode.SPRINT),
        material_digest="高数速成资料摘要",
    )
    messages = build_plan_intent_messages(
        course_name="高数",
        user_prompt="高数",
        digest_mode="sprint",
        material_context=material_context,
        message_history=["用户：帮我改成定积分的 5 个章节"],
        latest_feedback="帮我改成定积分的 5 个章节",
        latest_plan={
            "plan_summary": "上一版是高数速成全局方案",
            "chapter_plan": [
                {"title": "极限与连续", "required_elements": ["极限基础"]},
                {"title": "导数与微分", "required_elements": ["导数应用"]},
            ],
        },
    )
    prompt = "\n".join(message["content"] for message in messages)

    assert "replace_existing_outline" in prompt
    assert "requested_chapter_count" in prompt
    assert "定积分的 5 个章节" in prompt
    assert "不得保守保留旧方案" in prompt


def test_revision_brief_prompt_does_not_force_local_patch_for_explicit_replacement() -> None:
    material_context = DigestMaterialContext(
        course_mode_decision=DigestModeDecision(mode=DigestMode.SPRINT),
        material_digest="高数速成资料摘要",
    )
    prompt = build_plan_sketch_prompt(
        course_name="高数",
        user_prompt="",
        digest_mode="sprint",
        material_context=material_context,
        message_history=["用户：帮我改成定积分的 5 个章节"],
        latest_feedback="帮我改成定积分的 5 个章节",
        latest_plan={
            "plan_summary": "上一版是高数速成全局方案",
            "chapter_plan": [
                {"title": "极限与连续", "required_elements": ["极限基础"]},
                {"title": "导数与微分", "required_elements": ["导数应用"]},
            ],
        },
    )

    assert "局部补丁还是整体重定向" in prompt
    assert "整体重定向时不要说保留旧章节" in prompt
    assert "改成 XXX 的 N 个章节" in prompt
    assert "不要继续套用保留旧章节的局部补丁逻辑" in prompt


def test_structured_plan_replacement_prompt_requires_exact_count_and_drops_old_chapters() -> None:
    material_context = DigestMaterialContext(
        course_mode_decision=DigestModeDecision(mode=DigestMode.SPRINT),
        material_digest="高数速成资料摘要",
    )
    plan_intent = PlanIntent(
        plan_intent="用户要求把上一版高数方案改成定积分 5 章。",
        plan_change_mode="replace_existing_outline",
        target_scope="定积分",
        scope_decision="本轮是范围重定向，上一版旧章节只作为上下文。",
        requested_chapter_count=5,
        chapter_count_guidance="严格 5 章。",
        plan_queries=["定积分定义与几何意义", "定积分基本定理", "定积分典型计算"],
    )
    messages = build_plan_structured_messages(
        course_name="高数",
        user_prompt="高数",
        digest_mode="sprint",
        material_context=material_context,
        planner_brief=PlannerBrief(markdown="应围绕定积分重排。"),
        plan_intent=plan_intent,
        message_history=["用户：帮我改成定积分的 5 个章节"],
        latest_feedback="帮我改成定积分的 5 个章节",
        latest_plan={
            "plan_summary": "上一版是高数速成全局方案",
            "chapter_plan": [
                {"title": "极限与连续", "required_elements": ["极限基础"]},
                {"title": "导数与微分", "required_elements": ["导数应用"]},
                {"title": "级数判别", "required_elements": ["级数"]},
            ],
        },
    )
    prompt = "\n".join(message["content"] for message in messages)

    assert "chapters 数量必须严格等于用户指定的 5 章" in prompt
    assert "上一版方案 JSON 只能作为上下文和被替换对象" in prompt
    assert "不能保留极限、导数、级数、多元微分等旧章节" in prompt


def test_structured_plan_patch_prompt_requires_visible_focus_changes() -> None:
    material_context = DigestMaterialContext(
        course_mode_decision=DigestModeDecision(mode=DigestMode.SPRINT),
        material_digest="线性代数速成资料摘要",
    )
    plan_intent = PlanIntent(
        plan_intent="用户希望上一版线代方案主要讲矩阵和特征值。",
        plan_change_mode="patch_existing",
        target_scope="线性代数",
        scope_decision="本轮是重点调整，不是换成新专题。",
        plan_queries=["定位矩阵和特征值相关章节", "压缩低优先级章节", "改写相关 key_points"],
    )
    messages = build_plan_structured_messages(
        course_name="线性代数",
        user_prompt="线性代数",
        digest_mode="sprint",
        material_context=material_context,
        planner_brief=PlannerBrief(markdown="应把重点转到矩阵和特征值。"),
        plan_intent=plan_intent,
        message_history=["用户：线性代数", "助手：上一版线性代数速成方案", "用户：主要讲矩阵和特征值吧！"],
        latest_feedback="主要讲矩阵和特征值吧！",
        latest_plan={
            "plan_summary": "上一版是线性代数速成方案",
            "chapter_plan": [
                {"title": "向量、矩阵与线性方程组的基本语言", "required_elements": ["向量", "矩阵", "线性方程组"]},
                {"title": "矩阵运算与初等变换", "required_elements": ["矩阵运算", "初等变换"]},
                {"title": "特征值、特征向量与对角化", "required_elements": ["特征值", "对角化"]},
            ],
        },
    )
    prompt = "\n".join(message["content"] for message in messages)

    assert "不能只在 plan_text 宣称重心变化" in prompt
    assert "chapters 的顺序、章节取舍或相关 key_points" in prompt
    assert "chapters 也必须体现权重、顺序、取舍或 key_points 的变化" in prompt


def test_structured_plan_prompt_requires_course_catalog_titles() -> None:
    material_context = DigestMaterialContext(
        course_mode_decision=DigestModeDecision(mode=DigestMode.SPRINT),
        material_digest="线性代数速成资料摘要",
    )
    plan_intent = PlanIntent(
        plan_intent="用户想要线性代数速成入门。",
        target_scope="线性代数",
        scope_decision="本轮是完整课程范围，应按课程目录课时主题拆分。",
        chapter_split_guidance="按课程目录/课时主题拆分，不按抽象学习动作拆分。",
        plan_queries=["行列式", "矩阵", "线性方程组", "特征值"],
    )
    messages = build_plan_structured_messages(
        course_name="线性代数",
        user_prompt="线性代数速成入门",
        digest_mode="sprint",
        material_context=material_context,
        planner_brief=PlannerBrief(markdown="应围绕线性代数速成规划。"),
        plan_intent=plan_intent,
    )
    prompt = "\n".join(message["content"] for message in messages)

    assert "章节标题合同" in prompt
    assert "title 是课程目录标题，不是学习策略句" in prompt
    assert "key_points 才写学习动作" in prompt
    assert "本地代码不会做关键词提取" in prompt
    assert "行列式、矩阵、初等变换、向量、线性方程组、特征值、二次型" in prompt
