"""Generate exam questions and emit compact progress events."""

from __future__ import annotations

from time import perf_counter

from app.shared.infra.workflow import emit_progress
from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.examine.question_build.lib.generator import (
    ExamQuestionBlueprint,
    ExamQuestionGenerationFailure,
    generate_exam_questions_for_units,
)
from app.workflows.examine.question_build.state import QuestionBuildState


def build_generate_questions_node(*, context: WorkflowContext):
    del context

    async def generate_questions_node(state: QuestionBuildState) -> dict:
        if state.get("error"):
            return {}

        started_at = perf_counter()
        failed_questions: list[dict] = []
        await emit_progress(
            state,
            stage="generate_exam_questions",
            detail="Generating exam questions from allocated knowledge units...",
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

            generated_count = 0
            failed_count = 0

            async def handle_question_generated(question) -> None:
                nonlocal generated_count
                generated_count += 1
                await emit_progress(
                    state,
                    stage="generate_exam_questions",
                    detail=f"Generated question {question.item_order}.",
                    step="generate_question",
                    extra={
                        "generated_question": question.model_dump(mode="json"),
                        "generated_question_count": generated_count,
                        "question_count": len(specs),
                    },
                )

            async def handle_question_failed(failure: ExamQuestionGenerationFailure) -> None:
                nonlocal failed_count
                failed_count += 1
                failed_payload = failure.model_dump(mode="json")
                failed_questions.append(failed_payload)
                await emit_progress(
                    state,
                    stage="generate_exam_questions",
                    detail=f"Question {failure.item_order} generation failed and was skipped.",
                    step="generate_question_failed",
                    extra={
                        "failed_question": failed_payload,
                        "failed_question_count": failed_count,
                        "question_count": len(specs),
                    },
                )

            questions = await generate_exam_questions_for_units(
                units=list(state.get("units") or []),
                specs=specs,
                subject_profile={
                    "subject_name": str(state.get("subject_name") or ""),
                    "subject_description": str(state.get("subject_description") or ""),
                    "user_intent": str(state.get("subject_user_intent") or ""),
                },
                system_constraints=str(state.get("system_constraints") or ""),
                on_question_generated=handle_question_generated,
                on_question_failed=handle_question_failed,
                allow_partial=True,
            )
        except Exception as exc:
            elapsed_ms = int((perf_counter() - started_at) * 1000)
            await emit_progress(
                state,
                stage="generate_exam_questions",
                detail="Exam question generation failed.",
                step="generate_questions",
                elapsed_ms=elapsed_ms,
            )
            return {
                "generated_questions": [],
                "failed_questions": failed_questions,
                "failed_question_count": len(failed_questions),
                "generate_ms": elapsed_ms,
                "error": str(exc),
            }

        elapsed_ms = int((perf_counter() - started_at) * 1000)
        await emit_progress(
            state,
            stage="generate_exam_questions",
            detail=f"Generated {len(questions)} questions and skipped {len(failed_questions)} failed questions.",
            step="generate_questions",
            elapsed_ms=elapsed_ms,
        )
        return {
            "generated_questions": [item.model_dump(mode="json") for item in questions],
            "generate_ms": elapsed_ms,
            "failed_questions": failed_questions,
            "failed_question_count": len(failed_questions),
            "error": "",
        }

    return generate_questions_node


__all__ = ["build_generate_questions_node"]
