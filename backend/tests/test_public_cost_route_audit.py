from __future__ import annotations

from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_public_suggest_name_cost_route_is_removed() -> None:
    courses_api = (BACKEND_ROOT / "app/api/courses.py").read_text(encoding="utf-8")
    course_schema = (BACKEND_ROOT / "app/schemas/course.py").read_text(encoding="utf-8")

    assert "suggest-name" not in courses_api
    assert "CourseNameSuggestion" not in courses_api
    assert "CourseNameSuggestion" not in course_schema
    assert "acompletion(" not in courses_api


def test_internal_planner_course_identity_workflow_remains() -> None:
    identity_node = (
        BACKEND_ROOT / "app/workflows/digest/planner/nodes/generate_course_identity.py"
    ).read_text(encoding="utf-8")

    assert "generate_course_identity" in identity_node
    assert "acompletion_with_fallback" in identity_node
