from app.workflows.digest.common import pedagogy
from app.workflows.digest.docgen.lib.chapter_enhancement import (
    _append_practice_section,
    _append_problem_pattern_section,
)
from app.workflows.digest.docgen.prompts.chapter_review import build_chapter_review_messages
from app.workflows.digest.docgen.prompts.generation import build_docgen_writer_messages


def test_chapter_title_resolution_rejects_templates_and_derives_specific_titles() -> None:
    assert pedagogy.clean_generated_chapter_title("第 03 章：核心概念总览") == "核心概念总览"
    assert pedagogy.looks_like_generic_template_title("核心概念") is True
    assert pedagogy.is_usable_resolved_chapter_title("Chapter 2") is False

    title = pedagogy.resolve_effective_chapter_title(
        {
            "title": "第 2 章",
            "required_elements": ["矩阵分解：奇异值分解和低秩近似"],
            "summary": "本章说明特征值如何支撑降维。",
        },
        chapter_index=2,
    )
    assert title == "矩阵分解：奇异值分解和低秩近似"

    assert (
        pedagogy.coerce_resolved_chapter_title(
            "章节目标",
            chapter={"resolved_title": "矩阵分解：奇异值分解和低秩近似"},
            chapter_index=2,
        )
        == "矩阵分解：奇异值分解和低秩近似"
    )


def test_document_overview_dedupes_chapters_and_hides_course_ids() -> None:
    chapters = [
        {"chapter_index": 1, "title": "核心概念总览", "summary": "short"},
        {"chapter_index": 1, "title": "矩阵分解", "summary": "longer summary wins"},
        {"chapter_index": 2, "resolved_title": "特征值应用", "summary": "x"},
        {"chapter_index": 3, "title": "第 3 章", "required_elements": ["正交投影：最小二乘几何解释"]},
    ]

    overview = pedagogy.build_document_overview(
        course_name="course_linear_algebra",
        digest_mode="sprint",
        user_prompt="",
        plan_summary="",
        source_strategy="",
        chapters=chapters,
    )

    assert "《当前课程》" in overview
    assert "共 3 章" in overview
    assert "矩阵分解、特征值应用、正交投影：最小二乘几何解释" in overview
    assert "核心概念总览" not in overview


def test_heading_quality_detects_duplicate_generic_titles() -> None:
    quality = pedagogy.analyze_chapter_heading_quality(
        "# 线性代数\n\n## 核心概念\nA\n\n## 核心概念\nB",
        digest_mode="systematic",
    )

    assert quality["digest_mode"] == "systematic"
    assert quality["h2_count"] == 2
    assert quality["duplicate_titles"] == ["核心概念"]
    assert quality["generic_titles"] == ["核心概念", "核心概念"]
    assert quality["needs_agent_repair"] is True
    assert quality["needs_scaffold_fallback"] is False
    assert {"guide", "objectives", "recap"} <= set(quality["missing_modules"])


def test_learning_scaffold_inserts_required_sections_without_duplication() -> None:
    scaffold = pedagogy.ensure_chapter_learning_scaffold(
        "只有一段内容",
        title="矩阵分解",
        objective="掌握矩阵分解",
        required_elements=["奇异值分解", "低秩近似"],
        digest_mode="sprint",
        source_count=2,
    )
    repeated = pedagogy.ensure_chapter_learning_scaffold(
        scaffold,
        title="矩阵分解",
        objective="掌握矩阵分解",
        required_elements=["奇异值分解", "低秩近似"],
        digest_mode="sprint",
        source_count=2,
    )

    assert scaffold.startswith("# 矩阵分解\n")
    assert "> [!TIP]" in scaffold
    assert "奇异值分解" in scaffold
    assert "低秩近似" in scaffold
    assert scaffold.count("核心总结") == 1
    assert repeated.count("核心总结") == 1
    assert repeated.count("> [!TIP]") == 1


