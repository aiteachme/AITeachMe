"""Chapter-level review for enhanced DocGen drafts."""

from __future__ import annotations

from collections.abc import Sequence

from app.shared.infra.llm_support import acompletion_with_fallback
from app.shared.infra.tools.builtin.markdown_processing import count_words
from app.workflows.digest.docgen.lib.model_policy import DocGenModelStep, docgen_completion_kwargs_with_metadata
from app.workflows.digest.docgen.lib.presentation_policy import find_docgen_presentation_issues
from app.workflows.digest.docgen.lib.models import (
    ChapterGenerationTask,
    ChapterReviewReport,
    ClaimEvidenceMap,
    ClaimLedger,
    ConflictReport,
    EnhancedChapterDraft,
    LLMChapterReviewResult,
    ReviewAction,
    ReviewedChapterDraft,
    clean_string_list,
)
from app.workflows.digest.docgen.lib.quality import evidence_support_score
from app.workflows.digest.docgen.prompts.chapter_review import build_chapter_review_messages


def _normalize_blob(value: str) -> str:
    return "".join(str(value or "").split()).casefold()


def _is_target_covered(normalized_markdown: str, target: str) -> bool:
    needle = _normalize_blob(target)
    return bool(needle and needle in normalized_markdown)


def _coverage(markdown: str, targets: list[str]) -> tuple[float, list[str]]:
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


