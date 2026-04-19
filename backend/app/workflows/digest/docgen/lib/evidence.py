"""Evidence ledger extraction for DocGen chapters."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from app.workflows.digest.docgen.lib.models import EvidenceItem, EvidenceLedger, clean_string_list

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？!?；;])\s+|\n+")
_FORMULA_MARKERS = ("公式", "定理", "性质", "$", "=")
_METHOD_MARKERS = ("步骤", "方法", "算法", "路径", "流程", "判断")
_EXAMPLE_MARKERS = ("例", "题", "应用", "场景")
_PITFALL_MARKERS = ("易错", "误区", "注意", "不能", "陷阱")


def _source_type(url: str) -> str:
    if str(url or "").startswith("local://"):
        return "local"
    if str(url or "").strip():
        return "web"
    return "generated"


def _kind_for_claim(text: str) -> str:
    if any(marker in text for marker in _FORMULA_MARKERS):
        return "formula"
    if any(marker in text for marker in _METHOD_MARKERS):
        return "method"
    if any(marker in text for marker in _EXAMPLE_MARKERS):
        return "example"
    if any(marker in text for marker in _PITFALL_MARKERS):
        return "pitfall"
    if any(marker in text for marker in ("定义", "概念", "称为", "是指")):
        return "definition"
    return "background"


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
        marker_bonus = 1 if _kind_for_claim(fragment) != "background" else 0
        ranked.append((hit_count + marker_bonus, len(fragment), fragment))
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
                kind=_kind_for_claim(claim),
                claim=claim[:180],
                source_type=_source_type(url),
                source_ref=url or f"generated://chapter/{chapter_index}",
                source_title=str(source.get("title") or ""),
                source_span=str(source.get("source") or source.get("chunk_uid") or ""),
                confidence=0.84 if url.startswith("local://") else (0.68 if url else 0.45),
                used_in_markdown=False,
            )
        )
    if not items:
        items.append(
            EvidenceItem(
                evidence_id=f"ch{chapter_index:02d}_ev001",
                kind="background",
                claim="当前章节缺少可抽取的细粒度证据，已退回基于章节合同生成。",
                source_type="generated",
                source_ref=f"generated://chapter/{chapter_index}",
                confidence=0.35,
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


__all__ = ["build_evidence_ledger", "mark_evidence_used"]
