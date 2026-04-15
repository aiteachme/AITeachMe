"""Small offline eval facade for RAG and generated teaching content."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .context import InfraContext


@dataclass(frozen=True, slots=True)
class EvalResult:
    name: str
    score: float
    passed: bool
    metrics: dict[str, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def _tokens(text: str) -> set[str]:
    normalized = str(text or "").lower()
    tokens = {token for token in re.findall(r"[a-z0-9_]{2,}", normalized) if token.strip()}
    for run in re.findall(r"[\u3400-\u9fff]+", normalized):
        cleaned = run.strip()
        if len(cleaned) < 2:
            continue
        tokens.add(cleaned)
        max_size = min(4, len(cleaned))
        for size in range(2, max_size + 1):
            for index in range(0, len(cleaned) - size + 1):
                tokens.add(cleaned[index : index + size])
    return tokens


def _overlap_score(left: str, right: str) -> float:
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return round(len(left_tokens & right_tokens) / max(1, len(left_tokens)), 4)


async def run_rag_eval(
    ctx: InfraContext,
    case: dict[str, Any],
    *,
    metrics: list[str] | None = None,
) -> EvalResult:
    """Run a deterministic lightweight RAG eval case."""

    requested = metrics or ["query_context_overlap", "answer_context_overlap"]
    query = str(case.get("query") or "")
    answer = str(case.get("answer") or "")
    context = str(case.get("context") or "")
    values: dict[str, float] = {}
    if "query_context_overlap" in requested:
        values["query_context_overlap"] = _overlap_score(query, context)
    if "answer_context_overlap" in requested:
        values["answer_context_overlap"] = _overlap_score(answer, context)
    score = round(sum(values.values()) / max(1, len(values)), 4)
    return EvalResult(
        name="rag_eval",
        score=score,
        passed=score >= float(case.get("threshold", 0.2) or 0.2),
        metrics=values,
        metadata=ctx.trace_metadata(),
    )


async def run_generation_eval(
    ctx: InfraContext,
    case: dict[str, Any],
    *,
    rubric: dict[str, Any] | None = None,
) -> EvalResult:
    """Run a deterministic lightweight generation eval case."""

    output = str(case.get("output") or "")
    required = [str(item).strip() for item in case.get("required_terms", []) if str(item).strip()]
    threshold = float((rubric or {}).get("threshold", case.get("threshold", 0.6)) or 0.6)
    if not required:
        length_score = min(1.0, len(output.strip()) / 200.0)
        return EvalResult(
            name="generation_eval",
            score=round(length_score, 4),
            passed=length_score >= threshold,
            metrics={"length_score": round(length_score, 4)},
            metadata=ctx.trace_metadata(),
        )
    lowered = output.lower()
    hit_count = sum(1 for term in required if term.lower() in lowered)
    score = round(hit_count / max(1, len(required)), 4)
    return EvalResult(
        name="generation_eval",
        score=score,
        passed=score >= threshold,
        metrics={"required_term_coverage": score},
        notes=[term for term in required if term.lower() not in lowered],
        metadata=ctx.trace_metadata(),
    )


__all__ = ["EvalResult", "run_generation_eval", "run_rag_eval"]
