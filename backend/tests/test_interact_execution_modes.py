from __future__ import annotations

import asyncio

from app.shared.infra.strategies import StrategyMode
from app.workflows.common.context import WorkflowContext
from app.workflows.interact.nodes.prompt import build_prompt_node
from app.workflows.interact.nodes.stream import build_stream_answer_node
from app.workflows.interact.support.execution import (
    InteractExecutionMode,
    select_execution_mode,
)


def test_select_execution_mode_prefers_plan_execute_for_planning_question() -> None:
    mode = select_execution_mode(
        question="帮我做一个偏导数复习计划，告诉我先学什么后学什么",
        selected_context=None,
        strategy_mode=StrategyMode.PLANNING,
        retrieval_results=[],
    )

    assert mode == InteractExecutionMode.PLAN_EXECUTE


def test_prompt_node_injects_plan_execute_instruction(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.workflows.interact.nodes.prompt.build_chat_messages",
        lambda **kwargs: [
            {"role": "system", "content": "base system"},
            {"role": "user", "content": kwargs["question"]},
        ],
    )
    node = build_prompt_node(
        context=WorkflowContext(
            workflow_name="interact.chat.test",
            subject="demo",
        )
    )

    result = node(
        {
            "subject": "demo",
            "question": "帮我一步步理解偏导数",
            "strategy_mode": StrategyMode.GUIDED,
            "execution_mode": InteractExecutionMode.PLAN_EXECUTE,
            "retrieval_results": [],
            "recent_messages": [],
            "weak_points": [],
            "recent_mistakes": [],
        }
    )

    assert result["messages"][0]["content"] == "base system"
    assert "plan-execute" in str(result["messages"][1]["content"])


def test_stream_answer_node_uses_agent_loop_stream_for_plan_execute_mode(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_agent_loop_stream(messages, *, tools, config):
        captured["messages"] = messages
        captured["tools"] = tools
        captured["config"] = config
        for token in ("A", "B"):
            yield token

    def fail_if_called(*args, **kwargs):
        raise AssertionError("acompletion_stream should not be used in plan_execute mode")

    monkeypatch.setattr(
        "app.workflows.interact.nodes.stream.run_agent_loop_stream",
        fake_agent_loop_stream,
    )
    monkeypatch.setattr(
        "app.workflows.interact.nodes.stream.acompletion_stream",
        fail_if_called,
    )

    node = build_stream_answer_node(
        context=WorkflowContext(
            workflow_name="interact.chat.test",
            subject="demo",
        )
    )

    result = asyncio.run(
        node(
            {
                "subject": "demo",
                "session_id": "sess-1",
                "messages": [{"role": "user", "content": "帮我一步步理解偏导数"}],
                "execution_mode": InteractExecutionMode.PLAN_EXECUTE,
                "error": None,
            }
        )
    )

    assert result["assistant_response"] == "AB"
    assert result["stream_interrupted"] is False
    assert captured["tools"] == ["search_kb"]
    assert captured["config"].tool_argument_overrides == {"search_kb": {"subject": "demo"}}