def test_systematic_mode_sections_add_position_and_extension_boundaries() -> None:
    first_chapter_keys = [
        key
        for key, _heading, _block in pedagogy._build_mode_sections(
            title="矩阵分解",
            objective="理解矩阵分解在课程中的位置",
            required_elements=["奇异值分解", "低秩近似"],
            digest_mode="systematic",
            chapter_index=1,
            chapter_count=3,
        )
    ]
    final_chapter_keys = [
        key
        for key, _heading, _block in pedagogy._build_mode_sections(
            title="综合应用",
            objective="串联课程知识",
            required_elements=["综合题", "迁移应用"],
            digest_mode="systematic",
            chapter_index=3,
            chapter_count=3,
        )
    ]

    assert "map" in first_chapter_keys
    assert "extension" not in first_chapter_keys
    assert "map" not in final_chapter_keys
    assert "extension" in final_chapter_keys


def test_sprint_practice_supplement_repairs_weak_existing_practice_heading() -> None:
    markdown = "# 矩阵分解\n\n## 练习与自检\n\n- 复习一下奇异值分解。\n"
    questions = [
        {
            "label": "奇异值分解",
            "stem": "判断一个矩阵是否适合用奇异值分解做低秩近似。",
            "analysis_steps": ["先看矩阵和目标。", "再选择分解路径。"],
            "pitfall": "不能只看矩阵大小，还要看近似目标。",
        },
        {
            "label": "低秩近似",
            "stem": "给定保留阶数，说明如何判断近似是否足够。",
            "analysis_steps": ["先看保留的奇异值。", "再检查误差要求。"],
            "pitfall": "只保留最大的项不等于一定满足误差要求。",
        },
        {
            "label": "误差判断",
            "stem": "比较两个低秩近似方案，选出更稳妥的一种。",
            "analysis_steps": ["先比较目标。", "再比较误差和信息损失。"],
            "pitfall": "不要把计算方便当成误差更小。",
        },
    ]

    supplemented = _append_practice_section(
        markdown,
        questions,
        digest_mode="sprint",
        title="矩阵分解",
    )

    assert supplemented != markdown
    assert supplemented.count("> **例题") >= 3
    assert "> [!IMPORTANT]" in supplemented
    assert "**题目**" in supplemented
    assert "**解析**" in supplemented
    assert "**易错点**" in supplemented


def test_sprint_practice_supplement_only_fills_missing_example_gap() -> None:
    markdown = """# 矩阵分解

## 练习与自检

### 例题 1：奇异值分解

**题目**：判断一个矩阵是否适合用奇异值分解做低秩近似。

**解析**：先看矩阵和目标。

**易错点**：不能只看矩阵大小。

### 例题 2：低秩近似

**题目**：给定保留阶数，说明如何判断近似是否足够。

**解析**：先看保留的奇异值。

**易错点**：不要忽略误差要求。
"""
    questions = [
        {
            "label": "奇异值分解",
            "stem": "判断一个矩阵是否适合用奇异值分解做低秩近似。",
            "analysis_steps": ["先看矩阵和目标。", "再选择分解路径。"],
            "pitfall": "不能只看矩阵大小，还要看近似目标。",
        },
        {
            "label": "低秩近似",
            "stem": "给定保留阶数，说明如何判断近似是否足够。",
            "analysis_steps": ["先看保留的奇异值。", "再检查误差要求。"],
            "pitfall": "只保留最大项不等于一定满足误差要求。",
        },
        {
            "label": "误差判断",
            "stem": "比较两个低秩近似方案，选出更稳妥的一种。",
            "analysis_steps": ["先比较目标。", "再比较误差和信息损失。"],
            "pitfall": "不要把计算方便当成误差更小。",
        },
    ]

    supplemented = _append_practice_section(
        markdown,
        questions,
        digest_mode="sprint",
        title="矩阵分解",
    )

    assert supplemented != markdown
    assert supplemented.count("### 例题") + supplemented.count("> **例题") == 3
    assert "误差判断" in supplemented


