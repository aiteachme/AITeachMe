"""Chapter-level review for enhanced DocGen drafts."""

from __future__ import annotations

from app.shared.infra.tools.builtin.markdown_processing import count_words
from app.workflows.digest.docgen.lib.claims import evidence_support_score
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


def _coverage(markdown: str, targets: list[str]) -> tuple[float, list[str]]:
    if not targets:
        return 1.0, []
    normalized = "".join(str(markdown or "").split()).casefold()
    missing: list[str] = []
    hits = 0
    for target in targets:
        needle = "".join(str(target or "").split()).casefold()
        if needle and needle in normalized:
            hits += 1
        else:
            missing.append(target)
    return round(hits / max(1, len(targets)), 4), missing


def review_chapter(
    *,
    draft: EnhancedChapterDraft,
    task: ChapterGenerationTask | None,
    claim_ledger: ClaimLedger | None,
    claim_evidence_map: ClaimEvidenceMap | None,
    conflict_report: ConflictReport | None,
) -> tuple[ReviewedChapterDraft, ChapterReviewReport, list[ReviewAction]]:
    task = task or ChapterGenerationTask(chapter_index=draft.chapter_index, confirmed_title=draft.title)
    targets = clean_string_list([*task.required_elements, *task.claim_targets], limit=18)
    coverage_score, missing = _coverage(draft.markdown, targets)
    support_score = evidence_support_score(claim_evidence_map or ClaimEvidenceMap(chapter_index=draft.chapter_index))
    quality_score = draft.quality_signals.quality_score or 0.0
    word_count = count_words(draft.markdown)
    warnings: list[str] = []
    actions: list[ReviewAction] = []
    if missing:
        warnings.append("章节未完全覆盖执行合同中的关键点。")
        actions.append(
            ReviewAction(
                action_id=f"review_ch{draft.chapter_index:02d}_section_patch",
                action_type="section_patch",
                chapter_index=draft.chapter_index,
                severity="warning",
                reason="缺少关键覆盖点：" + "、".join(missing[:5]),
            )
        )
    if support_score < task.evidence_support_threshold and list((claim_ledger or ClaimLedger()).items or []):
        warnings.append("部分主张证据支撑偏弱。")
        actions.append(
            ReviewAction(
                action_id=f"review_ch{draft.chapter_index:02d}_evidence",
                action_type="regenerate_chapter",
                chapter_index=draft.chapter_index,
                severity="warning",
                reason="主张证据支撑低于阈值。",
            )
        )
    if word_count < task.min_word_count:
        warnings.append("章节长度低于最低字数要求。")
        actions.append(
            ReviewAction(
                action_id=f"review_ch{draft.chapter_index:02d}_surface_length",
                action_type="surface_patch",
                chapter_index=draft.chapter_index,
                severity="info",
                reason="章节偏短，MVP 仅记录并发布。",
            )
        )
    unresolved_conflicts = int((conflict_report or ConflictReport()).unresolved_count or 0)
    if unresolved_conflicts > 0:
        warnings.append("仍存在未解决的低证据或冲突提示。")
    passed = not any(action.action_type in {"regenerate_chapter", "re_dispatch", "rebuild_backbone"} for action in actions)
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


__all__ = ["review_chapter"]
