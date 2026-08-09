"""Chapter-level review for enhanced DocGen drafts."""

from __future__ import annotations

import re

from app.shared.infra.tools.builtin.markdown_processing import count_words
from app.workflows.digest.docgen.lib.presentation_policy import find_docgen_presentation_issues
from app.workflows.digest.docgen.lib.models import (
    ChapterGenerationTask,
    ChapterReviewReport,
    ClaimEvidenceMap,
    ClaimLedger,
    ConflictReport,
    EnhancedChapterDraft,
    ReviewAction,
    ReviewedChapterDraft,
    clean_string_list,
)
from app.workflows.digest.docgen.lib.quality import evidence_support_score


def _normalize_blob(value: str) -> str:
    return re.sub(r"[^0-9a-z_\u4e00-\u9fff*()+/\[\]&-]+", "", str(value or "").casefold())


def _parallel_target_anchors(target: str) -> list[str]:
    parts = re.split(r"(?:以及|并且|、|，|,|；|;|：|:|与|和|及|\s+)", str(target or ""))
    anchors: list[str] = []
    for part in parts:
        anchor = _normalize_blob(part)
        if len(anchor) < 2 or anchor in anchors:
            continue
        anchors.append(anchor)
    return anchors


def _anchor_covered(normalized_markdown: str, anchor: str) -> bool:
    if not anchor:
        return False
    if anchor in normalized_markdown:
        return True
    if len(anchor) < 3:
        return False
    trigrams = {anchor[index : index + 3] for index in range(len(anchor) - 2)}
    overlap = sum(trigram in normalized_markdown for trigram in trigrams) / max(1, len(trigrams))
    if overlap >= 0.45:
        return True
    if 4 <= len(anchor) <= 6:
        bigrams = {anchor[index : index + 2] for index in range(len(anchor) - 1)}
        bigram_overlap = sum(bigram in normalized_markdown for bigram in bigrams) / max(1, len(bigrams))
        if bigram_overlap >= 0.6:
            return True
    cjk_chars = {char for char in anchor if "\u4e00" <= char <= "\u9fff"}
    if len(cjk_chars) < 4:
        return False
    return len(cjk_chars.intersection(normalized_markdown)) / len(cjk_chars) >= 0.6


def _is_target_covered(normalized_markdown: str, target: str) -> bool:
    needle = _normalize_blob(target)
    if not needle:
        return False
    if needle in normalized_markdown:
        return True

    ascii_anchors = {
        token.casefold()
        for token in re.findall(r"[A-Za-z][A-Za-z0-9_]*(?:-[A-Za-z0-9_]+)*", str(target or ""))
        if len(token) >= 2
    }
    if any(_normalize_blob(anchor) not in normalized_markdown for anchor in ascii_anchors):
        return False
    parallel_anchors = _parallel_target_anchors(target)
    if len(parallel_anchors) >= 2:
        covered_count = sum(_anchor_covered(normalized_markdown, anchor) for anchor in parallel_anchors)
        required_count = (
            len(parallel_anchors)
            if len(parallel_anchors) <= 4
            else (len(parallel_anchors) * 4 + 4) // 5
        )
        return covered_count >= required_count
    if len(ascii_anchors) >= 2:
        return True
    return _anchor_covered(normalized_markdown, needle)


def measure_chapter_coverage(markdown: str, targets: list[str]) -> tuple[float, list[str]]:
    if not targets:
        return 1.0, []
    normalized = _normalize_blob(markdown)
    missing: list[str] = []
    hits = 0
    for target in targets:
        if _is_target_covered(normalized, target):
            hits += 1
        else:
            missing.append(target)
    return round(hits / max(1, len(targets)), 4), missing


def _chapter_anchor(draft: EnhancedChapterDraft) -> str:
    return draft.title or f"chapter:{draft.chapter_index}"


def _chapter_unit_test_issue(markdown: str) -> str:
    h2_titles = [
        match.group("title").strip()
        for match in re.finditer(r"(?m)^##\s+(?P<title>.+?)\s*$", str(markdown or ""))
    ]
    if not h2_titles:
        return "缺少二级标题结构，无法放置固定的章末单元测试模块。"
    if "单元测试" not in h2_titles:
        return "缺少固定的章末 `## 单元测试` 模块。"
    if h2_titles[-1] != "单元测试":
        return "`## 单元测试` 必须是本章最后一个二级标题。"
    return ""