def test_sprint_problem_pattern_section_adds_question_type_table() -> None:
    markdown = "# 矩阵分解\n\n## 核心内容\n\n奇异值分解可用于低秩近似。\n"
    questions = [
        {
            "label": "奇异值分解",
            "stem": "判断一个矩阵是否适合用奇异值分解做低秩近似。",
            "analysis_steps": ["先看矩阵和目标。", "再选择分解路径。", "最后检查误差要求。"],
            "pitfall": "不能只看矩阵大小，还要看近似目标。",
        },
        {
            "label": "低秩近似",
            "stem": "给定保留阶数，说明如何判断近似是否足够。",
            "analysis_steps": ["先看保留的奇异值。", "再检查误差要求。"],
            "pitfall": "只保留最大项不等于一定满足误差要求。",
        },
    ]

    supplemented = _append_problem_pattern_section(
        markdown,
        questions,
        digest_mode="sprint",
        title="矩阵分解",
    )

    assert supplemented != markdown
    assert "题型归纳与速练" in supplemented
    assert "| 题型/任务 | 题眼信号 | 处理模板 | 易错诊断 |" in supplemented
    assert "奇异值分解" in supplemented
    assert "先看矩阵和目标" in supplemented
    assert _append_problem_pattern_section(markdown, questions, digest_mode="systematic", title="矩阵分解") == markdown


def test_sprint_problem_pattern_section_does_not_accept_keyword_only_heading() -> None:
    markdown = "# 矩阵分解\n\n## 题型归纳\n\n本章要注意题眼、处理模板和易错诊断。\n"
    questions = [
        {
            "label": "奇异值分解",
            "stem": "判断一个矩阵是否适合用奇异值分解做低秩近似。",
            "analysis_steps": ["先看矩阵和目标。", "再选择分解路径。"],
            "pitfall": "不能只看矩阵大小，还要看近似目标。",
        }
    ]

    supplemented = _append_problem_pattern_section(
        markdown,
        questions,
        digest_mode="sprint",
        title="矩阵分解",
    )

    assert supplemented != markdown
    assert "| 题型/任务 | 题眼信号 | 处理模板 | 易错诊断 |" in supplemented
    assert "奇异值分解" in supplemented


def test_sprint_writer_prompt_requires_quick_reference_and_structured_examples() -> None:
    messages = build_docgen_writer_messages(
        title="矩阵分解",
        objective="掌握奇异值分解和低秩近似。",
        digest_mode="sprint",
        required_elements=["奇异值分解", "低秩近似"],
        writing_instructions="",
        source_count=1,
        dense_context="奇异值分解可用于低秩近似。",
        execution_contract={
            "practice_quota": {"worked_examples": 4, "self_check": 2},
            "example_density_policy": {"policy_text": "高密度例题"},
        },
    )
    prompt = messages[-1]["content"]

    assert "速查表或判断表" in prompt
    assert "题型归纳表" in prompt
    assert "> [!IMPORTANT]" in prompt
    assert "> [!WARNING]" in prompt
    assert "不能反复复用章节标题" in prompt
    assert "题目/案例-解析-易错点" in prompt
    assert "不要只写“请自行练习”" in prompt


def test_sprint_review_prompt_requires_problem_pattern_structure() -> None:
    messages = build_chapter_review_messages(
        chapter_title="矩阵分解",
        digest_mode="sprint",
        chapter_task={"confirmed_title": "矩阵分解"},
        markdown="# 矩阵分解\n\n## 核心内容\n\n奇异值分解可用于低秩近似。",
        claim_ledger={},
        claim_evidence_map={},
        conflict_report={},
        rule_review={},
    )
    prompt = messages[-1]["content"]

    assert "题型归纳" in prompt
    assert "题眼信号" in prompt
    assert "处理模板" in prompt
    assert "易错诊断" in prompt
