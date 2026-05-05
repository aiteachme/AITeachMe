from app.workflows.digest.common.runtime_config import get_planner_mode_runtime_config
from app.workflows.digest.planner.lib.plans import (
    build_supplement_chapter_payload,
    normalize_planner_draft,
    planner_mode_label,
    render_planner_chapter_contract,
)
from app.workflows.digest.planner.lib.store import _ensure_chapter_count_payload, _ensure_min_chapter_payload


def test_supplement_chapter_payload_uses_task_oriented_sprint_language() -> None:
    payload = build_supplement_chapter_payload(
        index=2,
        topic="Python 数据分析想学到能做作业，需要先会读取和清洗数据",
        digest_mode="sprint",
        user_prompt="Python 数据分析想学到能做作业",
    )

    assert payload["title"].startswith("Python 数据分析")
    assert len(payload["title"]) <= 18
    assert "高频考点" not in "；".join(payload["required_elements"])
    assert "典型题型" not in "；".join(payload["required_elements"])
    assert any("常见任务/题型" in item for item in payload["required_elements"])
    assert any("用户目标" in item for item in payload["required_elements"])


def test_confirm_padding_builds_contextual_chapter_titles() -> None:
    padded = _ensure_min_chapter_payload(
        [],
        min_chapters=3,
        digest_mode="systematic",
        user_prompt="Python 数据分析想学到能做作业",
        plan={"course": "Python数据分析"},
    )

    titles = [item["title"] for item in padded]
    assert titles == ["Python数据分析学习边界", "Python数据分析关键对象", "Python数据分析结构关系"]
    assert all("核心概念总览" not in title for title in titles)
    assert all("Python 数据分析想学到能做作业" not in "；".join(item["required_elements"]) for item in padded)


def test_planner_mode_label_is_student_facing() -> None:
    assert planner_mode_label("sprint") == "速成课"
    assert planner_mode_label("systematic") == "系统课"


def test_chapter_contract_mentions_range_and_total_length_budget() -> None:
    config = get_planner_mode_runtime_config("systematic")
    contract = render_planner_chapter_contract("systematic")

    assert f"{config.min_chapters}-{config.max_chapters} 章" in contract
    assert config.target_length in contract
    assert "整份知识文档的预算" in contract
    assert "冻结执行合同" not in contract


def test_normalize_planner_draft_caps_over_split_chapters() -> None:
    config = get_planner_mode_runtime_config("sprint")
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
