"""Document-level knowledge backbone for DocGen."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence

from app.workflows.digest.docgen.lib.models import (
    BackboneConflictWarning,
    BackboneResearchAgenda,
    CanonicalClaim,
    CanonicalGlossaryItem,
    ChapterGenerationPlan,
    ChapterGenerationTask,
    ChapterGenerationTaskSeed,
    ConceptDependencyEdge,
    ConfusionItem,
    DocumentBackbone,
    FileMaterialSummary,
    HighConfidenceEvidenceUnit,
    NotationItem,
    clean_string_list,
)


def _claim_type(text: str) -> str:
    if any(marker in text for marker in ("公式", "定理", "性质", "$", "=")):
        return "formula"
    if any(marker in text for marker in ("例题", "题型", "练习", "应用")):
        return "example"
    if any(marker in text for marker in ("易错", "误区", "注意", "不能")):
        return "pitfall"
    if any(marker in text for marker in ("定义", "概念", "称为", "是指")):
        return "definition"
    return "core"


def _target_chapters_for_term(term: str, task_seeds: Sequence[ChapterGenerationTaskSeed]) -> list[int]:
    normalized = "".join(str(term or "").split()).casefold()
    if not normalized:
        return []
    chapters: list[int] = []
    for task in task_seeds:
        haystack = "".join(
            [
                task.confirmed_title,
                task.enhanced_title,
                task.chapter_goal,
                *task.required_elements,
                *task.retrieval_queries,
            ]
        ).casefold()
        if normalized in haystack:
            chapters.append(task.chapter_index)
    return chapters[:8]


def build_document_backbone(
    *,
    task_seeds: Sequence[ChapterGenerationTaskSeed],
    agenda: BackboneResearchAgenda,
    evidence_units: Sequence[HighConfidenceEvidenceUnit],
    file_summaries: Sequence[FileMaterialSummary],
) -> tuple[DocumentBackbone, list[BackboneConflictWarning]]:
    """Build a rule-first backbone that can never block document publication."""

    warnings: list[BackboneConflictWarning] = []
    glossary_terms = clean_string_list(
        [
            *agenda.glossary_candidates,
            *[
                item
                for task in task_seeds
                for item in task.required_elements
            ],
        ],
        limit=80,
    )
    glossary: list[CanonicalGlossaryItem] = []
    for index, term in enumerate(glossary_terms[:48], start=1):
        target_chapters = _target_chapters_for_term(term, task_seeds)
        matching_summary = next(
            (
                summary
                for summary in file_summaries
                if term in summary.definitions or term in summary.concepts
            ),
            None,
        )
        glossary.append(
            CanonicalGlossaryItem(
                term=term,
                definition=(
                    term
                    if matching_summary is None
                    else next((item for item in matching_summary.definitions if term in item), term)
                ),
                source_hint=(matching_summary.filename if matching_summary is not None else ""),
                target_chapters=target_chapters or [task_seeds[min(index - 1, len(task_seeds) - 1)].chapter_index] if task_seeds else [],
            )
        )

    claims: list[CanonicalClaim] = []
    seen_claims: set[str] = set()
    for task in task_seeds:
        for item in clean_string_list([*task.required_elements, task.chapter_goal], limit=12):
            key = f"{task.chapter_index}:{item}".casefold()
            if key in seen_claims:
                continue
            seen_claims.add(key)
            claims.append(
                CanonicalClaim(
                    claim_id=f"bb_ch{task.chapter_index:02d}_claim_{len(claims) + 1:03d}",
                    claim_type=_claim_type(item),
                    claim_text=item,
                    target_chapter=task.chapter_index,
                    importance=0.72,
                    requires_evidence=True,
                    source_hint=", ".join(task.preferred_sources[:2]),
                )
            )
    for unit in evidence_units[:40]:
        target_chapter = max(unit.chapter_affinity, key=unit.chapter_affinity.get) if unit.chapter_affinity else None
        if target_chapter is None:
            continue
        claim_text = unit.text[:180]
        key = f"{target_chapter}:{claim_text}".casefold()
        if key in seen_claims:
            continue
        seen_claims.add(key)
        claims.append(
            CanonicalClaim(
                claim_id=f"bb_ch{target_chapter:02d}_evclaim_{len(claims) + 1:03d}",
                claim_type=unit.evidence_type,
                claim_text=claim_text,
                target_chapter=target_chapter,
                importance=max(0.45, unit.confidence),
                requires_evidence=True,
                source_hint=unit.source_ref,
            )
        )

    dependency_edges: list[ConceptDependencyEdge] = []
    for previous, current in zip(task_seeds, task_seeds[1:], strict=False):
        from_concept = (previous.required_elements[:1] or [previous.enhanced_title])[0]
        to_concept = (current.required_elements[:1] or [current.enhanced_title])[0]
        if from_concept and to_concept and from_concept != to_concept:
            dependency_edges.append(
                ConceptDependencyEdge(
                    from_concept=from_concept,
                    to_concept=to_concept,
                    relation="chapter_order",
                    reason="沿 confirmed plan 章节顺序形成的前置学习关系。",
                )
            )

    notation_items = [
        NotationItem(
            symbol=item,
            meaning=item,
            target_chapters=_target_chapters_for_term(item, task_seeds),
            source_hint="material_summary",
        )
        for item in clean_string_list(agenda.notation_candidates, limit=32)
    ]
    confusion_items = [
        ConfusionItem(
            confusion_id=f"conf_{index:03d}",
            topic=item,
            contrast=item,
            resolution_hint="写作和复核阶段需要显式说明边界、误区和判断条件。",
            target_chapters=_target_chapters_for_term(item, task_seeds),
        )
        for index, item in enumerate(clean_string_list(agenda.confusion_candidates, limit=32), start=1)
    ]

    source_types = Counter(unit.source_type for unit in evidence_units)
    evidence_confidence = [unit.confidence for unit in evidence_units]
    source_trust_summary = {
        "evidence_unit_count": len(evidence_units),
        "source_type_counts": dict(source_types),
        "avg_evidence_confidence": round(sum(evidence_confidence) / len(evidence_confidence), 4) if evidence_confidence else 0.0,
        "file_summary_count": len(file_summaries),
    }
    if not evidence_units:
        warnings.append(
            BackboneConflictWarning(
                warning_id="bb_no_evidence_units",
                severity="warning",
                detail="未找到高置信证据候选，文档骨架将主要依赖 confirmed plan 和文件摘要。",
            )
        )
    term_counts = Counter(item.casefold() for item in glossary_terms)
    duplicate_terms = [term for term, count in term_counts.items() if count > 3]
    if duplicate_terms:
        warnings.append(
            BackboneConflictWarning(
                warning_id="bb_duplicate_terms",
                severity="info",
                detail="部分术语在多个章节反复出现，后续复核需要关注重复讲解。",
            )
        )
    return (
        DocumentBackbone(
            canonical_glossary=glossary,
            concept_dependency_graph=dependency_edges,
            notation_registry=notation_items,
            canonical_claim_pool=claims,
            confusion_map=confusion_items,
            source_trust_summary=source_trust_summary,
            fallback_used=False,
        ),
        warnings,
    )


def fallback_document_backbone(*, task_seeds: Sequence[ChapterGenerationTaskSeed], reason: str) -> tuple[DocumentBackbone, list[BackboneConflictWarning]]:
    claims = [
        CanonicalClaim(
            claim_id=f"fallback_ch{task.chapter_index:02d}_claim",
            claim_type="core",
            claim_text=task.chapter_goal or task.enhanced_title,
            target_chapter=task.chapter_index,
            importance=0.45,
            requires_evidence=False,
            source_hint="fallback_seed",
        )
        for task in task_seeds
    ]
    return (
        DocumentBackbone(
            canonical_claim_pool=claims,
            source_trust_summary={"fallback_reason": reason, "evidence_unit_count": 0},
            fallback_used=True,
        ),
        [
            BackboneConflictWarning(
                warning_id="bb_fallback_used",
                severity="warning",
                detail=f"知识骨架构建降级：{reason}",
            )
        ],
    )


def apply_backbone_to_chapter_plan(
    *,
    plan: ChapterGenerationPlan,
    backbone: DocumentBackbone,
) -> ChapterGenerationPlan:
    claims_by_chapter: dict[int, list[CanonicalClaim]] = defaultdict(list)
    for claim in backbone.canonical_claim_pool:
        if claim.target_chapter is not None:
            claims_by_chapter[int(claim.target_chapter)].append(claim)
    glossary_by_chapter: dict[int, list[str]] = defaultdict(list)
    for item in backbone.canonical_glossary:
        for chapter_index in item.target_chapters:
            glossary_by_chapter[int(chapter_index)].append(item.term)
    confusion_by_chapter: dict[int, list[str]] = defaultdict(list)
    for item in backbone.confusion_map:
        for chapter_index in item.target_chapters:
            confusion_by_chapter[int(chapter_index)].append(item.topic or item.contrast)

    updated_tasks: list[ChapterGenerationTask] = []
    for task in plan.chapters:
        claim_targets = clean_string_list(
            [
                *task.claim_targets,
                *[claim.claim_text for claim in claims_by_chapter.get(task.chapter_index, [])],
            ],
            limit=18,
        )
        concept_targets = clean_string_list(
            [
                *task.concept_targets,
                *glossary_by_chapter.get(task.chapter_index, []),
            ],
            limit=18,
        )
        dependency_refs = clean_string_list(
            [
                edge.from_concept
                for edge in backbone.concept_dependency_graph
                if edge.to_concept in concept_targets or edge.to_concept in task.required_elements
            ],
            limit=12,
        )
        forward_refs = clean_string_list(
            [
                edge.to_concept
                for edge in backbone.concept_dependency_graph
                if edge.from_concept in concept_targets or edge.from_concept in task.required_elements
            ],
            limit=12,
        )
        updated_tasks.append(
            task.model_copy(
                update={
                    "claim_targets": claim_targets,
                    "concept_targets": concept_targets,
                    "confusion_targets": clean_string_list(
                        [*task.confusion_targets, *confusion_by_chapter.get(task.chapter_index, [])],
                        limit=16,
                    ),
                    "dependency_refs": dependency_refs,
                    "forward_refs": forward_refs,
                    "coverage_threshold": task.coverage_threshold or 0.62,
                    "evidence_support_threshold": task.evidence_support_threshold or 0.5,
                    "repetition_tolerance": task.repetition_tolerance or 0.35,
                    "patch_tolerance": task.patch_tolerance or 0.35,
                }
            )
        )
    return plan.model_copy(update={"chapters": updated_tasks})


__all__ = [
    "apply_backbone_to_chapter_plan",
    "build_document_backbone",
    "fallback_document_backbone",
]
