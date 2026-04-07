from __future__ import annotations

import asyncio

from app.langgraph_dev import (
    digest_curriculum_graph,
    digest_docgen_graph,
    digest_kg_graph,
    digest_unified_graph,
    examine_exam_grade_graph,
    examine_question_build_graph,
    ingest_deep_enhance_graph,
    ingest_fast_parse_graph,
    interact_chat_graph,
    profile_pipeline_graph,
)
from app.workflows.common.context import WorkflowContext
from app.workflows.interact.nodes import stream as stream_module


def _node_ids(compiled_graph) -> set[str]:
    return {node.id for node in compiled_graph.get_graph().nodes.values()}


def test_langgraph_dev_entrypoints_compile_expected_graphs() -> None:
    assert {"load_raw_file", "parse_file", "finalize_success"}.issubset(
        _node_ids(ingest_fast_parse_graph)
    )
    assert {"load_enhance_context", "deep_enhance_file", "finalize_deep_enhance"}.issubset(
        _node_ids(ingest_deep_enhance_graph)
    )
    assert {"acquire_lock", "prepare", "finalize_graph"}.issubset(_node_ids(digest_kg_graph))
    assert {"derive_units", "derive_theme_tree", "finalize_curriculum"}.issubset(
        _node_ids(digest_curriculum_graph)
    )
    assert {"load_files", "outline_reduce", "finalize_assemble"}.issubset(
        _node_ids(digest_docgen_graph)
    )
    assert {"prepare_shared", "run_parallel_lanes", "publish_outputs"}.issubset(
        _node_ids(digest_unified_graph)
    )
    assert {"load_history_state", "stream_answer", "persist_turn"}.issubset(
        _node_ids(interact_chat_graph)
    )
    assert {"load_units", "generate_templates", "finalize_build"}.issubset(
        _node_ids(examine_question_build_graph)
    )
    assert {"grade_answers", "update_mastery", "finalize_grade"}.issubset(
        _node_ids(examine_exam_grade_graph)
    )
    assert {"resolve_profile_context", "update_mastery", "refresh_user_profile"}.issubset(
        _node_ids(profile_pipeline_graph)
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
