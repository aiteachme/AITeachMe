"""Filter KnowledgeUnit candidates before blueprint planning."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from time import perf_counter

from app.models.knowledge_unit import KnowledgeUnit
from app.shared.infra.workflow import emit_progress
from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.examine.question_build.lib.generator import select_exam_knowledge_units
from app.workflows.examine.question_build.state import QuestionBuildState

EXAM_BLUEPRINT_CANDIDATE_MIN = 24
EXAM_BLUEPRINT_CANDIDATE_MAX = 60
EXAM_BLUEPRINT_CANDIDATE_PER_QUESTION = 4
_STRICT_SCOPE_MARKERS = (
    "只考",
    "仅考",
    "只练",
    "仅练",
    "只出",
    "限定",
    "考试范围",
    "考察范围",
    "考查范围",
    "范围是",
    "范围为",
)
_INCLUDE_SCOPE_MARKERS = (
    "只考",
    "仅考",
    "重点考",
    "主要考",
    "考察",
    "考查",
    "围绕",
    "关于",
    "针对",
    "复习",
    "范围",
    "章节",
)
_EXCLUDE_SCOPE_MARKERS = (
    "不考",
    "不要考",
    "别考",
    "不练",
    "不要练",
    "排除",
    "避免",
    "跳过",
    "除了",
)
_SCOPE_SPLIT_RE = re.compile(
    r"[，,。.;；:：、/\\|()\[\]{}<>《》“”\"'`]+|以及|还有|并且|或者|里的|中的|里面|之中|和|与|及|或|的|里|中"
)
_LATIN_TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9_+\-]{1,}")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_FILLER_REPLACEMENTS = (
    "这一部分",
    "这部分",
    "相关内容",
    "相关知识",
    "中等难度",
    "高难度",
    "低难度",
    "知识点",
    "内容",
    "题目",
    "试题",
    "练习",
    "考卷",
    "试卷",
    "考试",
    "测验",
    "难度",
    "范围",
    "章节",
    "单元",
    "部分",
)
_STOP_TERMS = {
    "请",
    "帮我",
    "生成",
    "生成一套",
    "一套",
    "等难度",
    "创建",
    "出",
    "考",
    "练",
    "重点",
    "主要",
    "只",
    "仅",
    "不要",
    "不用",
    "难度",
    "简单",
    "中等",
    "困难",
    "综合",
}


@dataclass(frozen=True)
class ScopeIntent:
    include_terms: list[str]
    exclude_terms: list[str]
    strict: bool = False


def exam_candidate_unit_limit(question_count: int) -> int:
    normalized_count = max(1, int(question_count or 1))
    scaled = normalized_count * EXAM_BLUEPRINT_CANDIDATE_PER_QUESTION
    return min(EXAM_BLUEPRINT_CANDIDATE_MAX, max(EXAM_BLUEPRINT_CANDIDATE_MIN, scaled))


def _unit_id(unit: KnowledgeUnit) -> int | None:
    return int(unit.id) if unit.id is not None else None


def _unit_search_text(unit: KnowledgeUnit) -> str:
    return " ".join(
        [
            str(unit.canonical_name or ""),
            str(unit.knowledge_unit_type or ""),
            str(unit.summary or ""),
        ]
    ).casefold()


def _dedupe_terms(terms: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for term in terms:
        cleaned = term.strip().casefold()
        if len(cleaned) < 2 or cleaned in _STOP_TERMS or cleaned in seen:
            continue
        seen.add(cleaned)
        deduped.append(cleaned)
    return deduped[:12]


def _clean_scope_phrase(value: str) -> str:
    cleaned = value.strip().casefold()
    for marker in [*_INCLUDE_SCOPE_MARKERS, *_EXCLUDE_SCOPE_MARKERS]:
        cleaned = cleaned.replace(marker, " ")
    for filler in _FILLER_REPLACEMENTS:
        cleaned = cleaned.replace(filler, " ")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def _phrase_terms(value: str) -> list[str]:
    cleaned = _clean_scope_phrase(value)
    if not cleaned:
        return []

    terms: list[str] = []
    for token in _SCOPE_SPLIT_RE.split(cleaned):
        token = token.strip()
        if len(token) >= 2:
            terms.append(token)
        terms.extend(_LATIN_TOKEN_RE.findall(token))
    return _dedupe_terms(terms)


def _segments_after_markers(prompt: str, markers: tuple[str, ...]) -> list[str]:
    segments: list[str] = []
    all_markers = [*_INCLUDE_SCOPE_MARKERS, *_EXCLUDE_SCOPE_MARKERS]
    for marker in markers:
        start = 0
        while True:
            index = prompt.find(marker, start)
            if index < 0:
                break
            segment = prompt[index + len(marker) :]
            stop_positions = [
                pos
                for delimiter in ["。", "；", ";", "\n"]
                for pos in [segment.find(delimiter)]
                if pos >= 0
            ]
            stop_positions.extend(
                pos
                for other_marker in all_markers
                for pos in [segment.find(other_marker)]
                if pos > 0
            )
            if stop_positions:
                segment = segment[: min(stop_positions)]
            segments.append(segment)
            start = index + len(marker)
    return segments


def _extract_scope_intent(user_prompt: str) -> ScopeIntent:
    prompt = user_prompt.strip().casefold()
    if not prompt:
        return ScopeIntent(include_terms=[], exclude_terms=[], strict=False)

    exclude_segments = _segments_after_markers(prompt, _EXCLUDE_SCOPE_MARKERS)
    exclude_terms = _dedupe_terms([term for segment in exclude_segments for term in _phrase_terms(segment)])

    include_segments = _segments_after_markers(prompt, _INCLUDE_SCOPE_MARKERS)
    include_terms = _dedupe_terms([term for segment in include_segments for term in _phrase_terms(segment)])
    if not include_terms:
        without_excludes = prompt
        for marker in _EXCLUDE_SCOPE_MARKERS:
            parts = without_excludes.split(marker)
            without_excludes = parts[0] if parts else without_excludes
        include_terms = _phrase_terms(without_excludes)

    strict = any(marker in prompt for marker in _STRICT_SCOPE_MARKERS)
    return ScopeIntent(include_terms=include_terms, exclude_terms=exclude_terms, strict=strict)


def _cjk_bigrams(value: str) -> set[str]:
    chars = [char for char in value if _CJK_RE.match(char)]
    return {chars[index] + chars[index + 1] for index in range(len(chars) - 1)}


def _term_overlap_score(term: str, text: str) -> float:
    if term in text:
        return 1.0
    term_bigrams = _cjk_bigrams(term)
    if not term_bigrams:
        return 0.0
    text_bigrams = _cjk_bigrams(text)
    if not text_bigrams:
        return 0.0
    return len(term_bigrams & text_bigrams) / max(len(term_bigrams), 1)


def _unit_scope_score(unit: KnowledgeUnit, terms: list[str]) -> float:
    if not terms:
        return 0.0
    name = str(unit.canonical_name or "").casefold()
    text = _unit_search_text(unit)
    score = 0.0
    for term in terms:
        if term in name:
            score += 8.0 + min(len(term), 12) * 0.2
            continue
        if term in text:
            score += 4.0 + min(len(term), 12) * 0.1
            continue
        overlap = max(_term_overlap_score(term, name), _term_overlap_score(term, text) * 0.8)
        if overlap >= 0.55:
            score += overlap * 3.0
    return score


def _is_excluded_by_scope(unit: KnowledgeUnit, exclude_terms: list[str]) -> bool:
    if not exclude_terms:
        return False
    return _unit_scope_score(unit, exclude_terms) >= 3.0


def _scope_ranked_units(
    units: list[KnowledgeUnit],
    intent: ScopeIntent,
    mastery_by_unit_id: dict[int, float],
) -> list[KnowledgeUnit]:
    if not intent.include_terms:
        return []
    scored: list[tuple[float, KnowledgeUnit]] = []
    for unit in units:
        if _is_excluded_by_scope(unit, intent.exclude_terms):
            continue
        score = _unit_scope_score(unit, intent.include_terms)
        if score <= 0:
            continue
        mastery_bonus = 1.0 - mastery_by_unit_id.get(int(unit.id or 0), 0.5)
        scored.append((score + mastery_bonus * 0.25, unit))
    return [
        unit
        for _score, unit in sorted(
            scored,
            key=lambda item: (-item[0], int(item[1].id or 0)),
        )
    ]


def _append_unique(target: list[KnowledgeUnit], source: list[KnowledgeUnit], seen: set[int]) -> None:
    for unit in source:
        unit_id = _unit_id(unit)
        if unit_id is None or unit_id in seen:
            continue
        seen.add(unit_id)
        target.append(unit)


def _sort_by_mastery(units: list[KnowledgeUnit], mastery_by_unit_id: dict[int, float]) -> list[KnowledgeUnit]:
    return sorted(
        units,
        key=lambda unit: (
            mastery_by_unit_id.get(int(unit.id or 0), 0.5),
            int(unit.id or 0),
        ),
    )


def _filter_candidate_units(
    *,
    units: list[KnowledgeUnit],
    exam_mode: str,
    question_count: int,
    mastery_by_unit_id: dict[int, float],
    priority_unit_ids: list[int],
    user_prompt: str,
) -> tuple[list[KnowledgeUnit], int]:
    limit = exam_candidate_unit_limit(question_count)
    unit_by_id = {int(unit.id): unit for unit in units if unit.id is not None}
    priority_units = [unit_by_id[unit_id] for unit_id in priority_unit_ids if unit_id in unit_by_id]

    scope_intent = _extract_scope_intent(user_prompt)
    scope_units = _scope_ranked_units(units, scope_intent, mastery_by_unit_id)
    candidate_source = (
        scope_units
        if scope_intent.strict and scope_units
        else [unit for unit in units if not _is_excluded_by_scope(unit, scope_intent.exclude_terms)]
    )
    weak_units = _sort_by_mastery(
        [unit for unit in candidate_source if int(unit.id or 0) in mastery_by_unit_id],
        mastery_by_unit_id,
    )
    priority_units = [unit for unit in priority_units if unit in candidate_source]

    ordered: list[KnowledgeUnit] = []
    seen: set[int] = set()
    _append_unique(ordered, scope_units, seen)

    if exam_mode == "paper_exam":
        weak_quota = max(1, limit // 2)
        _append_unique(ordered, priority_units[:weak_quota], seen)
        _append_unique(ordered, weak_units[:weak_quota], seen)
        _append_unique(ordered, candidate_source, seen)
    else:
        _append_unique(ordered, priority_units, seen)
        _append_unique(ordered, weak_units, seen)
        _append_unique(ordered, candidate_source, seen)

    return ordered[:limit], limit


def build_filter_knowledge_units_node(*, context: WorkflowContext):
    del context

    async def filter_knowledge_units_node(state: QuestionBuildState) -> dict:
        started_at = perf_counter()
        await emit_progress(
            state,
            stage="filter_exam_units",
            detail="Filtering candidate knowledge units for exam blueprint planning...",
            step="filter_knowledge_units",
        )
        try:
            input_units = list(state.get("units") or [])
            exam_mode = str(state.get("exam_mode") or "web_practice")
            question_count = int(state.get("question_count") or 1)
            mastery_by_unit_id = dict(state.get("mastery_by_unit_id") or {})
            priority_unit_ids = [
                int(unit_id)
                for unit_id in list(state.get("priority_unit_ids") or [])
                if int(unit_id or 0) > 0
            ]
            user_prompt = str(state.get("user_prompt") or "")
            limit = exam_candidate_unit_limit(question_count)
            filter_strategy = "llm_graph"
            filter_rationale = ""
            try:
                selection = await select_exam_knowledge_units(
                    subject=str(state.get("subject") or ""),
                    subject_name=str(state.get("subject_name") or ""),
                    subject_description=str(state.get("subject_description") or ""),
                    subject_user_intent=str(state.get("subject_user_intent") or ""),
                    exam_mode=exam_mode,
                    units=input_units,
                    knowledge_graph_edges=list(state.get("knowledge_graph_edges") or []),
                    question_count=question_count,
                    candidate_limit=limit,
                    mastery_by_unit_id=mastery_by_unit_id,
                    priority_unit_ids=priority_unit_ids,
                    user_prompt=user_prompt,
                    system_constraints=str(state.get("system_constraints") or ""),
                )
                unit_by_id = {int(unit.id): unit for unit in input_units if unit.id is not None}
                filtered = [unit_by_id[unit_id] for unit_id in selection.knowledge_unit_ids if unit_id in unit_by_id]
                if not filtered and input_units:
                    raise ValueError("LLM knowledge-unit selection returned no matching units")
                scope_intent = ScopeIntent(
                    include_terms=selection.scope_include_terms,
                    exclude_terms=selection.scope_exclude_terms,
                    strict=selection.scope_strict,
                )
                filter_rationale = selection.rationale
            except Exception as llm_exc:
                filtered, limit = _filter_candidate_units(
                    units=input_units,
                    exam_mode=exam_mode,
                    question_count=question_count,
                    mastery_by_unit_id=mastery_by_unit_id,
                    priority_unit_ids=priority_unit_ids,
                    user_prompt=user_prompt,
                )
                scope_intent = _extract_scope_intent(user_prompt)
                filter_strategy = "rules_fallback"
                filter_rationale = f"LLM selection failed, used rules fallback: {llm_exc}"
            candidate_unit_ids = [int(unit.id) for unit in filtered if unit.id is not None]
            elapsed_ms = int((perf_counter() - started_at) * 1000)
            await emit_progress(
                state,
                stage="filter_exam_units",
                detail=(
                    f"Selected {len(candidate_unit_ids)} candidate knowledge units "
                    f"from {len(input_units)} available units."
                ),
                step="filter_knowledge_units",
                elapsed_ms=elapsed_ms,
                extra={
                    "candidate_unit_ids": candidate_unit_ids,
                    "candidate_unit_limit": limit,
                    "input_unit_count": len(input_units),
                    "knowledge_graph_edge_count": len(list(state.get("knowledge_graph_edges") or [])),
                    "candidate_unit_count": len(candidate_unit_ids),
                    "scope_include_terms": scope_intent.include_terms,
                    "scope_exclude_terms": scope_intent.exclude_terms,
                    "scope_strict": scope_intent.strict,
                    "filter_strategy": filter_strategy,
                    "filter_rationale": filter_rationale,
                },
            )
            return {
                "units": filtered,
                "candidate_unit_ids": candidate_unit_ids,
                "candidate_unit_limit": limit,
                "input_unit_count": len(input_units),
                "knowledge_graph_edge_count": len(list(state.get("knowledge_graph_edges") or [])),
                "candidate_unit_count": len(candidate_unit_ids),
                "scope_include_terms": scope_intent.include_terms,
                "scope_exclude_terms": scope_intent.exclude_terms,
                "scope_strict": scope_intent.strict,
                "filter_strategy": filter_strategy,
                "filter_rationale": filter_rationale,
                "filter_ms": elapsed_ms,
                "error": "",
            }
        except asyncio.CancelledError:
            elapsed_ms = int((perf_counter() - started_at) * 1000)
            await emit_progress(
                state,
                stage="filter_exam_units",
                detail="知识点筛选被取消，试卷生成失败。",
                step="filter_knowledge_units",
                elapsed_ms=elapsed_ms,
            )
            return {
                "units": [],
                "candidate_unit_ids": [],
                "filter_ms": elapsed_ms,
                "error": "Question candidate filtering was cancelled.",
            }
        except Exception as exc:
            elapsed_ms = int((perf_counter() - started_at) * 1000)
            await emit_progress(
                state,
                stage="filter_exam_units",
                detail="Failed to filter candidate knowledge units.",
                step="filter_knowledge_units",
                elapsed_ms=elapsed_ms,
            )
            return {"units": [], "candidate_unit_ids": [], "filter_ms": elapsed_ms, "error": str(exc)}

    return filter_knowledge_units_node


__all__ = [
    "build_filter_knowledge_units_node",
    "exam_candidate_unit_limit",
]
