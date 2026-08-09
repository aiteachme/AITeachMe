import asyncio

from app.workflows.digest.common import pedagogy
from app.workflows.digest.common.contracts import (
    DigestConfirmedPlanContract,
    build_digest_retrieval_policy,
    resolve_digest_retrieval_profile,
)
from app.workflows.digest.docgen.lib.chapter_enhancement import (
    _ensure_requested_placeholders,
)
from app.workflows.digest.docgen.lib import chapter_review
from app.workflows.digest.docgen.lib.chapter_review import measure_chapter_coverage, _rule_review_chapter
from app.workflows.digest.docgen.lib.chapter_planning import _filter_scope_items
from app.workflows.digest.docgen.lib.models import (
    ChapterGenerationTask,
    ChapterReviewReport,
    ClaimEvidenceBinding,
    ClaimEvidenceMap,
    ClaimItem,
    ClaimLedger,
    EnhancedChapterDraft,
    ReviewedChapterDraft,
)
from app.workflows.digest.docgen.lib.textbook_style import normalize_textbook_headings
from app.workflows.digest.docgen.lib.mode_profiles import get_docgen_mode_profile
from app.workflows.digest.planner.lib.constants import get_planner_mode_contract


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


def test_chapter_review_uses_rule_guardrail_only(monkeypatch) -> None:
    draft = EnhancedChapterDraft(
        chapter_index=1,
        title="矩阵乘法",
        markdown="# 矩阵乘法\n\n完整正文。",
    )
    rule_reviewed = ReviewedChapterDraft(
        chapter_index=1,
        title=draft.title,
        markdown=draft.markdown,
        review_report_ref="ch01_review",
    )
    rule_report = ChapterReviewReport(
        report_id="ch01_review",
        chapter_index=1,
        passed=True,
        quality_score=0.9,
    )

    monkeypatch.setattr(
        chapter_review,
        "_rule_review_chapter",
        lambda **_kwargs: (rule_reviewed, rule_report, []),
    )

    reviewed, report, actions = asyncio.run(
        chapter_review.review_chapter(
            draft=draft,
            task=None,
            claim_ledger=None,
            claim_evidence_map=None,
            conflict_report=None,
        )
    )

    assert reviewed.review_report_ref == "ch01_review"
    assert report.review_mode == "rule_guardrail"
    assert report.llm_action_count == 0
    assert actions == []


def test_docgen_retrieval_profile_does_not_keyword_route_user_text() -> None:
    assert (
        resolve_digest_retrieval_profile(
            "sprint",
            user_prompt="NOIP 数学竞赛专项训练",
            course_name="高等数学与算法竞赛",
        )
        == "docgen_balanced"
    )

    policy = build_digest_retrieval_policy(
        None,
        has_local_materials=False,
        user_prompt="OI-Wiki 线性代数",
        course_name="数学竞赛",
    )

    assert policy["internal_profile"] == "docgen_balanced"
    assert policy["external_focus"] == "general_learning_sources"


def test_docgen_retrieval_profile_rejects_removed_site_specific_contract() -> None:
    plan = DigestConfirmedPlanContract.model_validate(
        {
            "course_name": "算法专题",
            "retrieval_profile": "docgen_oi",
        }
    )

    assert plan.resolve_retrieval_profile() == "docgen_balanced"
    assert (
        build_digest_retrieval_policy(
            plan.resolve_retrieval_profile(),
            has_local_materials=True,
        )["external_focus"]
        == "general_learning_sources"
    )


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
        plan="",
        source_strategy="",
        chapters=chapters,
    )

    assert "《当前课程》" in overview
    assert "共 3 章" in overview
    assert "矩阵分解、特征值应用、正交投影：最小二乘几何解释" in overview
    assert "核心概念总览" not in overview


def test_systematic_mode_contract_and_word_budget_stay_deep() -> None:
    contract = get_planner_mode_contract("systematic")
    assert contract.min_chapters == 5
    assert contract.max_chapters == 12
    assert contract.target_length == "30000-100000字"

    profile = get_docgen_mode_profile("systematic")
    assert profile.word_budget(
        chapter_count=10,
        depth_level="deep",
        target_length=contract.target_length,
    ) == (3000, 10000)


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


