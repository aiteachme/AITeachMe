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
            elapsed_ms = int((perf_counter() - started_at) * 1000)
            await emit_progress(
                state,
                stage="filter_exam_units",
                detail="Knowledge-unit filtering was cancelled.",
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
