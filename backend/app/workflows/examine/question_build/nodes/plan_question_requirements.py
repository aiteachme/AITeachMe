"""Plan per-question type constraints and generation prompts."""

from __future__ import annotations

import asyncio
from time import perf_counter

from app.shared.infra.workflow import emit_progress
from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.examine.question_build.lib.generator import plan_exam_question_requirements
from app.workflows.examine.question_build.state import QuestionBuildState


def build_plan_question_requirements_node(*, context: WorkflowContext):
    del context

    async def plan_question_requirements_node(state: QuestionBuildState) -> dict:
        if state.get("error"):
            return {}

        started_at = perf_counter()
        await emit_progress(
            state,
            stage="plan_question_requirements",
            detail="Planning per-question types and generation constraints...",
            step="plan_question_requirements",
        )
        try:
            planned = await plan_exam_question_requirements(
                exam_mode=str(state.get("exam_mode") or "web_practice"),
                question_count=int(state.get("question_count") or 1),
                user_prompt=str(state.get("user_prompt") or ""),
            )
            prompt_payload = [item.model_dump(mode="json") for item in planned]

            elapsed_ms = int((perf_counter() - started_at) * 1000)
            await emit_progress(
                state,
                stage="plan_question_requirements",
                detail=f"Planned types and generation constraints for {len(prompt_payload)} questions.",
                step="plan_question_requirements",
                elapsed_ms=elapsed_ms,
                extra={"question_requirement_plans": prompt_payload},
            )
            return {
                "question_requirement_plans": prompt_payload,
                "requirements_plan_ms": elapsed_ms,
                "error": "",
            }
        except asyncio.CancelledError:
            elapsed_ms = int((perf_counter() - started_at) * 1000)
            await emit_progress(
                state,
                stage="plan_question_requirements",
                detail="Question type and generation-constraint planning was cancelled.",
                step="plan_question_requirements",
                elapsed_ms=elapsed_ms,
            )
            return {
                "question_requirement_plans": [],
                "requirements_plan_ms": elapsed_ms,
                "error": "Question prompt planning was cancelled.",
            }
        except Exception as exc:
            elapsed_ms = int((perf_counter() - started_at) * 1000)
            await emit_progress(
                state,
                stage="plan_question_requirements",
                detail="Question type and generation-constraint planning failed.",
                step="plan_question_requirements",
                elapsed_ms=elapsed_ms,
            )
            return {
                "question_requirement_plans": [],
                "requirements_plan_ms": elapsed_ms,
                "error": str(exc),
            }

    return plan_question_requirements_node


__all__ = ["build_plan_question_requirements_node"]