def test_heading_quality_reports_singleton_h3_without_triggering_llm_repair() -> None:
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
    assert quality["needs_agent_repair"] is False


def test_heading_quality_does_not_force_valid_sprint_heading_model_review() -> None:
    quality = pedagogy.analyze_chapter_heading_quality(
        (
            "# 计算机基础\n\n"
            "## CPU 与内存协作\n\n"
            "## 指令执行路径\n\n"
            "## 存储层级差异\n\n"
        ),
        digest_mode="sprint",
    )

    assert quality["needs_agent_repair"] is False
    assert quality["force_model_heading_review"] is False
    assert quality["malformed_titles"] == []


def test_heading_quality_allows_repeated_h3_under_different_h2_sections() -> None:
    quality = pedagogy.analyze_chapter_heading_quality(
        (
            "# C 语言\n\n"
            "## 条件分支\n\n### 易错边界\n\n注意悬空 else。\n\n"
            "## 循环控制\n\n### 易错边界\n\n注意循环边界。\n\n"
            "## 综合练习\n\n完成综合练习。\n"
        ),
        digest_mode="sprint",
    )

    assert quality["duplicate_titles"] == []
    assert quality["needs_agent_repair"] is False


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


def test_textbook_heading_normalization_resets_dedupe_per_chapter() -> None:
    markdown = (
        "# 函数与极限\n\n"
        "## 单元测试\n\n"
        "第一章测试。\n\n"
        "# 连续性\n\n"
        "## 单元测试\n\n"
        "第二章测试。\n"
    )

    normalized = normalize_textbook_headings(markdown, digest_mode="sprint")

    assert normalized.count("## 单元测试") == 2


def test_textbook_heading_normalization_collapses_adjacent_demoted_labels() -> None:
    markdown = (
        "# 导数应用\n\n"
        "## 阶段测验\n\n"
        "\n"
        "## 章节练习\n\n"
        "- 判断单调区间。\n"
    )

    normalized = normalize_textbook_headings(markdown, digest_mode="sprint")

    assert normalized.count("**练习**") == 1
    assert "- 判断单调区间。" in normalized


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


def test_rule_review_routes_material_contract_misses_to_local_patch() -> None:
    draft = EnhancedChapterDraft(
        chapter_index=1,
        title="函数与极限",
        markdown="# 函数与极限\n\n## 极限直观\n\n极限描述变量逼近时的趋势。\n\n## 单元测试\n\n**题目**：判断极限是否存在。\n",
    )
    task = ChapterGenerationTask(
        chapter_index=1,
        confirmed_title="函数与极限",
        required_elements=["函数的基本概念、常见初等函数与图像性质"],
        min_word_count=1,
    )

    _reviewed, report, actions = _rule_review_chapter(
        draft=draft,
        task=task,
        claim_ledger=None,
        claim_evidence_map=None,
        conflict_report=None,
        digest_mode="sprint",
    )

    coverage_actions = [action for action in actions if action.action_id == "review_ch01_section_patch"]
    assert coverage_actions
    assert coverage_actions[0].action_type == "section_patch"
    assert coverage_actions[0].severity == "warning"
    assert report.passed is False


def test_rule_review_does_not_treat_source_claims_as_verbatim_coverage_contracts() -> None:
    draft = EnhancedChapterDraft(
        chapter_index=1,
        title="变量与数据类型",
        markdown=(
            "# 变量与数据类型\n\n"
            "## 变量定义\n\n变量需要先定义再使用。\n\n"
            "## 单元测试\n\n**题目**：变量何时可以使用？\n\n**答案**：定义后。\n"
        ),
    )
    task = ChapterGenerationTask(
        chapter_index=1,
        confirmed_title="变量与数据类型",
        required_elements=["变量定义"],
        claim_targets=["| int | a,b,c; | --- | --- | 破碎 OCR 表格与代码片段"],
        min_word_count=1,
    )

    _reviewed, report, actions = _rule_review_chapter(
        draft=draft,
        task=task,
        claim_ledger=None,
        claim_evidence_map=None,
        conflict_report=None,
        digest_mode="sprint",
    )

    assert report.coverage_score == 1.0
    assert report.missing_elements == []
    assert not any(action.action_id == "review_ch01_section_patch" for action in actions)


