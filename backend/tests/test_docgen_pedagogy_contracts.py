from app.workflows.digest.common import pedagogy
from app.workflows.digest.docgen.lib.chapter_enhancement import (
    _ensure_requested_placeholders,
)
from app.workflows.digest.docgen.lib.chapter_review import _coverage, _rule_review_chapter
from app.workflows.digest.docgen.lib.chapter_planning import _filter_scope_items
from app.workflows.digest.docgen.lib.models import ChapterGenerationTask, EnhancedChapterDraft
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


def test_heading_quality_detects_duplicate_titles_without_local_semantic_wordlist() -> None:
    quality = pedagogy.analyze_chapter_heading_quality(
        "# 线性代数\n\n## 核心概念\nA\n\n## 核心概念\nB",
        digest_mode="systematic",
    )

    assert quality["digest_mode"] == "systematic"
    assert quality["h2_count"] == 2
    assert quality["duplicate_titles"] == ["核心概念"]
    assert quality["generic_titles"] == []
    assert quality["malformed_titles"] == []
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


def test_heading_quality_forces_sprint_heading_model_review_without_title_wordlist() -> None:
    quality = pedagogy.analyze_chapter_heading_quality(
        (
            "# 计算机基础\n\n"
            "## CPU 与内存协作\n\n"
            "## 指令执行路径\n\n"
            "## 存储层级差异\n\n"
        ),
        digest_mode="sprint",
    )

    assert quality["needs_agent_repair"] is True
    assert quality["force_model_heading_review"] is True
    assert quality["malformed_titles"] == []


def test_heading_quality_detects_malformed_heading_shape_without_semantic_wordlist() -> None:
    quality = pedagogy.analyze_chapter_heading_quality(
        "# 计算机基础\n\n## CPU 与\n\n## 指令执行路径\n\n## 存储层级差异\n\n",
        digest_mode="systematic",
    )

    assert quality["malformed_titles"] == ["CPU 与"]
    assert quality["needs_agent_repair"] is True


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


def test_textbook_heading_normalization_drops_duplicate_headings_without_local_titles() -> None:
    markdown = (
        "# 计算机硬件组成与指令系统基础\n\n"
        "## CPU 与内存协作\n\n"
        "CPU 取指、译码和执行需要内存提供指令与数据。\n\n"
        "## CPU 与内存协作\n\n"
        "重复标题不能进入最终目录。\n\n"
        "## 指令执行路径\n\n"
        "判断指令由哪些部分组成。\n"
    )

    normalized = normalize_textbook_headings(
        markdown,
        digest_mode="sprint",
        fallback_title="计算机硬件组成与指令系统基础",
        focus_items=["CPU、运算器、控制器与内存储器的构成关系"],
    )

    assert normalized.count("## CPU 与内存协作") == 1
    assert "\n## 指令执行路径" in normalized


def test_sprint_rule_review_does_not_infer_problem_organization_from_title_keywords() -> None:
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
    assert organization_actions == []
    assert report.passed is False


def test_rule_review_coverage_uses_exact_contract_text_not_keyword_tokens() -> None:
    score, missing = _coverage(
        "CPU 由运算器和控制器组成，内存储器负责保存正在处理的数据。",
        ["CPU、运算器、控制器与内存储器"],
    )

    assert score == 0.0
    assert missing == ["CPU、运算器、控制器与内存储器"]


def test_chapter_scope_filter_removes_other_chapter_targets_without_title_generation() -> None:
    filtered = _filter_scope_items(
        ["Internet 的功能与信息服务", "DOS 命令执行环境与文件管理", "网络覆盖地域的分类标准"],
        local_scope=["计算机网络架构与互联基础", "网络覆盖地域的分类标准"],
        forbidden_scope=["操作系统原理与软件管理", "DOS 命令执行环境与文件管理", "数制转换与数据编码原理"],
        limit=4,
    )

    assert filtered == ["Internet 的功能与信息服务", "网络覆盖地域的分类标准"]


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


def test_sprint_rule_review_does_not_keyword_reject_unanswered_practice() -> None:
    draft = EnhancedChapterDraft(
        chapter_index=1,
        title="定积分计算",
        markdown=(
            "# 定积分计算\n\n"
            "## 换元积分题型\n\n"
            "| 题型 | 适用条件 | 做法 | 易错 |\n"
            "| --- | --- | --- | --- |\n"
            "| 换元积分 | 复合函数可凑微分 | 换元后改上下限 | 忘记改上下限 |\n\n"
            "## 换元积分边界判断\n\n"
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
    assert unanswered_actions == []
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

    assert "真实分类或常见问法整理" in prompt
    assert "答案或结论" in prompt
    assert "> [!IMPORTANT]" in prompt
    assert "> [!WARNING]" in prompt
    assert "> [!EXAMPLE]" in prompt
    assert "> [!PRACTICE]" in prompt
    assert "不要把公式、说明、步骤、提醒和例题揉在同一段里" in prompt
    assert "公式后解释适用条件，步骤后给检查点，例题后给错因" in prompt
    assert "每个主要 `##` 都要有足够正文" in prompt
    assert "章末保留一个短练习收束块" in prompt
    assert "训练型章节至少 6 个完整学习活动" in prompt
    assert "概念章至少 2 个左右" in prompt
    assert "不要复用章节标题" in prompt
    assert "必须给出参考答案" in prompt
    assert "带答案的理解检查活动" in prompt
    assert "学习动作、检查动作或配额标签复制成目录标题" in prompt
    assert "泛化目录标题、学习动作标题、内部检查标题、序号占位题型" in prompt
    assert "固定词表、关键词抽取或字符串拼接" in prompt
    assert "本章边界外主题" in prompt
    assert "接口权限的判断题" not in prompt
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
        markdown="# 计算机硬件组成与指令系统基础\n\n## 模块检查标题\n\nCPU 与内存协作。\n",
        dense_context="CPU 由运算器和控制器组成，指令包含操作码和地址码。",
    )
    prompt = messages[-1]["content"]

    assert "必须按小节正文改成具体内容名" in prompt
    assert "不要保留这些标签当目录标题" in prompt
    assert "泛化目录标题、学习动作标题、内部检查标题、序号占位题型" in prompt


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
    assert "每章末尾应有一个短练习收束块" in prompt
    assert "不要在 action 里给可直接复制的标题" in prompt
    assert "按本章具体对象、方法、任务差异或场景命名" in prompt
    assert "序号占位题型" in prompt
    assert "参考答案" in prompt
    assert "孤立三级标题属于层级过度切分" in prompt
    assert "题眼信号" not in prompt
    assert "处理模板" not in prompt
