from __future__ import annotations

import asyncio
import json
from pathlib import Path

from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.digest.curriculum.graph import build_curriculum_derive_graph
from app.workflows.digest.docgen.graph import get_langgraph_dev_docgen_graph
from app.workflows.digest.exports import WORKFLOW_EXPORTS as DIGEST_WORKFLOW_EXPORTS
from app.workflows.digest.kg.graph import build_kg_digest_graph
from app.workflows.digest.planner.graph import get_langgraph_dev_planner_graph
from app.workflows.digest.unified.graph import get_langgraph_dev_unified_graph
from app.workflows.examine.exam_grade_workflow import build_exam_grade_graph
from app.workflows.examine.question_build_workflow import build_question_build_graph
from app.workflows.ingest.graph import (
    build_deep_enhance_graph,
    get_langgraph_dev_fast_parse_graph,
)
from app.workflows.interact.graph import get_langgraph_dev_interact_graph
from app.workflows.interact.nodes import stream as stream_module
from app.workflows.profile.graph import build_profile_pipeline_graph


def _node_ids(graph) -> set[str]:
    compiled_graph = graph if hasattr(graph, "get_graph") else graph.compile()
    return {node.id for node in compiled_graph.get_graph().nodes.values()}


def test_langgraph_dev_entrypoints_compile_expected_graphs() -> None:
    assert {"load_raw_file", "parse_file", "finalize_success"}.issubset(
        _node_ids(get_langgraph_dev_fast_parse_graph())
    )
    assert {"load_enhance_context", "deep_enhance_file", "finalize_deep_enhance"}.issubset(
        _node_ids(build_deep_enhance_graph())
    )
    assert {"acquire_lock", "prepare", "finalize_graph"}.issubset(_node_ids(build_kg_digest_graph()))
    assert {"derive_units", "derive_theme_tree", "finalize_curriculum"}.issubset(
        _node_ids(build_curriculum_derive_graph())
    )
    assert {"load_context", "draft_plan"}.issubset(
        _node_ids(get_langgraph_dev_planner_graph())
    )
    assert {"load_context", "research_chapters", "publish_document"}.issubset(
        _node_ids(get_langgraph_dev_docgen_graph())
    )
    assert {"prepare_shared", "run_parallel_lanes", "publish_outputs"}.issubset(
        _node_ids(get_langgraph_dev_unified_graph())
    )
    assert {"load_history_state", "stream_answer", "persist_turn"}.issubset(
        _node_ids(get_langgraph_dev_interact_graph())
    )
    assert {"load_units", "generate_templates", "finalize_build"}.issubset(
        _node_ids(build_question_build_graph())
    )
    assert {"grade_answers", "update_mastery", "finalize_grade"}.issubset(
        _node_ids(build_exam_grade_graph())
    )
    assert {"resolve_profile_context", "update_mastery", "refresh_user_profile"}.issubset(
        _node_ids(build_profile_pipeline_graph())
    )


def test_interact_stream_node_supports_debug_mode(monkeypatch) -> None:
    class FakeStream:
        def __init__(self, tokens: list[str]):
            self._tokens = iter(tokens)
            self.closed = False

        def __aiter__(self):
            return self

        async def __anext__(self) -> str:
            try:
                return next(self._tokens)
            except StopIteration as exc:
                raise StopAsyncIteration from exc

        async def aclose(self) -> None:
            self.closed = True

    def fake_completion_stream(_messages, task_type):
        return FakeStream(["A", "B"])

    monkeypatch.setattr(stream_module, "acompletion_stream", fake_completion_stream)
    context = WorkflowContext(
        workflow_name="interact.chat.test",
        subject="demo",
    )
    node = stream_module.build_stream_answer_node(context=context)

    result = asyncio.run(
        node(
            {
                "messages": [{"role": "user", "content": "AB"}],
                "error": None,
            }
        )
    )

    assert result["assistant_response"] == "AB"
    assert result["stream_interrupted"] is False


def test_langgraph_json_registers_digest_planner() -> None:
    payload = json.loads(Path("backend/langgraph.json").read_text(encoding="utf-8"))
    planner_graph = payload["graphs"].get("digest_planner")

    assert planner_graph is not None
    assert planner_graph["path"] == "./app/workflows/digest/planner/graph.py:get_langgraph_dev_planner_graph"


def test_digest_workflow_exports_include_planner_before_unified() -> None:
    keys = [export.key for export in DIGEST_WORKFLOW_EXPORTS]

    assert "digest_planner" in keys
    assert keys.index("digest_planner") < keys.index("digest_unified")
