"""Filter KnowledgeUnit candidates before blueprint planning."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from time import perf_counter

from app.shared.infra.workflow import emit_progress
from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.examine.question_build.lib.generator import select_exam_knowledge_units
from app.workflows.support.exam_pool_policy import exam_candidate_unit_limit
from app.workflows.examine.question_build.state import QuestionBuildState



@dataclass(frozen=True)
class ScopeIntent:
    include_terms: list[str]
    exclude_terms: list[str]
    strict: bool = False


def _unit_id(unit: object) -> int:
    return _positive_int(getattr(unit, "id", 0))


def _positive_int(value: object) -> int:
    try:
        normalized = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return normalized if normalized > 0 else 0


def _fallback_candidate_unit_ids(
    *,
    units: list[object],
    priority_unit_ids: list[int],
    limit: int,
) -> list[int]:
    available_ids = [_unit_id(unit) for unit in units]
    available_ids = [unit_id for unit_id in available_ids if unit_id > 0]
    available_set = set(available_ids)
    selected: list[int] = []
    for unit_id in [*priority_unit_ids, *available_ids]:
        normalized = int(unit_id or 0)
        if normalized <= 0 or normalized not in available_set or normalized in selected:
            continue
        selected.append(normalized)
        if len(selected) >= max(1, int(limit or 1)):
            break
    return selected


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
                unit_id
                for unit_id in (_positive_int(item) for item in list(state.get("priority_unit_ids") or []))
                if unit_id > 0
            ]
            user_prompt = str(state.get("user_prompt") or "")
            limit = exam_candidate_unit_limit(question_count)
            filter_strategy = "llm_graph"
            filter_rationale = ""

            async def fallback_result(*, reason: str, detail: str) -> dict:
                candidate_unit_ids = _fallback_candidate_unit_ids(
                    units=input_units,
                    priority_unit_ids=priority_unit_ids,
                    limit=limit,
                )
                unit_by_id = {_unit_id(unit): unit for unit in input_units if _unit_id(unit) > 0}
                filtered = [unit_by_id[unit_id] for unit_id in candidate_unit_ids if unit_id in unit_by_id]
                if not filtered and input_units:
                    filtered = input_units[: max(1, min(len(input_units), int(limit or 1)))]
                    candidate_unit_ids = [_unit_id(unit) for unit in filtered if _unit_id(unit) > 0]
                elapsed_ms = int((perf_counter() - started_at) * 1000)
                await emit_progress(
                    state,
                    stage="filter_exam_units",
                    detail=(
                        f"Selected {len(candidate_unit_ids)} candidate knowledge units "
                        f"with fallback because {detail}"
                    ),
                    step="filter_knowledge_units",
                    elapsed_ms=elapsed_ms,
                    extra={
                        "candidate_unit_ids": candidate_unit_ids,
                        "candidate_unit_limit": limit,
                        "input_unit_count": len(input_units),
                        "knowledge_graph_edge_count": len(list(state.get("knowledge_graph_edges") or [])),
                        "candidate_unit_count": len(candidate_unit_ids),
                        "scope_include_terms": [],
                        "scope_exclude_terms": [],
                        "scope_strict": False,
                        "filter_strategy": reason,
                        "filter_rationale": detail,
                    },
                )
                return {
                    "units": filtered,
                    "candidate_unit_ids": candidate_unit_ids,
                    "candidate_unit_limit": limit,
                    "input_unit_count": len(input_units),
                    "knowledge_graph_edge_count": len(list(state.get("knowledge_graph_edges") or [])),
                    "candidate_unit_count": len(candidate_unit_ids),
                    "scope_include_terms": [],
                    "scope_exclude_terms": [],
                    "scope_strict": False,
                    "filter_strategy": reason,
                    "filter_rationale": detail,
                    "filter_ms": elapsed_ms,
                    "error": "" if candidate_unit_ids else detail,
                }

            selection = await select_exam_knowledge_units(
                course_id=str(state.get("course_id") or ""),
                course_name=str(state.get("course_name") or ""),
                course_description=str(state.get("course_description") or ""),
                course_user_intent=str(state.get("course_user_intent") or ""),
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
            task = asyncio.current_task()
            if task is not None and task.cancelling():
                raise
            elapsed_ms = int((perf_counter() - started_at) * 1000)
            await emit_progress(
                state,
                stage="filter_exam_units",
                detail="Knowledge-unit filtering was cancelled.",
                step="filter_knowledge_units",
                elapsed_ms=elapsed_ms,
            )
            return await fallback_result(
                reason="deterministic_cancel_fallback",
                detail="Question candidate filtering was cancelled.",
            )
        except Exception as exc:
            return await fallback_result(
                reason="deterministic_error_fallback",
                detail=str(exc),
            )

    return filter_knowledge_units_node


__all__ = [
    "build_filter_knowledge_units_node",
    "exam_candidate_unit_limit",
]
