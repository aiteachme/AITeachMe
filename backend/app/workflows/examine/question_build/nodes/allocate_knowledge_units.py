"""Allocate knowledge units after question types and requirements are planned."""

from __future__ import annotations

import asyncio
from time import perf_counter

from app.shared.infra.workflow import emit_progress
from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.examine.question_build.lib.generator import (
    ExamQuestionRequirementPlan,
    allocate_exam_question_knowledge_units,
)
from app.workflows.examine.question_build.state import QuestionBuildState


def build_allocate_knowledge_units_node(*, context: WorkflowContext):
    del context

    async def allocate_knowledge_units_node(state: QuestionBuildState) -> dict:
        if state.get("error"):
            return {}

        started_at = perf_counter()
        await emit_progress(
            state,
            stage="allocate_knowledge_units",
            detail="Allocating knowledge units for each planned question...",
            step="allocate_knowledge_units",
        )
        try:
            planned = await allocate_exam_question_knowledge_units(
                course_id=str(state.get("course_id") or ""),
                course_name=str(state.get("course_name") or ""),
                course_description=str(state.get("course_description") or ""),
                course_user_intent=str(state.get("course_user_intent") or ""),
                exam_mode=str(state.get("exam_mode") or "web_practice"),
                units=list(state.get("units") or []),
                question_count=int(state.get("question_count") or 1),
                mastery_by_unit_id=dict(state.get("mastery_by_unit_id") or {}),
                question_prompt_plans=[
                    ExamQuestionRequirementPlan.model_validate(item)
                    for item in list(state.get("question_requirement_plans") or [])
                ],
                user_prompt=str(state.get("user_prompt") or ""),
                system_constraints=str(state.get("system_constraints") or ""),
            )
            blueprint_payload = [item.model_dump(mode="json") for item in planned]

            elapsed_ms = int((perf_counter() - started_at) * 1000)
            await emit_progress(
                state,
                stage="allocate_knowledge_units",
                detail=f"Allocated knowledge units for {len(blueprint_payload)} questions.",
                step="allocate_knowledge_units",
                elapsed_ms=elapsed_ms,
                extra={"question_blueprints": blueprint_payload},
            )
            return {"question_blueprints": blueprint_payload, "allocate_ms": elapsed_ms, "error": ""}
        except asyncio.CancelledError:
            elapsed_ms = int((perf_counter() - started_at) * 1000)
            await emit_progress(
                state,
                stage="allocate_knowledge_units",
                detail="Knowledge-unit allocation was cancelled.",
                step="allocate_knowledge_units",
                elapsed_ms=elapsed_ms,
            )
            return {
                "question_blueprints": [],
                "allocate_ms": elapsed_ms,
                "error": "Knowledge-unit allocation was cancelled.",
            }
        except Exception as exc:
            elapsed_ms = int((perf_counter() - started_at) * 1000)
            await emit_progress(
                state,
                stage="allocate_knowledge_units",
                detail="Knowledge-unit allocation failed.",
                step="allocate_knowledge_units",
                elapsed_ms=elapsed_ms,
            )
            return {"question_blueprints": [], "allocate_ms": elapsed_ms, "error": str(exc)}

    return allocate_knowledge_units_node


__all__ = ["build_allocate_knowledge_units_node"]
