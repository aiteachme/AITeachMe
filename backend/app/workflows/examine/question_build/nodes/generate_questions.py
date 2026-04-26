"""Generate exam questions and emit compact progress events."""

from __future__ import annotations

from time import perf_counter

from app.shared.infra.workflow import emit_progress
from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.examine.question_build.lib.generator import (
    ExamQuestionBlueprint,
    generate_exam_questions_for_units,
)
from app.workflows.examine.question_build.state import QuestionBuildState


def build_generate_questions_node(*, context: WorkflowContext):
    del context

    async def generate_questions_node(state: QuestionBuildState) -> dict:
        if state.get("error"):
            return {}

        started_at = perf_counter()
        await emit_progress(
            state,
            stage="generate_exam_questions",
            detail="正在基于知识点生成高质量考题...",
            step="generate_questions",
        )
        try:
            blueprints = [
                ExamQuestionBlueprint.model_validate(item)
                for item in list(state.get("question_blueprints") or [])
            ]
            if not blueprints:
                raise ValueError("question blueprint planning returned no items")
            specs = [blueprint.to_generation_spec() for blueprint in blueprints]
            questions = await generate_exam_questions_for_units(
                units=list(state.get("units") or []),
                specs=specs,
            )
        except Exception as exc:
            elapsed_ms = int((perf_counter() - started_at) * 1000)
            await emit_progress(
                state,
                stage="generate_exam_questions",
                detail="考题生成失败，请稍后重试。",
                step="generate_questions",
                elapsed_ms=elapsed_ms,
            )
            return {
                "generated_questions": [],
                "generate_ms": elapsed_ms,
                "error": str(exc),
            }

        elapsed_ms = int((perf_counter() - started_at) * 1000)
        await emit_progress(
            state,
            stage="generate_exam_questions",
            detail=f"已生成 {len(questions)} 道考题。",
            step="generate_questions",
            elapsed_ms=elapsed_ms,
        )
        return {
            "generated_questions": [item.model_dump(mode="json") for item in questions],
            "generate_ms": elapsed_ms,
            "error": "",
        }

    return generate_questions_node


__all__ = ["build_generate_questions_node"]
