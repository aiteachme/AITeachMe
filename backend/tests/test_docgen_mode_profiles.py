from app.workflows.digest.common.pedagogy import clean_generated_chapter_title
from app.workflows.digest.docgen.lib.chapter_enhancement import _append_practice_section
from app.workflows.digest.docgen.mode_profiles import get_docgen_mode_profile
from app.workflows.digest.docgen.prompts.generation import build_docgen_writer_messages
from app.workflows.digest.docgen.lib.textbook_style import normalize_textbook_headings


def test_docgen_mode_profile_uses_flexible_course_hints():
    for mode in ("sprint", "systematic"):
        profile = get_docgen_mode_profile(mode)
        joined = "\n".join([*profile.chapter_format, *profile.course_flow_hints])

        assert "本章自检" not in joined
        assert profile.course_flow_hints
        assert profile.practice_focuses


def test_docgen_mode_profile_splits_total_target_length_by_chapter_count():
    sprint = get_docgen_mode_profile("sprint")
    systematic = get_docgen_mode_profile("systematic")

    assert sprint.word_budget(
        chapter_count=5,
        depth_level="standard",
        target_length="10000-20000字",
    ) == (2000, 4000)
    assert sprint.word_budget(
        chapter_count=5,
        depth_level="standard",
        target_length="1w-2w字",
    ) == (2000, 4000)
    assert systematic.word_budget(
        chapter_count=10,
        depth_level="deep",
        target_length="2w到5w字",
    ) == (2000, 5000)


def test_writer_prompt_marks_course_flow_as_non_required():
    messages = build_docgen_writer_messages(
        title="行列式",
        objective="理解行列式计算",
        digest_mode="sprint",
        required_elements=["行列式性质"],
        writing_instructions="",
        source_count=1,
        dense_context="行列式性质与计算例题。",
        chapter_index=1,
        chapter_count=3,
    )

    prompt = messages[-1]["content"]
    assert "课程化节奏" in prompt
    assert "不是固定目录" in prompt
    assert "不要为了凑齐参考模块而硬塞小节" in prompt


def test_append_practice_section_uses_mode_specific_headings():
    questions = [
        {
            "label": "行列式性质",
            "stem": "已知一个三阶行列式，判断交换两行后符号如何变化。",
            "analysis_steps": ["识别操作类型。", "调用行列式交换两行变号的性质。"],
            "pitfall": "不要把交换两行和倍乘某一行混在一起。",
        }
    ]

    sprint = _append_practice_section("# 行列式\n\n正文", questions, digest_mode="sprint", title="行列式")
    systematic = _append_practice_section("# 行列式\n\n正文", questions, digest_mode="systematic", title="行列式")

    assert "## 行列式性质的典型例题解析" in sprint
    assert "**题目**" in sprint
    assert "**解析**" in sprint
    assert "**易错点**" in sprint
    assert "## 行列式性质的例题与迁移" in systematic


def test_textbook_heading_policy_rewrites_low_information_headings_by_shape():
    markdown = """# 行列式

## 本章要点

正文

### 本章问题

问题

## 行列式的性质与计算

正文
"""

    normalized = normalize_textbook_headings(
        markdown,
        digest_mode="sprint",
        fallback_title="行列式",
        focus_items=["行列式性质"],
    )

    assert "## 行列式性质的核心要点" in normalized
    assert "### 行列式性质的典型判断问题" in normalized
    assert "## 行列式的性质与计算" in normalized


def test_docgen_title_cleaning_strips_display_numbering():
    assert clean_generated_chapter_title("1. 条件概率与独立性") == "条件概率与独立性"
    assert clean_generated_chapter_title("(1). 条件概率与独立性") == "条件概率与独立性"
    assert clean_generated_chapter_title("（一）条件概率与独立性") == "条件概率与独立性"
    assert clean_generated_chapter_title("一、条件概率与独立性") == "条件概率与独立性"
    assert clean_generated_chapter_title("第 1 章 条件概率与独立性") == "条件概率与独立性"
    assert clean_generated_chapter_title("第一章 条件概率与独立性") == "条件概率与独立性"
    assert clean_generated_chapter_title("1.1 条件概率与独立性") == "条件概率与独立性"
    assert clean_generated_chapter_title("2-范数") == "2-范数"


def test_textbook_heading_policy_strips_display_numbering_only_from_headings():
    markdown = """# 1. 条件概率与独立性

## (1). 条件概率的定义

正文

### 一、独立性的判定方法

1. 这个有序列表应该保留编号。

```python
# 1. 代码注释里的编号也应该保留
```
"""

    normalized = normalize_textbook_headings(
        markdown,
        digest_mode="systematic",
        fallback_title="条件概率与独立性",
        focus_items=["条件概率", "独立性"],
    )

    assert "# 条件概率与独立性" in normalized
    assert "## 条件概率的定义" in normalized
    assert "### 独立性的判定方法" in normalized
    assert "1. 这个有序列表应该保留编号。" in normalized
    assert "# 1. 代码注释里的编号也应该保留" in normalized

    fallback_normalized = normalize_textbook_headings(
        "# 第 1 章\n\n正文",
        digest_mode="systematic",
        fallback_title="第 1 章",
        focus_items=[],
    )
    assert fallback_normalized.startswith("# 未命名章节")

    h2_fallback_normalized = normalize_textbook_headings(
        "## 第 1 章\n\n正文",
        digest_mode="systematic",
        fallback_title="第 1 章",
        focus_items=[],
    )
    assert h2_fallback_normalized.startswith("## 本章内容")
