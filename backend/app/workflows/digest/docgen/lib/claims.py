"""Claim ledger and evidence alignment helpers for DocGen."""

from __future__ import annotations

from collections.abc import Sequence

from app.workflows.digest.docgen.lib.models import (
    ChapterGenerationTask,
    ClaimEvidenceBinding,
    ClaimEvidenceMap,
    ClaimItem,
    ClaimLedger,
    DocumentBackbone,
    EvidenceLedger,
    clean_string_list,
    clean_unit_float,
)


def _claim_type(text: str) -> str:
    if any(marker in text for marker in ("公式", "定理", "性质", "$", "=")):
        return "formula"
    if any(marker in text for marker in ("例", "题", "应用", "场景")):
        return "example"
    if any(marker in text for marker in ("易错", "误区", "注意", "不能", "陷阱")):
        return "pitfall"
    if any(marker in text for marker in ("定义", "概念", "称为", "是指")):
        return "definition"
    return "core"


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
                claim_type=_claim_type(claim_text),
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
                source_hint="fallback_task_objective",
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


__all__ = ["align_claim_evidence", "build_claim_ledger", "evidence_support_score"]