def test_rule_review_records_low_evidence_without_requesting_model_patch() -> None:
    draft = EnhancedChapterDraft(
        chapter_index=1,
        title="变量",
        markdown="# 变量\n\n## 定义\n\n变量需要先定义再使用。\n\n## 单元测试\n\n**题目**：变量何时可用？\n\n**答案**：定义后。\n",
    )
    task = ChapterGenerationTask(
        chapter_index=1,
        confirmed_title="变量",
        required_elements=["变量定义"],
        min_word_count=1,
        evidence_support_threshold=0.6,
    )
    claim_ledger = ClaimLedger(
        chapter_index=1,
        items=[ClaimItem(claim_id="claim-1", chapter_index=1, claim_text="变量定义")],
    )
    claim_map = ClaimEvidenceMap(
        chapter_index=1,
        bindings=[ClaimEvidenceBinding(claim_id="claim-1", support_level=0.5)],
    )

    _reviewed, report, actions = _rule_review_chapter(
        draft=draft,
        task=task,
        claim_ledger=claim_ledger,
        claim_evidence_map=claim_map,
        conflict_report=None,
        digest_mode="sprint",
    )

    evidence_actions = [action for action in actions if action.action_id == "review_ch01_evidence"]
    assert report.passed is True
    assert report.evidence_support_score == 0.5
    assert evidence_actions[0].action_type == "record_only"
    assert evidence_actions[0].severity == "warning"


def test_rule_review_coverage_accepts_reordered_explicit_concepts() -> None:
    score, missing = measure_chapter_coverage(
        "CPU 由运算器和控制器组成，内存储器负责保存正在处理的数据。",
        ["CPU、运算器、控制器与内存储器"],
    )

    assert score == 1.0
    assert missing == []


def test_rule_review_coverage_rejects_incomplete_parallel_concepts() -> None:
    target = "CPU、运算器、控制器与内存储器"

    score, missing = measure_chapter_coverage("CPU 由运算器和控制器组成。", [target])

    assert score == 0.0
    assert missing == [target]


def test_rule_review_coverage_accepts_long_parallel_contract_rephrasing() -> None:
    target = "C 程序入口 main 函数、源程序编译流程、头文件包含、宏定义替换规则的零基础铺垫"
    markdown = (
        "程序从 main 函数这个入口开始。源文件先编译再链接，头文件通过 include 引入声明，"
        "宏定义在预处理阶段完成文本替换。"
    )

    score, missing = measure_chapter_coverage(markdown, [target])

    assert score == 1.0
    assert missing == []


def test_rule_review_coverage_preserves_symbolic_pointer_expression() -> None:
    target = "数组名与首元素地址、指针加减及*(p+i)访问关系"
    markdown = (
        "数组名 a 在多数表达式中转换为首元素地址 &a[0]。"
        "p+i 指向第 i 个元素，*(p+i) 访问该元素；指针加减按元素大小移动。"
    )

    score, missing = measure_chapter_coverage(markdown, [target])

    assert score == 1.0
    assert missing == []


def test_rule_review_coverage_accepts_short_parallel_compounds_across_explanation() -> None:
    target = "循环变量更新、累加累乘与奇偶数统计题型"
    markdown = (
        "循环题要明确循环变量的初始化、条件和更新。"
        "累加通常从 0 开始，累乘通常从 1 开始；奇偶数统计使用取余判断。"
    )

    score, missing = measure_chapter_coverage(markdown, [target])

    assert score == 1.0
    assert missing == []


def test_rule_review_coverage_rejects_long_contract_with_multiple_missing_concepts() -> None:
    target = "标识符命名规则、C 语言关键字、基本数据类型、sizeof 运算结果、变量初始化与赋值语句"

    score, missing = measure_chapter_coverage("本节介绍标识符命名规则、C 语言关键字和基本数据类型。", [target])

    assert score == 0.0
    assert missing == [target]