def _rule_review_chapter(
    *,
    draft: EnhancedChapterDraft,
    task: ChapterGenerationTask | None,
    claim_ledger: ClaimLedger | None,
    claim_evidence_map: ClaimEvidenceMap | None,
    conflict_report: ConflictReport | None,
    digest_mode: str = "",
) -> tuple[ReviewedChapterDraft, ChapterReviewReport, list[ReviewAction]]:
    """执行无需 LLM 的章节复核兜底。

    规则复核只检查合同覆盖、证据支撑、长度和冲突信号。它既是 LLM
    review 失败时的 fallback，也是 LLM 结果的 guardrail。
    """

    del digest_mode
    task = task or ChapterGenerationTask(chapter_index=draft.chapter_index, confirmed_title=draft.title)
    # ``required_elements`` is the confirmed teaching contract. ``claim_targets``
    # may contain long source excerpts or OCR fragments and belongs to evidence
    # support checks; treating it as verbatim coverage creates false LLM repairs.
    targets = clean_string_list(task.required_elements, limit=18)
    coverage_score, missing = measure_chapter_coverage(draft.markdown, targets)
    support_score = evidence_support_score(claim_evidence_map or ClaimEvidenceMap(chapter_index=draft.chapter_index))
    quality_score = draft.quality_signals.quality_score or 0.0
    word_count = count_words(draft.markdown)
    warnings: list[str] = []
    actions: list[ReviewAction] = []
    scope_constraints = [
        "不得补入其他章节的知识对象；如果材料里出现 forbidden_scope 中的主题，只能一句带过作为前后联系，不能新增为独立小节。"
    ] if task.forbidden_scope else []
    rendering_issues = find_docgen_presentation_issues(draft.markdown)
    unit_test_issue = _chapter_unit_test_issue(draft.markdown)
    if rendering_issues:
        warnings.extend(rendering_issues)
        actions.append(
            ReviewAction(
                action_id=f"review_ch{draft.chapter_index:02d}_surface_rendering",
                action_type="surface_patch",
                chapter_index=draft.chapter_index,
                severity="warning",
                reason="Markdown 展示与学习结构异常：" + "；".join(rendering_issues),
                target_anchor=_chapter_anchor(draft),
                instruction="修复 Markdown 展示结构与学习块完整性，包括标题层级、加粗/高亮闭合、表格、callout、代码块、公式、Mermaid、长段落、过长列表，以及例题/练习的题目、解析和答案字段。",
                constraints=[
                    "不得新增无依据知识点。",
                    "不得改变章节标题和章节顺序。",
                    "例题或练习缺少字段时，只能基于章节已有内容、执行合同或材料证据补齐。",
                    "优先调整 Markdown 标记、空行、fenced block 边界、阅读分组和安全高亮表达。",
                    *scope_constraints,
                ],
                expected_effect="章节 Markdown 可以稳定渲染，并且重点、提示块、表格、代码块、公式、Mermaid、例题和练习都能清晰显示。",
            )
        )
    if unit_test_issue:
        warnings.append(unit_test_issue)
        actions.append(
            ReviewAction(
                action_id=f"review_ch{draft.chapter_index:02d}_unit_test",
                action_type="section_patch",
                chapter_index=draft.chapter_index,
                severity="warning",
                reason=unit_test_issue,
                target_anchor=_chapter_anchor(draft),
                instruction=(
                    "在本章末尾补齐固定二级标题 `## 单元测试`，围绕本章核心概念、方法、易错点或应用任务生成短题/"
                    "案例检查/边界辨析，并为每题给出答案、判定依据或解析要点。"
                ),
                constraints=[
                    "`## 单元测试` 必须是本章最后一个二级标题。",
                    "不得把其它章节主题补成测试主体。",
                    "传统题不适合时改成案例检查、操作步骤检查、边界辨析或迁移任务。",
                    "每题必须可判断，不能只写“自行思考”。",
                    *scope_constraints,
                ],
                expected_effect="每章都有可被 examine/profile 继续利用的章末测试信号，且不影响其它标题由模型按内容自然命名。",
            )
        )
    coverage_below_threshold = bool(targets and coverage_score < task.coverage_threshold)
    if missing:
        warnings.append("章节存在执行合同覆盖提示，需结合正文语义复核判断。")
        needs_patch = coverage_below_threshold
        actions.append(
            ReviewAction(
                action_id=f"review_ch{draft.chapter_index:02d}_section_patch",
                action_type="section_patch" if needs_patch else "record_only",
                chapter_index=draft.chapter_index,
                severity="warning" if needs_patch else "info",
                reason="缺少学习大纲项：" + "、".join(missing[:5]),
                target_anchor=_chapter_anchor(draft),
                instruction=(
                    "只使用本章现有正文与执行合同线索，短而具体地补齐这些缺项："
                    + "、".join(missing[:8])
                    if needs_patch
                    else "记录规则覆盖提示：" + "、".join(missing[:8])
                ),
                constraints=[
                    "不得新增、删除或重排 confirmed plan 章节。",
                    "不得复制整章、重复已有小节或引入本章材料没有支持的新事实。",
                    "只补实际缺失的知识、例题、方法或边界，不得只复述大纲长短语。",
                    *scope_constraints,
                ],
                expected_effect=(
                    f"章节覆盖率达到至少 {task.coverage_threshold:.0%}，且保持原有标题与正文结构。"
                    if needs_patch
                    else "避免轻微逐字匹配误判，同时让覆盖提示在质量报告中保持可见。"
                ),
            )
        )
    # Example density, training-chapter role, self-check completeness and task
    # taxonomy are semantic judgments. They are handled by the structured LLM
    # review prompt, not by local keyword matching.
    if support_score < task.evidence_support_threshold and list((claim_ledger or ClaimLedger()).items or []):
        warnings.append("部分主张证据支撑偏弱。")
        actions.append(
            ReviewAction(
                action_id=f"review_ch{draft.chapter_index:02d}_evidence",
                action_type="record_only",
                chapter_index=draft.chapter_index,
                severity="warning",
                reason="主张证据支撑低于阈值。",
                target_anchor=_chapter_anchor(draft),
                instruction="记录低支撑主张及现有来源映射，后续资料补充或人工复核时优先检查。",
                constraints=[
                    "不得为了提高启发式分数而生成免责声明或重复正文。",
                    "不得把本地资料没有覆盖的内容伪装成材料原文。",
                    "warning、support score 和 claim/evidence 映射必须保留在 manifest。",
                    *scope_constraints,
                ],
                expected_effect="低支撑信号保持可见，但不触发一次无法获得新证据的冗余模型改写。",
            )
        )
    if word_count < task.min_word_count:
        warnings.append("章节长度低于最低字数要求。")
        actions.append(
            ReviewAction(
                action_id=f"review_ch{draft.chapter_index:02d}_section_length",
                action_type="section_patch",
                chapter_index=draft.chapter_index,
                severity="warning",
                reason=f"章节偏短：当前约 {word_count} 字，低于最低要求 {task.min_word_count} 字。",
                target_anchor=_chapter_anchor(draft),
                instruction="在不新增无证据事实、不改变章节边界的前提下，扩写本章核心小节：补清定义/条件、解释路径、例子或任务、检查点和易错边界，使正文达到最低字数要求。",
                constraints=[
                    "优先使用本章已有研究材料、claim/evidence 和已出现的正文线索。",
                    "不得新增、删除或重排 confirmed plan 章节。",
                    "不得引入没有证据支撑的新断言。",
                    *scope_constraints,
                ],
                expected_effect="章节从短提纲扩展为完整学习单元，读者不用回看教材也能理解本章核心内容。",
            )
        )
    unresolved_conflicts = int((conflict_report or ConflictReport()).unresolved_count or 0)
    if unresolved_conflicts > 0:
        warnings.append("仍存在未解决的低证据或冲突提示。")
    passed = not coverage_below_threshold and not any(
        action.action_type in {"section_patch", "evidence_patch", "regenerate_chapter", "re_dispatch", "rebuild_backbone"}
        and action.severity in {"warning", "error"}
        for action in actions
    )
    report = ChapterReviewReport(
        report_id=f"ch{draft.chapter_index:02d}_review",
        chapter_index=draft.chapter_index,
        passed=passed,
        coverage_score=coverage_score,
        evidence_support_score=support_score,
        quality_score=quality_score,
        missing_elements=missing,
        warnings=warnings,
        fallback_used=False,
    )
    reviewed = ReviewedChapterDraft.model_validate(
        {
            **draft.model_dump(mode="json"),
            "review_report_ref": report.report_id,
            "warnings": [*draft.warnings, *warnings],
            "patched": False,
        }
    )
    return reviewed, report, actions


