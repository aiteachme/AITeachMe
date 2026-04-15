from __future__ import annotations

import asyncio

from app.workflows.support.teaching_tools import list_teaching_functions, run_teaching_function


def test_list_teaching_functions_returns_teaching_owned_catalog() -> None:
    items = list_teaching_functions()
    names = {item["name"] for item in items}
    categories = {item["name"]: item["category"] for item in items}

    assert "solve_step_by_step" in names
    assert "generate_similar_problems" in names
    assert "explain_formula" in names
    assert "compare_concepts" in names
    assert categories["solve_step_by_step"] == "method"
    assert categories["generate_similar_problems"] == "practice"
    assert categories["explain_formula"] == "explain"


def test_run_teaching_function_executes_registered_teaching_tool() -> None:
    result = asyncio.run(run_teaching_function("compare_concepts", concept_a="??", concept_b="??"))

    assert "??" in result
    assert "??" in result
    assert "维度" in result
    assert "核心定义" in result