def _dedupe_actions(actions: Sequence[ReviewAction]) -> list[ReviewAction]:
    deduped: list[ReviewAction] = []
    seen: set[tuple[str, int | None, str, str]] = set()
    for action in actions:
        key = (
            action.action_type,
            action.chapter_index,
            action.target_anchor.casefold(),
            action.reason.casefold(),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(action)
    return deduped


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
    targets = clean_string_list([*task.required_elements, *task.claim_targets], limit=18)
    coverage_score, missing = _coverage(draft.markdown, targets)
    support_score = evidence_support_score(claim_evidence_map or ClaimEvidenceMap(chapter_index=draft.chapter_index))
    quality_score = draft.quality_signals.quality_score or 0.0
    word_count = count_words(draft.markdown)
    warnings: list[str] = []
    actions: list[ReviewAction] = []
    scope_constraints = [
        "不得补入其他章节的知识对象；如果材料里出现 forbidden_scope 中的主题，只能一句带过作为前后联系，不能新增为独立小节。"
    ] if task.forbidden_scope else []
    rendering_issues = find_docgen_presentation_issues(draft.markdown)
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
    if missing:
        warnings.append("章节未完全覆盖执行合同中的关键点。")
        actions.append(
            ReviewAction(
                action_id=f"review_ch{draft.chapter_index:02d}_section_patch",
                action_type="section_patch",
                chapter_index=draft.chapter_index,
                severity="warning",
                reason="缺少学习大纲项：" + "、".join(missing[:5]),
                target_anchor=_chapter_anchor(draft),
                instruction="补齐章节中缺失的学习大纲项：" + "、".join(missing[:8]),
                constraints=[
                    "不得新增、删除或重排 confirmed plan 章节。",
                    "只允许修改本章相关小节。",
                    "不得引入没有证据支撑的新断言。",
                    *scope_constraints,
                ],
                expected_effect="章节正文能覆盖执行合同中的关键点，且不改变章节边界。",
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
                action_type="evidence_patch",
                chapter_index=draft.chapter_index,
                severity="warning",
                reason="主张证据支撑低于阈值。",
                target_anchor=_chapter_anchor(draft),
                instruction="针对证据支撑不足的主张补充可追踪来源，并只局部改写相关小节。",
                constraints=[
                    "必须优先使用本地资料或已打开网页正文。",
                    "不得只依据搜索标题补新断言。",
                    "补充来源和 claim/evidence 映射必须写入 manifest。",
                    *scope_constraints,
                ],
                expected_effect="低支撑主张获得新的 evidence binding，章节正文只做必要局部调整。",
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
    passed = not any(
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


def _llm_actions_to_review_actions(
    *,
    draft: EnhancedChapterDraft,
    suggestions: Sequence,
) -> list[ReviewAction]:
    actions: list[ReviewAction] = []
    for index, suggestion in enumerate(suggestions, start=1):
        action_type = suggestion.action_type
        if action_type == "regenerate_chapter" and suggestion.reason and "证据" in suggestion.reason:
            action_type = "evidence_patch"
        actions.append(
            ReviewAction(
                action_id=f"llm_review_ch{draft.chapter_index:02d}_{index:02d}_{action_type}",
                action_type=action_type,
                chapter_index=draft.chapter_index,
                severity=suggestion.severity,
                reason=suggestion.reason,
                target_anchor=suggestion.target_anchor or _chapter_anchor(draft),
                instruction=suggestion.instruction,
                constraints=suggestion.constraints,
                expected_effect=suggestion.expected_effect,
            )
        )
    return actions


async def review_chapter(
    *,
    draft: EnhancedChapterDraft,
    task: ChapterGenerationTask | None,
    claim_ledger: ClaimLedger | None,
    claim_evidence_map: ClaimEvidenceMap | None,
    conflict_report: ConflictReport | None,
    digest_mode: str = "",
) -> tuple[ReviewedChapterDraft, ChapterReviewReport, list[ReviewAction]]:
    """Run LLM content review with deterministic guardrail fallback."""

    rule_reviewed, rule_report, rule_actions = _rule_review_chapter(
        draft=draft,
        task=task,
        claim_ledger=claim_ledger,
        claim_evidence_map=claim_evidence_map,
        conflict_report=conflict_report,
        digest_mode=digest_mode,
    )
    task = task or ChapterGenerationTask(chapter_index=draft.chapter_index, confirmed_title=draft.title)
    try:
        llm_result = await acompletion_with_fallback(
            build_chapter_review_messages(
                chapter_title=draft.title,
                digest_mode=digest_mode,
                chapter_task=task.model_dump(mode="json"),
                markdown=draft.markdown,
                claim_ledger=(claim_ledger or ClaimLedger(chapter_index=draft.chapter_index)).model_dump(mode="json"),
                claim_evidence_map=(claim_evidence_map or ClaimEvidenceMap(chapter_index=draft.chapter_index)).model_dump(mode="json"),
                conflict_report=(conflict_report or ConflictReport(chapter_index=draft.chapter_index)).model_dump(mode="json"),
                rule_review=rule_report.model_dump(mode="json"),
            ),
            **docgen_completion_kwargs_with_metadata(
                DocGenModelStep.CHAPTER_REVIEW,
                digest_mode=digest_mode,
                chapter_index=draft.chapter_index,
                review_mode="docgen_content_review",
            ),
            response_model=LLMChapterReviewResult,
        )
        assert isinstance(llm_result, LLMChapterReviewResult)
    except Exception as exc:
        fallback_report = rule_report.model_copy(
            update={
                "warnings": [
                    *rule_report.warnings,
                    f"LLM 内容复核失败，已使用规则复核兜底：{str(exc)[:120]}",
                ],
                "fallback_used": True,
                "review_mode": "rule_fallback_after_llm_error",
            }
        )
        fallback_reviewed = ReviewedChapterDraft.model_validate(
            {
                **rule_reviewed.model_dump(mode="json"),
                "warnings": clean_string_list([*draft.warnings, *fallback_report.warnings], limit=32),
                "review_report_ref": fallback_report.report_id,
            }
        )
        return fallback_reviewed, fallback_report, rule_actions

    llm_actions = _llm_actions_to_review_actions(
        draft=draft,
        suggestions=llm_result.actions,
    )
    merged_actions = _dedupe_actions([*rule_actions, *llm_actions])
    missing = clean_string_list([*rule_report.missing_elements, *llm_result.missing_elements], limit=18)
    warnings = clean_string_list([*rule_report.warnings, *llm_result.warnings], limit=24)
    blocking_types = {"section_patch", "evidence_patch", "regenerate_chapter", "re_dispatch", "rebuild_backbone"}
    passed = llm_result.passed and not any(
        action.action_type in blocking_types and action.severity in {"warning", "error"}
        for action in merged_actions
    )
    report = ChapterReviewReport(
        report_id=rule_report.report_id,
        chapter_index=draft.chapter_index,
        passed=passed,
        coverage_score=min(rule_report.coverage_score or 1.0, llm_result.coverage_score),
        evidence_support_score=min(rule_report.evidence_support_score or 1.0, llm_result.evidence_support_score),
        quality_score=min(rule_report.quality_score or 1.0, llm_result.quality_score),
        missing_elements=missing,
        warnings=warnings,
        fallback_used=False,
        review_mode="llm_structured_with_rule_guardrails",
        llm_action_count=len(llm_actions),
        rule_action_count=len(rule_actions),
    )
    reviewed = ReviewedChapterDraft.model_validate(
        {
            **draft.model_dump(mode="json"),
            "review_report_ref": report.report_id,
            "warnings": [*draft.warnings, *warnings],
            "patched": False,
        }
    )
    return reviewed, report, merged_actions


__all__ = ["review_chapter"]
