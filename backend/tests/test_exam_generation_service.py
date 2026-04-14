from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.exams_service import trigger_exam_generate
from app.workflows.examine.context import build_exam_style_profile


class _DummyExportResult:
    markdown_path = "paper.md"
    tex_path = None

    def model_dump(self) -> dict[str, object]:
        return {
            "markdown_path": self.markdown_path,
            "tex_path": self.tex_path,
            "pdf_path": None,
            "compiler": None,
        }


def test_build_exam_style_profile_injects_default_paper_exam_prompt() -> None:
    with patch(
        "app.workflows.examine.context._load_subject_profile_for_exam",
        return_value=None,
    ), patch(
        "app.workflows.examine.context._load_user_profile_for_exam",
        return_value=None,
    ):
        style = build_exam_style_profile(
            MagicMock(),
            subject="linear-algebra",
            exam_mode="paper_exam",
        )

    assert style.format_hint == "paper_exam"
    assert style.style_prompt is not None
    assert "正式考试试卷" in style.style_prompt
    assert any("built-in formal paper style" in note for note in style.notes)


def test_build_exam_style_profile_keeps_explicit_style_prompt() -> None:
    with patch(
        "app.workflows.examine.context._load_subject_profile_for_exam",
        return_value=None,
    ), patch(
        "app.workflows.examine.context._load_user_profile_for_exam",
        return_value=None,
    ):
        style = build_exam_style_profile(
            MagicMock(),
            subject="linear-algebra",
            exam_mode="paper_exam",
            style_prompt="请严格模仿学校闭卷考试卷面。",
        )

    assert style.style_prompt == "请严格模仿学校闭卷考试卷面。"
    assert not any("built-in formal paper style" in note for note in style.notes)


def test_trigger_exam_generate_skips_question_build_for_sufficient_paper_inventory() -> None:
    session = MagicMock()
    snapshot = SimpleNamespace(id=7)
    style_profile = SimpleNamespace(
        recommended_question_count=None,
        preferred_question_types=["single_choice", "fill_blank", "short_answer"],
        difficulty_focus="medium",
        focus_teaching_unit_ids=[],
        focus_node_ids=[],
    )
    paper = SimpleNamespace(
        id=101,
        subject="linear-algebra",
        user_id="local",
        exam_mode="paper_exam",
        total_items=24,
        selection_context_json="{}",
        updated_at=None,
    )

    with patch(
        "app.services.exams_service.paper_generation.exams_repo.get_published_curriculum_version",
        return_value=snapshot,
    ), patch(
        "app.services.exams_service.paper_generation.build_exam_style_profile",
        return_value=style_profile,
    ), patch(
        "app.services.exams_service.paper_generation._resolve_requested_unit_scope",
        return_value=[11, 12, 13],
    ), patch(
        "app.services.exams_service.paper_generation._resolve_auto_build_unit_ids",
        return_value=[11, 12, 13],
    ), patch(
        "app.services.exams_service.paper_generation._count_effective_template_inventory",
        side_effect=[40, 40],
    ), patch(
        "app.services.exams_service.paper_generation.trigger_question_build",
        new_callable=AsyncMock,
    ) as build_mock, patch(
        "app.services.exams_service.paper_generation.assemble_paper",
        return_value=paper,
    ) as assemble_mock, patch(
        "app.services.exams_service.paper_generation.export_exam_paper_artifacts",
        return_value=_DummyExportResult(),
    ):
        result = asyncio.run(
            trigger_exam_generate(
                session,
                subject="linear-algebra",
                user_id="local",
                exam_mode="paper_exam",
                num_questions=24,
                teaching_unit_ids=[11, 12, 13],
            )
        )

    build_mock.assert_not_awaited()
    assemble_mock.assert_called_once()
    assert result.exam_mode == "paper_exam"
    assert result.exam_paper_id == 101