async def review_chapter(
    *,
    draft: EnhancedChapterDraft,
    task: ChapterGenerationTask | None,
    claim_ledger: ClaimLedger | None,
    claim_evidence_map: ClaimEvidenceMap | None,
    conflict_report: ConflictReport | None,
    digest_mode: str = "",
    guideline_summary: dict | None = None,
    dispatch_item: dict | None = None,
    chapter_contract: dict | None = None,
    evidence_items: list[dict] | None = None,
    learner_profile_text: str = "",
) -> tuple[ReviewedChapterDraft, ChapterReviewReport, list[ReviewAction]]:
    """Validate one chapter with deterministic guardrails after the writer pass."""

    del guideline_summary, dispatch_item, chapter_contract, evidence_items, learner_profile_text

    rule_reviewed, rule_report, rule_actions = _rule_review_chapter(
        draft=draft,
        task=task,
        claim_ledger=claim_ledger,
        claim_evidence_map=claim_evidence_map,
        conflict_report=conflict_report,
        digest_mode=digest_mode,
    )
    report = rule_report.model_copy(
        update={
            "review_mode": "rule_guardrail",
            "llm_action_count": 0,
            "rule_action_count": len(rule_actions),
        }
    )
    reviewed = ReviewedChapterDraft.model_validate(
        {
            **rule_reviewed.model_dump(mode="json"),
            "review_report_ref": report.report_id,
        }
    )
    return reviewed, report, rule_actions


__all__ = ["measure_chapter_coverage", "review_chapter"]
