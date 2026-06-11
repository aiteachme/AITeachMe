"""DocGen quality ledgers, evidence alignment, conflicts, and merge review."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from app.shared.infra.llm_support import acompletion_with_fallback, run_llm_tasks
from app.shared.infra.tools.builtin.markdown_processing import count_words
from app.workflows.digest.docgen.lib.model_policy import DocGenModelStep, docgen_completion_kwargs_with_metadata
from app.workflows.digest.docgen.lib.models import (
    ChapterGenerationTask,
    ClaimEvidenceBinding,
    ClaimEvidenceMap,
    ClaimItem,
    ClaimLedger,
    ConflictItem,
    ConflictReport,
    DocumentBackbone,
    DocumentConsistencyReport,
    EnhancedChapterDraft,
    EvidenceItem,
    EvidenceLedger,
    LLMDocumentConsistencyReviewResult,
    MergeReviewIssue,
    MergeReviewReport,
    ReviewAction,
    ReviewedChapterDraft,
    clean_string_list,
    clean_unit_float,
)
from app.workflows.digest.docgen.prompts.document_review import build_document_review_messages

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？!?；;])\s+|\n+")


def _source_type(url: str) -> str:
    if str(url or "").startswith("local://"):
        return "local"
    if str(url or "").strip():
        return "web"
    return "generated"


def _candidate_claims(dense_context: str, targets: Sequence[str], *, limit: int) -> list[str]:
    target_terms = clean_string_list(targets, limit=16)
    fragments = [
        fragment.strip(" -")
        for fragment in _SENTENCE_SPLIT_RE.split(str(dense_context or ""))
        if 12 <= len(fragment.strip()) <= 180
    ]
    ranked: list[tuple[int, int, str]] = []
    for fragment in fragments:
        hit_count = sum(1 for term in target_terms if term and term in fragment)
        ranked.append((hit_count, len(fragment), fragment))
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    claims: list[str] = []
    seen: set[str] = set()
    for score, _length, fragment in ranked:
        if score <= 0 and claims:
            continue
        key = fragment.casefold()
        if key in seen:
            continue
        seen.add(key)
        claims.append(fragment)
        if len(claims) >= limit:
            break
    return claims


def build_evidence_ledger(
    *,
    chapter_index: int,
    dense_context: str,
    source_details: Sequence[Mapping[str, Any]],
    targets: Sequence[str],
) -> EvidenceLedger:
    claims = _candidate_claims(dense_context, targets, limit=10)
    sources = list(source_details or [])
    items: list[EvidenceItem] = []
    for index, claim in enumerate(claims, start=1):
        source = sources[(index - 1) % len(sources)] if sources else {}
        url = str(source.get("url") or "")
        items.append(
            EvidenceItem(
                evidence_id=f"ch{chapter_index:02d}_ev{index:03d}",
                kind="core",
                claim=claim[:180],
                source_type=_source_type(url),
                source_ref=url or f"generated://chapter/{chapter_index}",
                source_title=str(source.get("title") or ""),
                source_span=str(source.get("source") or source.get("chunk_uid") or ""),
                confidence=0.84 if url.startswith("local://") else (0.68 if url else 0.45),
                used_in_markdown=False,
            )
        )
    return EvidenceLedger(chapter_index=chapter_index, items=items)


def mark_evidence_used(ledger: EvidenceLedger, markdown: str) -> EvidenceLedger:
    normalized = "".join(str(markdown or "").split()).casefold()
    updated: list[EvidenceItem] = []
    for item in ledger.items:
        claim_key = "".join(item.claim[:40].split()).casefold()
        updated.append(item.model_copy(update={"used_in_markdown": bool(claim_key and claim_key in normalized)}))
    return ledger.model_copy(update={"items": updated})


def build_claim_ledger(
    *,
    task: ChapterGenerationTask,
    evidence_ledger: EvidenceLedger,
    document_backbone: DocumentBackbone | None = None,
) -> ClaimLedger:
    backbone_claims = [
        claim.claim_text
        for claim in list((document_backbone or DocumentBackbone()).canonical_claim_pool)
        if claim.target_chapter == task.chapter_index and claim.claim_text
    ]
    claim_texts = clean_string_list(
        [
            *task.claim_targets,
            *backbone_claims,
            *[item.claim for item in evidence_ledger.items if item.claim],
            *task.required_elements,
        ],
        limit=16,
    )
    items: list[ClaimItem] = []
    for index, claim_text in enumerate(claim_texts, start=1):
        items.append(
            ClaimItem(
                claim_id=f"ch{task.chapter_index:02d}_claim_{index:03d}",
                chapter_index=task.chapter_index,
                claim_type="core",
                claim_text=claim_text[:240],
                importance=0.78 if claim_text in task.claim_targets else 0.58,
                requires_evidence=True,
                source_hint="chapter_task_or_backbone",
            )
        )
    if not items:
        items.append(
            ClaimItem(
                claim_id=f"ch{task.chapter_index:02d}_claim_001",
                chapter_index=task.chapter_index,
                claim_type="core",
                claim_text=task.objective or task.enhanced_title,
                importance=0.4,
                requires_evidence=False,
                source_hint="task_objective",
            )
        )
        return ClaimLedger(chapter_index=task.chapter_index, items=items, fallback_used=True)
    return ClaimLedger(chapter_index=task.chapter_index, items=items)


def align_claim_evidence(
    *,
    claim_ledger: ClaimLedger,
    evidence_ledger: EvidenceLedger,
) -> tuple[ClaimLedger, ClaimEvidenceMap]:
    evidence_items = list(evidence_ledger.items or [])
    bindings: list[ClaimEvidenceBinding] = []
    updated_claims: list[ClaimItem] = []
    for claim in claim_ledger.items:
        claim_blob = "".join(claim.claim_text.split()).casefold()
        scored: list[tuple[float, str]] = []
        for evidence in evidence_items:
            evidence_blob = "".join(evidence.claim.split()).casefold()
            overlap = 0.0
            if claim_blob and evidence_blob:
                if claim_blob[:24] in evidence_blob or evidence_blob[:24] in claim_blob:
                    overlap = 0.8
                else:
                    claim_terms = set(claim_blob[i : i + 2] for i in range(0, max(0, len(claim_blob) - 1), 2))
                    evidence_terms = set(evidence_blob[i : i + 2] for i in range(0, max(0, len(evidence_blob) - 1), 2))
                    overlap = len(claim_terms & evidence_terms) / max(1, len(claim_terms | evidence_terms))
            score = max(overlap, evidence.confidence * 0.6)
            if score > 0.18:
                scored.append((score, evidence.evidence_id))
        scored.sort(reverse=True)
        evidence_ids = [evidence_id for _score, evidence_id in scored[:3]]
        support_level = clean_unit_float(scored[0][0] if scored else 0.0)
        bindings.append(
            ClaimEvidenceBinding(
                claim_id=claim.claim_id,
                evidence_ids=evidence_ids,
                support_level=support_level,
                notes="aligned_by_text_overlap" if evidence_ids else "no_evidence_aligned",
            )
        )
        updated_claims.append(claim.model_copy(update={"evidence_ids": evidence_ids}))
    return (
        claim_ledger.model_copy(update={"items": updated_claims}),
        ClaimEvidenceMap(
            chapter_index=claim_ledger.chapter_index,
            bindings=bindings,
            fallback_used=claim_ledger.fallback_used,
        ),
    )


def evidence_support_score(claim_evidence_map: ClaimEvidenceMap) -> float:
    bindings = list(claim_evidence_map.bindings or [])
    if not bindings:
        return 0.0
    return round(sum(binding.support_level for binding in bindings) / len(bindings), 4)


def resolve_conflicts_for_chapter(
    *,
    task: ChapterGenerationTask,
    evidence_ledger: EvidenceLedger,
    document_backbone: DocumentBackbone | None = None,
) -> ConflictReport:
    items: list[ConflictItem] = []
    backbone = document_backbone or DocumentBackbone()
    unresolved_count = 0
    for index, confusion in enumerate(backbone.confusion_map, start=1):
        if confusion.target_chapters and task.chapter_index not in confusion.target_chapters:
            continue
        topic = confusion.topic or confusion.contrast
        if not topic:
            continue
        if topic in task.confusion_targets or topic in task.required_elements or not confusion.target_chapters:
            items.append(
                ConflictItem(
                    conflict_id=f"ch{task.chapter_index:02d}_conf_{index:03d}",
                    chapter_index=task.chapter_index,
                    conflict_type="confusion_target",
                    severity="info",
                    detail=f"本章需要显式处理易混点：{topic}",
                    resolution=confusion.resolution_hint or "正文中说明边界和判断条件。",
                    source_refs=[],
                )
            )
    low_confidence = [
        item
        for item in evidence_ledger.items
        if item.confidence < task.evidence_support_threshold and item.source_type == "generated"
    ]
    if low_confidence:
        unresolved_count += len(low_confidence)
        items.append(
            ConflictItem(
                conflict_id=f"ch{task.chapter_index:02d}_low_evidence",
                chapter_index=task.chapter_index,
                conflict_type="low_evidence_support",
                severity="warning",
                detail="部分主张缺少可靠资料支撑，章节需要使用不确定性表达。",
                resolution="避免宣称为真题、权威结论或材料明确内容；保留降级说明。",
                source_refs=clean_string_list([item.source_ref for item in low_confidence], limit=8),
            )
        )
    return ConflictReport(
        chapter_index=task.chapter_index,
        items=items,
        unresolved_count=unresolved_count,
    )


def review_document_consistency(
    *,
    reviewed_chapters: list[ReviewedChapterDraft],
    document_backbone: DocumentBackbone,
    expected_chapter_count: int,
) -> DocumentConsistencyReport:
    issues: list[dict[str, object]] = []
    if expected_chapter_count and len(reviewed_chapters) != expected_chapter_count:
        issues.append(
            {
                "severity": "warning",
                "issue_type": "chapter_count",
                "detail": f"预期 {expected_chapter_count} 章，实际可发布 {len(reviewed_chapters)} 章。",
            }
        )
    titles = [chapter.title.strip() for chapter in reviewed_chapters if chapter.title.strip()]
    title_counts = Counter(title.casefold() for title in titles)
    duplicate_titles = [title for title, count in title_counts.items() if count > 1]
    if duplicate_titles:
        issues.append(
            {
                "severity": "warning",
                "issue_type": "duplicate_title",
                "detail": "存在重复章节标题。",
            }
        )
    glossary_terms = [item.term for item in document_backbone.canonical_glossary if item.term]
    glossary_warnings: list[str] = []
    if glossary_terms:
        merged_markdown = "\n".join(chapter.markdown for chapter in reviewed_chapters)
        normalized = "".join(merged_markdown.split()).casefold()
        missing_terms = [
            term
            for term in glossary_terms[:24]
            if "".join(term.split()).casefold() not in normalized
        ]
        if missing_terms:
            glossary_warnings.append("部分骨架术语未在正文中显式出现：" + "、".join(missing_terms[:8]))
    source_summary = {
        "chapter_count": len(reviewed_chapters),
        "source_count": sum(len(chapter.source_details) for chapter in reviewed_chapters),
        "fallback_chapter_count": sum(1 for chapter in reviewed_chapters if chapter.fallback_used),
        "backbone_fallback_used": document_backbone.fallback_used,
    }
    return DocumentConsistencyReport(
        passed=not issues,
        issues=issues,
        glossary_warnings=glossary_warnings,
        source_summary=source_summary,
        fallback_used=False,
    )


def _merge_document_review_report(
    *,
    rule_report: DocumentConsistencyReport,
    llm_result: LLMDocumentConsistencyReviewResult,
) -> DocumentConsistencyReport:
    issues = [
        *list(rule_report.issues or []),
        *list(llm_result.issues or []),
    ][:24]
    glossary_warnings = clean_string_list(
        [
            *list(rule_report.glossary_warnings or []),
            *list(llm_result.glossary_warnings or []),
            *list(llm_result.warnings or []),
        ],
        limit=24,
    )
    has_error_issue = any(str(item.get("severity") or "") == "error" for item in issues if isinstance(item, dict))
    return DocumentConsistencyReport(
        passed=rule_report.passed and llm_result.passed and not has_error_issue,
        issues=issues,
        glossary_warnings=glossary_warnings,
        source_summary={
            **dict(rule_report.source_summary or {}),
            "document_review_mode": "llm_structured_with_rule_guardrails",
            "llm_issue_count": len(list(llm_result.issues or [])),
            "llm_action_count": len(list(llm_result.actions or [])),
        },
        fallback_used=False,
    )


def _document_review_actions(llm_result: LLMDocumentConsistencyReviewResult) -> list[ReviewAction]:
    actions: list[ReviewAction] = []
    for index, action in enumerate(list(llm_result.actions or []), start=1):
        action_id = action.action_id or f"document_review_{index:02d}_{action.action_type}"
        actions.append(action.model_copy(update={"action_id": action_id, "status": "recorded"}))
    return actions


async def review_document_consistency_with_llm(
    *,
    reviewed_chapters: list[ReviewedChapterDraft],
    document_backbone: DocumentBackbone,
    expected_chapter_count: int,
    digest_mode: str = "",
    guideline: dict[str, Any] | None = None,
    dispatch_table: dict[str, Any] | None = None,
    learner_profile_text: str = "",
) -> tuple[DocumentConsistencyReport, list[ReviewAction], int]:
    """Run deterministic whole-document review, then one bounded LLM review."""

    rule_report = review_document_consistency(
        reviewed_chapters=reviewed_chapters,
        document_backbone=document_backbone,
        expected_chapter_count=expected_chapter_count,
    )
    async def _run_document_review(_: object) -> LLMDocumentConsistencyReviewResult:
        result = await acompletion_with_fallback(
            build_document_review_messages(
                digest_mode=digest_mode,
                reviewed_chapters=[chapter.model_dump(mode="json") for chapter in reviewed_chapters],
                rule_report=rule_report.model_dump(mode="json"),
                guideline=guideline or {},
                dispatch_table=dispatch_table or {},
                learner_profile_text=learner_profile_text,
            ),
            **docgen_completion_kwargs_with_metadata(
                DocGenModelStep.DOCUMENT_REVIEW,
                digest_mode=digest_mode,
                chapter_count=len(reviewed_chapters),
                rule_issue_count=len(rule_report.issues),
            ),
            response_model=LLMDocumentConsistencyReviewResult,
        )
        assert isinstance(result, LLMDocumentConsistencyReviewResult)
        return result

    try:
        (llm_result,) = await run_llm_tasks([None], _run_document_review, max_concurrent=1)
    except Exception as exc:
        fallback_report = rule_report.model_copy(
            update={
                "fallback_used": True,
                "source_summary": {
                    **dict(rule_report.source_summary or {}),
                    "document_review_mode": "rule_fallback_after_llm_error",
                    "llm_error_type": type(exc).__name__,
                    "llm_error": str(exc)[:180],
                },
            }
        )
        return fallback_report, [], 1
    return _merge_document_review_report(rule_report=rule_report, llm_result=llm_result), _document_review_actions(llm_result), 1


def build_merge_review_report(
    *,
    enhanced_chapters: list[EnhancedChapterDraft],
    expected_chapter_count: int,
    plan: str,
) -> MergeReviewReport:
    """生成发布前的整本合并检查报告。"""

    del plan
    issues: list[MergeReviewIssue] = []
    if len(enhanced_chapters) != expected_chapter_count:
        issues.append(
            MergeReviewIssue(
                severity="warning",
                issue_type="chapter_count",
                detail=f"增强章节数 {len(enhanced_chapters)} 与计划章节数 {expected_chapter_count} 不一致。",
                suggestion="检查失败章节并决定是否重新生成。",
            )
        )
    title_counts = Counter(chapter.title.strip() for chapter in enhanced_chapters if chapter.title.strip())
    for title, count in title_counts.items():
        if count > 1:
            issues.append(
                MergeReviewIssue(
                    severity="warning",
                    issue_type="duplicate_title",
                    detail=f"章节标题重复：{title}",
                    suggestion="后续可在章节增强中细化标题。",
                )
            )
    low_quality = [
        chapter
        for chapter in enhanced_chapters
        if chapter.quality_signals.quality_score and chapter.quality_signals.quality_score < 0.55
    ]
    for chapter in low_quality[:5]:
        issues.append(
            MergeReviewIssue(
                severity="warning",
                chapter_index=chapter.chapter_index,
                issue_type="quality",
                detail=f"章节质量分偏低：{chapter.quality_signals.quality_score}",
                suggestion="可重新生成或人工复核该章。",
            )
        )
    no_sources = [chapter for chapter in enhanced_chapters if not chapter.source_details]
    for chapter in no_sources[:5]:
        issues.append(
            MergeReviewIssue(
                severity="warning",
                chapter_index=chapter.chapter_index,
                issue_type="source",
                detail="章节缺少可追踪来源。",
                suggestion="建议补充本地资料或允许外部检索。",
            )
        )
    total_words = sum(count_words(chapter.markdown) for chapter in enhanced_chapters)
    decision = "publish" if not issues else "publish_with_warnings"
    return MergeReviewReport(
        passed=not any(issue.severity == "error" for issue in issues),
        decision=decision,
        issues=issues,
        coverage_summary={
            "chapter_count": len(enhanced_chapters),
            "expected_chapter_count": expected_chapter_count,
            "total_words": total_words,
        },
        style_summary={
            "duplicate_title_count": sum(1 for _title, count in title_counts.items() if count > 1),
            "low_quality_chapter_count": len(low_quality),
        },
        source_summary={
            "chapters_without_sources": [chapter.chapter_index for chapter in no_sources],
            "chapter_source_count": {
                str(chapter.chapter_index): len(chapter.source_details)
                for chapter in enhanced_chapters
            },
        },
    )


__all__ = [
    "align_claim_evidence",
    "build_claim_ledger",
    "build_evidence_ledger",
    "build_merge_review_report",
    "evidence_support_score",
    "mark_evidence_used",
    "resolve_conflicts_for_chapter",
    "review_document_consistency",
    "review_document_consistency_with_llm",
]
