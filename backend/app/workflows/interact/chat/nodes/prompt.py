"""Prompt-building node builders for the interact workflow."""

from __future__ import annotations

from app.agent_tools.catalog import build_agent_tool_catalog
from app.agent_tools.policy import AgentToolPolicyRequest
from app.schemas.llm import ChatMessage, SYSTEM
from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.interact.chat.lib.tooling import resolve_interact_tool_plan
from app.workflows.interact.chat.prompts import build_chat_messages, get_execution_instruction
from app.workflows.interact.chat.state import InteractWorkflowState


def build_prompt_node(*, context: WorkflowContext):
    """Build the node that assembles the final prompt messages."""

    workflow_logger = context.get_logger()

    def build_prompt(state: InteractWorkflowState) -> InteractWorkflowState:
        course_id = state["course_id"] or "global"
        tool_plan = resolve_interact_tool_plan(
            execution_mode=state["execution_mode"],
            course_id=course_id,
            retrieval_results=state.get("retrieval_results", []),
            scene=state.get("scene"),
            source=state.get("source"),
        )
        agent_tool_catalog = build_agent_tool_catalog(
            AgentToolPolicyRequest(
                scene=state.get("scene"),
                source=state.get("source"),
                course_id=course_id,
                allow_write_tools=False,
            ),
            active_tool_names=tool_plan.tool_names,
        )
        messages = build_chat_messages(
            course_id=course_id,
            strategy_mode=state["strategy_mode"],
            retrieval_results=state.get("retrieval_results", []),
            recent_messages=state.get("recent_messages", []),
            course_context=state.get("course_context"),
            weak_points=state.get("weak_points", []),
            recent_mistakes=state.get("recent_mistakes", []),
            question=state["question"],
            scene=state.get("scene"),
            source=state.get("source"),
            selected_context=state.get("selected_context"),
            selection_context=state.get("selection_context"),
            source_chunk_id=state.get("source_chunk_id"),
            agent_tool_catalog=agent_tool_catalog,
        )
        execution_instruction = get_execution_instruction(state["execution_mode"])
        if execution_instruction:
            mode_message: ChatMessage = {
                "role": SYSTEM,
                "content": execution_instruction,
            }
            if messages and messages[0].get("role") == SYSTEM:
                messages = [messages[0], mode_message, *messages[1:]]
            else:
                messages = [mode_message, *messages]
        workflow_logger.info(
            "interact_prompt_built",
            message_count=len(messages),
            citation_count=len(state.get("contexts") or []),
            execution_mode=state["execution_mode"].value,
        )
        return {
            **state,
            "messages": messages,
        }

    return build_prompt
