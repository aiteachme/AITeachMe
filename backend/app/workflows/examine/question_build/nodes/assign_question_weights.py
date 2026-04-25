"""Assign weighted knowledge-unit coverage to generated questions."""

from __future__ import annotations

from time import perf_counter

from app.shared.infra.workflow import emit_progress
from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.examine.question_build.lib.generator import (
    ExamQuestionBlueprint,
    ExamQuestionDraft,
    assign_question_knowledge_weights,
)
from app.workflows.examine.question_build.state import QuestionBuildState


def build_assign_question_weights_node(*, context: WorkflowContext):
    del context

    async def assign_question_weights_node(state: QuestionBuildState) -> dict:
        if state.get("error"):
            return {}

        started_at = perf_counter()
        await emit_progress(
            state,
            stage="weight_exam_questions",
            detail="正在根据每道题内容为知识单元分配覆盖权重...",
            step="assign_question_weights",
        )
        try:
            blueprints = [
                ExamQuestionBlueprint.model_validate(item)
                for item in list(state.get("question_blueprints") or [])
            ]
            questions = [
                ExamQuestionDraft.model_validate(item)
                for item in list(state.get("generated_questions") or [])
            ]
            weighted = await assign_question_knowledge_weights(
                subject=str(state.get("subject") or ""),
                subject_name=str(state.get("subject_name") or ""),
                subject_description=str(state.get("subject_description") or ""),
                subject_user_intent=str(state.get("subject_user_intent") or ""),
                units=list(state.get("units") or []),
                blueprints=blueprints,
                questions=questions,
            )
        except Exception as exc:
            elapsed_ms = int((perf_counter() - started_at) * 1000)
            await emit_progress(
                state,
                stage="weight_exam_questions",
                detail="知识单元权重分配失败，请稍后重试。",
                step="assign_question_weights",
                elapsed_ms=elapsed_ms,
            )
            return {"weight_ms": elapsed_ms, "error": str(exc)}

        elapsed_ms = int((perf_counter() - started_at) * 1000)
        await emit_progress(
            state,
            stage="weight_exam_questions",
            detail=f"已完成 {len(weighted)} 道题的知识单元权重分配。",
            step="assign_question_weights",
            elapsed_ms=elapsed_ms,
        )
        return {
            "generated_questions": [item.model_dump(mode="json") for item in weighted],
            "weight_ms": elapsed_ms,
            "error": "",
        }

    return assign_question_weights_node


__all__ = ["build_assign_question_weights_node"]
