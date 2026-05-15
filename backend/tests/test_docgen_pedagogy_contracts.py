from app.workflows.digest.common import pedagogy
from app.workflows.digest.docgen.lib.chapter_enhancement import (
    _append_practice_section,
    _build_practice_questions,
    _ensure_requested_placeholders,
    _minimum_visible_examples,
)
from app.workflows.digest.docgen.lib.chapter_review import _rule_review_chapter
from app.workflows.digest.docgen.lib.models import ChapterDraft, ChapterGenerationTask, EnhancedChapterDraft
from app.workflows.digest.docgen.lib.textbook_style import normalize_textbook_headings
from app.workflows.digest.docgen.prompts.chapter_review import build_chapter_review_messages
from app.workflows.digest.docgen.prompts.generation import (
    build_docgen_heading_repair_messages,
    build_docgen_writer_messages,
)


def test_chapter_title_resolution_keeps_model_titles_without_local_derivation() -> None:
    assert pedagogy.clean_generated_chapter_title("第 03 章：核心概念总览") == "核心概念总览"
    assert pedagogy.is_usable_resolved_chapter_title("Chapter 2") is False

    title = pedagogy.resolve_effective_chapter_title(
        {
            "title": "第 2 章",
            "required_elements": ["矩阵分解：奇异值分解和低秩近似"],
            "summary": "本章说明特征值如何支撑降维。",
        },
        chapter_index=2,
    )
    assert title == "第 2 章"

    assert (
        pedagogy.coerce_resolved_chapter_title(
            "章节目标",
            chapter={"resolved_title": "矩阵分解：奇异值分解和低秩近似"},
            chapter_index=2,
        )
        == "矩阵分解：奇异值分解和低秩近似"
    )


def test_title_resolution_prompt_uses_generalizable_examples_not_math_wordlist() -> None:
    messages = pedagogy.build_chapter_title_resolution_messages(
        course_name="产品设计",
        digest_mode="systematic",
        objective="讲清用户访谈后的需求收敛与方案取舍。",
        required_elements=["用户访谈", "需求归纳", "方案取舍"],
        search_queries=["需求分析", "原型评审"],
        writing_instructions="标题要像真实课程目录。",
        dense_context="本章讨论从访谈记录到可执行方案的判断过程。",
        source_titles=["用户研究笔记"],
        local_hits=2,
        web_hits=0,
    )
    prompt = "\n".join(message["content"] for message in messages)

    assert "标题示例只展示" in prompt
    assert "不是候选词表" in prompt
    assert "不能照抄" in prompt
    assert "如果本章不属于这些领域" in prompt
    assert "现金流表" in prompt
    assert "洛必达法则" not in prompt


def test_mermaid_placeholder_not_added_when_writer_already_rendered_diagram() -> None:
    markdown = "# Hardware\n\n```mermaid\ngraph TD\n  A[CPU] --> B[Memory]\n```\n"
    rendered = _ensure_requested_placeholders(
        markdown,
        [{"kind": "mermaid", "description": "hardware relation diagram"}],
    )

    assert rendered == markdown
    assert rendered.count("```mermaid") == 1
    assert "ATM_DOCGEN_ASSET_REQUEST" not in rendered


