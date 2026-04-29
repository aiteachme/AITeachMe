from app.workflows.digest.planner.lib.plans import build_supplement_chapter_payload
from app.workflows.digest.planner.lib.plans import planner_mode_label
from app.workflows.digest.planner.lib.store import _ensure_min_chapter_payload


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
    assert planner_mode_label("sprint") == "冲刺型"
    assert planner_mode_label("systematic") == "系统型"