def test_rule_review_coverage_keeps_genuinely_missing_contract_visible() -> None:
    target = "函数的基本概念、常见初等函数与图像性质"

    score, missing = measure_chapter_coverage("极限描述变量逼近时的趋势。", [target])

    assert score == 0.0
    assert missing == [target]


def test_chapter_scope_filter_removes_other_chapter_targets_without_title_generation() -> None:
    filtered = _filter_scope_items(
        ["Internet 的功能与信息服务", "DOS 命令执行环境与文件管理", "网络覆盖地域的分类标准"],
        local_scope=["计算机网络架构与互联基础", "网络覆盖地域的分类标准"],
        forbidden_scope=["操作系统原理与软件管理", "DOS 命令执行环境与文件管理", "数制转换与数据编码原理"],
        limit=4,
    )

    assert filtered == ["Internet 的功能与信息服务", "网络覆盖地域的分类标准"]


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


def test_rule_review_requires_fixed_unit_test_as_final_h2() -> None:
    task = ChapterGenerationTask(
        chapter_index=1,
        confirmed_title="函数图像",
        required_elements=[],
    )
    missing_draft = EnhancedChapterDraft(
        chapter_index=1,
        title="函数图像",
        markdown="# 函数图像\n\n## 图像性质\n\n函数图像可以帮助判断增减性。\n",
    )
    misplaced_draft = EnhancedChapterDraft(
        chapter_index=1,
        title="函数图像",
        markdown=(
            "# 函数图像\n\n"
            "## 图像性质\n\n函数图像可以帮助判断增减性。\n\n"
            "## 单元测试\n\n> [!QUESTION]\n> **题目/任务**：判断一次函数的增减性。\n>\n> **答案/结论**：斜率为正时递增。\n\n"
            "## 本章小结\n\n看斜率和截距。\n"
        ),
    )

    _reviewed, _report, missing_actions = _rule_review_chapter(
        draft=missing_draft,
        task=task,
        claim_ledger=None,
        claim_evidence_map=None,
        conflict_report=None,
        digest_mode="systematic",
    )
    _reviewed, _report, misplaced_actions = _rule_review_chapter(
        draft=misplaced_draft,
        task=task,
        claim_ledger=None,
        claim_evidence_map=None,
        conflict_report=None,
        digest_mode="systematic",
    )

    missing_unit_actions = [action for action in missing_actions if action.action_id.endswith("_unit_test")]
    misplaced_unit_actions = [action for action in misplaced_actions if action.action_id.endswith("_unit_test")]
    assert len(missing_unit_actions) == 1
    assert len(misplaced_unit_actions) == 1
    assert "缺少固定的章末 `## 单元测试` 模块" in missing_unit_actions[0].reason
    assert "`## 单元测试` 必须是本章最后一个二级标题" in misplaced_unit_actions[0].reason
    assert "本章末尾补齐固定二级标题 `## 单元测试`" in missing_unit_actions[0].instruction


def test_rule_review_short_chapter_requests_section_expansion() -> None:
    draft = EnhancedChapterDraft(
        chapter_index=1,
        title="系统学习章节",
        markdown="# 系统学习章节\n\n## 核心概念\n\n这里只给出一句定义。",
    )
    task = ChapterGenerationTask(
        chapter_index=1,
        confirmed_title="系统学习章节",
        required_elements=[],
        min_word_count=200,
    )

    _reviewed, report, actions = _rule_review_chapter(
        draft=draft,
        task=task,
        claim_ledger=None,
        claim_evidence_map=None,
        conflict_report=None,
        digest_mode="systematic",
    )

    length_actions = [action for action in actions if action.action_id.endswith("_section_length")]
    assert len(length_actions) == 1
    assert length_actions[0].action_type == "section_patch"
    assert length_actions[0].severity == "warning"
    assert "扩写本章核心小节" in length_actions[0].instruction
    assert report.passed is False