def test_document_overview_dedupes_chapters_and_hides_course_ids() -> None:
    chapters = [
        {"chapter_index": 1, "title": "核心概念总览", "summary": "short"},
        {"chapter_index": 1, "title": "矩阵分解", "summary": "longer summary wins"},
        {"chapter_index": 2, "resolved_title": "特征值应用", "summary": "x"},
        {"chapter_index": 3, "resolved_title": "正交投影：最小二乘几何解释"},
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
    assert quality["generic_titles"] == ["核心概念"]
    assert quality["low_value_titles"] == []
    assert quality["needs_agent_repair"] is True
    assert quality["needs_scaffold_fallback"] is False
    assert quality["missing_modules"] == []


def test_heading_quality_detects_singleton_h3_sections() -> None:
    quality = pedagogy.analyze_chapter_heading_quality(
        (
            "# 计算机基础\n\n"
            "## 存储器层级结构与特性对比\n\n"
            "### 典型场景辨析\n\n"
            "缓存、内存和外存的差异需要结合访问速度和容量判断。\n\n"
            "## 进制转换与数据编码规则\n\n"
            "### 进制转换的核心技巧\n\n"
            "先确定基数，再按位权展开。\n\n"
            "### 字符编码与汉字内码规则\n\n"
            "ASCII 与汉字编码分别处理。\n\n"
            "## 常见任务与考点整理\n\n"
            "把容量换算、编码判断和性能对比放到同一组检查。\n"
        ),
        digest_mode="sprint",
    )

    assert quality["h2_count"] == 3
    assert quality["singleton_subheading_paths"] == [
        "存储器层级结构与特性对比 > 典型场景辨析",
    ]
    assert quality["needs_agent_repair"] is True


def test_heading_quality_detects_low_value_generated_toc_titles() -> None:
    quality = pedagogy.analyze_chapter_heading_quality(
        (
            "# 计算机基础\n\n"
            "## 核心概念速查表\n\n"
            "## 掌握 CPU、运算器、控制器与内存储的补充讲解\n\n"
            "## 典型例题与易错诊断\n\n"
            "### 例题 1\n\n"
            "## 字长定义与应\n\n"
        ),
        digest_mode="sprint",
    )

    assert quality["needs_agent_repair"] is True
    assert quality["low_value_titles"] == [
        "核心概念速查表",
        "掌握 CPU、运算器、控制器与内存储的补充讲解",
        "典型例题与易错诊断",
        "例题 1",
        "字长定义与应",
    ]


def test_learning_scaffold_does_not_generate_local_sections() -> None:
    scaffold = pedagogy.ensure_chapter_learning_scaffold(
        "只有一段内容",
        title="矩阵分解",
        objective="掌握矩阵分解",
        required_elements=["奇异值分解", "低秩近似"],
        digest_mode="sprint",
        source_count=2,
    )

    assert scaffold.startswith("# 矩阵分解\n")
    assert "只有一段内容" in scaffold
    assert "> [!TIP]" not in scaffold
    assert "核心总结" not in scaffold


def test_mode_sections_do_not_provide_keyword_scaffold_fallback() -> None:
    assert (
        pedagogy._build_mode_sections(
            title="矩阵分解",
            objective="理解矩阵分解在课程中的位置",
            required_elements=["奇异值分解", "低秩近似"],
            digest_mode="systematic",
            chapter_index=1,
            chapter_count=3,
        )
        == []
    )


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


def test_textbook_heading_normalization_does_not_generate_local_toc_titles() -> None:
    markdown = (
        "# 计算机硬件组成与指令系统基础\n\n"
        "## 核心概念速查表\n\n"
        "CPU、运算器、控制器和内存储器需要放在同一张结构图里理解。\n\n"
        "## 掌握 CPU、运算器、控制器与内存储器的构成关系的补充讲解\n\n"
        "这里补充说明各部件如何协作。\n\n"
        "## 综合训练与检查标准\n\n"
        "1. 判断指令由哪些部分组成。\n"
    )

    normalized = normalize_textbook_headings(
        markdown,
        digest_mode="sprint",
        fallback_title="计算机硬件组成与指令系统基础",
        focus_items=["CPU、运算器、控制器与内存储器的构成关系"],
    )

    assert "\n## 核心概念速查表" not in normalized
    assert "\n## 掌握 CPU、运算器、控制器与内存储器的构成关系的补充讲解" not in normalized
    assert "\n## 综合训练与检查标准" not in normalized
    assert "的补充讲解" not in normalized
    assert "核心概念速查表" not in normalized


def test_sprint_practice_seed_prefers_more_examples_for_quick_review() -> None:
    questions = _build_practice_questions(
        ChapterDraft(chapter_index=1, title="极限计算"),
        digest_mode="sprint",
    )

    assert len(questions) >= 6
    assert _minimum_visible_examples(digest_mode="sprint", question_count=len(questions)) == 4

    supplemented = _append_practice_section(
        "# 极限计算\n\n## 核心方法\n\n用条件判断选择方法。\n",
        questions,
        digest_mode="sprint",
        title="极限计算",
    )

    assert supplemented.count("> **例题") >= 6
    assert "易错点" in supplemented


def test_sprint_rule_review_requires_model_generated_problem_organization() -> None:
    draft = EnhancedChapterDraft(
        chapter_index=1,
        title="定积分计算",
        markdown="# 定积分计算\n\n## 核心内容\n\n换元积分要先判断是否能凑微分。\n",
    )
    task = ChapterGenerationTask(
        chapter_index=1,
        confirmed_title="定积分计算",
        required_elements=["换元积分题型", "分部积分计算"],
        practice_seed_policy={
            "digest_mode": "sprint",
            "example_density_policy": {
                "worked_examples_per_chapter": 4,
                "practice_tasks_per_chapter": 4,
                "training_chapter_min_examples": 6,
                "concept_chapter_min_examples": 2,
            },
        },
    )

    _reviewed, report, actions = _rule_review_chapter(
        draft=draft,
        task=task,
        claim_ledger=None,
        claim_evidence_map=None,
        conflict_report=None,
        digest_mode="sprint",
    )

    organization_actions = [
        action for action in actions if action.action_id.endswith("_sprint_problem_organization")
    ]
    assert organization_actions
    instruction = organization_actions[0].instruction
    assert "自然生成" in instruction
    assert "修复模型根据本章语义命名" in instruction
    assert "离开上下文看不懂的泛标题" in instruction
    assert "具体题型对象" in instruction
    assert "| 题型/任务 |" not in instruction
    assert report.passed is False


def test_sprint_rule_review_does_not_force_problem_table_for_concept_chapter() -> None:
    draft = EnhancedChapterDraft(
        chapter_index=1,
        title="矩阵分解",
        markdown=(
            "# 矩阵分解\n\n"
            "## 分解直觉\n\n"
            "矩阵分解把复杂矩阵拆成更容易解释的结构。\n\n"
            "### 短例子\n\n"
            "示例：把一个数据矩阵拆成方向和权重，可以帮助理解主要变化方向。\n\n"
            "### 反例\n\n"
            "反例：如果只看矩阵大小，不看任务目标，就无法判断该用哪种分解。\n"
        ),
    )
    task = ChapterGenerationTask(
        chapter_index=1,
        confirmed_title="矩阵分解",
        required_elements=["奇异值分解", "低秩近似"],
        practice_seed_policy={
            "digest_mode": "sprint",
            "example_density_policy": {
                "worked_examples_per_chapter": 4,
                "practice_tasks_per_chapter": 4,
                "training_chapter_min_examples": 6,
                "concept_chapter_min_examples": 2,
            },
        },
    )

    _reviewed, _report, actions = _rule_review_chapter(
        draft=draft,
        task=task,
        claim_ledger=None,
        claim_evidence_map=None,
        conflict_report=None,
        digest_mode="sprint",
    )

    assert not any(action.action_id.endswith("_sprint_problem_organization") for action in actions)


def test_sprint_rule_review_rejects_unanswered_self_check() -> None:
    draft = EnhancedChapterDraft(
        chapter_index=1,
        title="定积分计算",
        markdown=(
            "# 定积分计算\n\n"
            "## 换元积分题型\n\n"
            "| 题型 | 适用条件 | 做法 | 易错 |\n"
            "| --- | --- | --- | --- |\n"
            "| 换元积分 | 复合函数可凑微分 | 换元后改上下限 | 忘记改上下限 |\n\n"
            "## 考前速查与自测\n\n"
            "1. 练习：计算 $\\int_0^1 xe^{-x^2}\\,dx$。（提示：凑微分）\n"
            "2. 思考：为什么换元后积分上下限要同步变化？\n"
        ),
    )
    task = ChapterGenerationTask(
        chapter_index=1,
        confirmed_title="定积分计算",
        required_elements=["换元积分", "分部积分"],
        practice_seed_policy={
            "digest_mode": "sprint",
            "example_density_policy": {
                "worked_examples_per_chapter": 1,
                "practice_tasks_per_chapter": 1,
            },
        },
    )

    _reviewed, report, actions = _rule_review_chapter(
        draft=draft,
        task=task,
        claim_ledger=None,
        claim_evidence_map=None,
        conflict_report=None,
        digest_mode="sprint",
    )

    unanswered_actions = [
        action for action in actions if action.action_id.endswith("_sprint_unanswered_self_check")
    ]
    assert unanswered_actions
    assert "答案/结论" in unanswered_actions[0].instruction
    assert report.passed is False


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

    assert "题型分类或常见问法整理" in prompt
    assert "答案或结论" in prompt
    assert "> [!IMPORTANT]" in prompt
    assert "> [!WARNING]" in prompt
    assert "不要把公式、说明、步骤、提醒和例题揉在同一段里" in prompt
    assert "公式后解释适用条件，步骤后给检查点，例题后给错因" in prompt
    assert "训练型章节至少 6 个完整学习活动" in prompt
    assert "概念章至少 2 个左右" in prompt
    assert "不要复用章节标题" in prompt
    assert "必须给出参考答案" in prompt
    assert "考前速查与自测" in prompt
    assert "接口权限的判断题" in prompt
    assert "不能照抄或当候选词表" in prompt
    assert "孤立三级标题" in prompt
    assert "不要只写“请自行练习”" in prompt
    assert "题眼信号" not in prompt
    assert "处理模板" not in prompt


def test_heading_repair_prompt_requires_content_specific_section_titles() -> None:
    messages = build_docgen_heading_repair_messages(
        title="计算机硬件组成与指令系统基础",
        objective="让学生理解 CPU、内存和指令系统的关系。",
        digest_mode="sprint",
        required_elements=["CPU、运算器、控制器与内存储器", "指令系统"],
        writing_instructions="标题要清楚。",
        source_count=2,
        markdown="# 计算机硬件组成与指令系统基础\n\n## 核心概念速查表\n\nCPU 与内存协作。\n",
        dense_context="CPU 由运算器和控制器组成，指令包含操作码和地址码。",
    )
    prompt = messages[-1]["content"]

    assert "必须按小节正文改成具体内容名" in prompt
    assert "不要保留这些词当目录标题" in prompt
    assert "知识速查表" in prompt


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

    assert "题型/任务整理" in prompt
    assert "方法对照" in prompt
    assert "完整例题" in prompt
    assert "固定口号或本地模板" in prompt
    assert "不要在 action 里给可直接复制的泛标题" in prompt
    assert "目录里看不出内容的标题" in prompt
    assert "参考答案" in prompt
    assert "孤立三级标题属于层级过度切分" in prompt
    assert "题眼信号" not in prompt
    assert "处理模板" not in prompt
