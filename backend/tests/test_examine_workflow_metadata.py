from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.shared.infra.workflow.result import ok_result
from app.workflows.examine.exam_grade import graph as exam_grade_graph
from app.workflows.examine.question_build import graph as question_build_graph


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_question_build_trace_includes_positive_exam_paper_id(monkeypatch) -> None:
    contexts = []

    async def fake_run_state_graph(**kwargs):
        contexts.append(kwargs["context"])
        return ok_result({})

    monkeypatch.setattr(question_build_graph, "run_state_graph", fake_run_state_graph)

    await question_build_graph.run_question_build_workflow(
        course_id="course-question-build",
        exam_paper_id=42,
        question_count=1,
    )
    await question_build_graph.run_question_build_workflow(
        course_id="course-question-build",
        exam_paper_id=0,
        question_count=1,
    )

    assert contexts[0].metadata["exam_paper_id"] == 42
    assert "exam_paper_id" not in contexts[1].metadata


@pytest.mark.anyio
async def test_exam_grade_trace_only_includes_one_shared_exam_paper_id(monkeypatch) -> None:
    contexts = []

    async def fake_run_state_graph(**kwargs):
        contexts.append(kwargs["context"])
        return ok_result({"grade_decisions": [], "error": ""})

    monkeypatch.setattr(exam_grade_graph, "run_state_graph", fake_run_state_graph)

    await exam_grade_graph.run_exam_grade_workflow(
        course_id="course-grade",
        items=[SimpleNamespace(exam_paper_id=42), SimpleNamespace(exam_paper_id=42)],
    )
    await exam_grade_graph.run_exam_grade_workflow(
        course_id="course-grade",
        items=[SimpleNamespace(exam_paper_id=42), SimpleNamespace(exam_paper_id=43)],
    )
    await exam_grade_graph.run_exam_grade_workflow(
        course_id="course-grade",
        items=[SimpleNamespace(exam_paper_id=0)],
    )

    assert contexts[0].metadata["exam_paper_id"] == 42
    assert "exam_paper_id" not in contexts[1].metadata
    assert "exam_paper_id" not in contexts[2].metadata
