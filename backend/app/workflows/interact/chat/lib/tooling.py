"""Tool configuration for the interact chat lane.

Stream nodes use this module to decide which tools are exposed to one turn and
how the agent loop should run. It does not execute tools directly and does not
own the global tool registry.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from app.agent_tools.context import AgentToolContext
from app.agent_tools.policy import AgentToolPolicyRequest, is_global_assistant_source, resolve_agent_tool_names
from app.shared.infra.agent_loop import AgentLoopConfig
from app.utils.course import is_global_course
from app.workflows.interact.chat.lib.execution import InteractExecutionMode
from app.workflows.interact.chat.lib.intent import ChatScene, parse_chat_scene
from app.workflows.interact.chat.lib.model_policy import (
    INTERACT_MODEL_SELECTOR,
    InteractModelStep,
    interact_llm_kwargs,
)
from app.workflows.interact.chat.lib.types import RetrievedContext

DEFAULT_INTERACT_TOOLS = ("search_kb",)
ASK_USER_OPTIONS_TOOL = "ask_user_options"
_FORCE_ASK_USER_MARKERS = (
    "ask_user_options",
    "\u76f4\u63a5\u95ee\u6211",
    "\u7528\u9009\u9879\u95ee\u6211",
    "\u4f7f\u7528\u9009\u9879\u95ee\u6211",
    "\u7ed9\u6211\u51e0\u4e2a\u9009\u9879",
    "\u7ed9\u51e0\u4e2a\u9009\u9879",
    "\u95ee\u6211\u95ee\u9898",
)
_NUMBERED_OPTION_RE = re.compile(r"^\s*(?:[-*]\s*)?(?:\d{1,2}|[A-Fa-f])[\.\)\u3001\uff09]\s*(.+?)\s*$")


@dataclass(frozen=True)
class InteractToolPlan:
    """Resolved tool plan for one chat turn."""

    tool_names: list[str]
    model_selector: str = INTERACT_MODEL_SELECTOR
    max_iterations: int = 3
    max_tool_calls_per_turn: int = 2
    tool_timeout_s: int = 20
    forced_tool_name: str | None = None

    @property
    def uses_tools(self) -> bool:
        return bool(self.tool_names)


def resolve_interact_tool_plan(
    *,
    execution_mode: InteractExecutionMode,
    course_id: str,
    retrieval_results: list[RetrievedContext],
    scene: str | None = None,
    source: str | None = None,
    question: str | None = None,
    allow_write_tools: bool = False,
    approved_tool_names: set[str] | None = None,
) -> InteractToolPlan:
    """Resolve the bounded tool plan for one turn.

    Today only ``search_kb`` is exposed, but the return shape is intentionally
    list-based so future tools can be added by policy instead of hardcoding
    them in the stream node.
    """

    policy_request = AgentToolPolicyRequest(
        scene=scene,
        source=source,
        course_id=course_id,
        allow_write_tools=allow_write_tools,
        approved_tool_names=frozenset(approved_tool_names or set()),
    )
    tool_names = resolve_agent_tool_names(policy_request)
    forced_tool_name = resolve_forced_interact_tool_name(
        question=question,
        tool_names=tool_names,
    )
    if forced_tool_name:
        return InteractToolPlan(tool_names=[forced_tool_name], forced_tool_name=forced_tool_name)
    parsed_scene = parse_chat_scene(scene)
    if execution_mode != InteractExecutionMode.PLAN_EXECUTE and not (
        parsed_scene == ChatScene.WEB_RESEARCH
        or (is_global_course(course_id) and (parsed_scene == ChatScene.GLOBAL_ASSISTANT or is_global_assistant_source(source)))
    ):
        return InteractToolPlan(tool_names=[])
    _ = retrieval_results
    return InteractToolPlan(tool_names=tool_names, forced_tool_name=forced_tool_name)


def resolve_forced_interact_tool_name(
    *,
    question: str | None,
    tool_names: list[str],
) -> str | None:
    if ASK_USER_OPTIONS_TOOL not in tool_names:
        return None
    if is_explicit_ask_user_options_request(question):
        return ASK_USER_OPTIONS_TOOL
    return None


def is_explicit_ask_user_options_request(question: str | None) -> bool:
    """Return whether the user explicitly asked the agent to use the ask-user tool."""

    normalized = " ".join(str(question or "").casefold().split())
    if not normalized:
        return False
    if any(marker.casefold() in normalized for marker in _FORCE_ASK_USER_MARKERS):
        return True
    return "\u9009\u9879" in normalized and "\u95ee" in normalized and "\u6211" in normalized


def synthesize_ask_user_options_action(
    *,
    question: str | None,
    assistant_response: str | None,
    existing_client_actions: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Recover a selectable-options action when a model wrote the choices as text."""

    if existing_client_actions:
        return existing_client_actions
    if not is_explicit_ask_user_options_request(question):
        return []

    prompt, options = _extract_numbered_option_prompt(assistant_response or "")
    if len(options) < 2:
        return []

    return [
        {
            "type": ASK_USER_OPTIONS_TOOL,
            "payload": {
                "question": _clip_action_text(prompt or "\u8bf7\u9009\u62e9\u4e00\u4e2a\u9009\u9879", 240),
                "options": [
                    {
                        "id": f"option_{index}",
                        "label": _clip_action_text(option, 80),
                        "value": _clip_action_text(option, 160),
                        "description": "",
                    }
                    for index, option in enumerate(options[:6], start=1)
                ],
                "allow_custom_response": True,
            },
        }
    ]


def _extract_numbered_option_prompt(content: str) -> tuple[str, list[str]]:
    prompt_lines: list[str] = []
    options: list[str] = []
    seen_option = False

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = _NUMBERED_OPTION_RE.match(line)
        if match:
            seen_option = True
            option = _clean_option_label(match.group(1))
            if option:
                options.append(option)
            continue
        if not seen_option:
            prompt_lines.append(line)

    return " ".join(prompt_lines).strip(), options


def _clean_option_label(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip(" \t*-_")


def _clip_action_text(value: str, max_chars: int) -> str:
    text = str(value or "").strip()
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 1)].rstrip() + "..."


def build_agent_loop_config(
    *,
    tool_plan: InteractToolPlan,
    course_id: str,
    user_id: str | None = None,
    session_id: str | None = None,
    source: str | None = None,
    attached_file_ids: list[str] | None = None,
    approved_tool_names: set[str] | None = None,
    model_selector: str | None = None,
    tool_event_handler: Callable[[dict[str, Any]], Awaitable[None] | None] | None = None,
    client_action_handler: Callable[[list[dict[str, Any]], dict[str, Any]], Awaitable[None] | None] | None = None,
    extra_metadata: dict[str, object] | None = None,
) -> AgentLoopConfig:
    """Build the shared AgentLoop configuration for Interact."""

    return AgentLoopConfig(
        max_iterations=tool_plan.max_iterations,
        max_tool_calls_per_turn=tool_plan.max_tool_calls_per_turn,
        tool_timeout_s=tool_plan.tool_timeout_s,
        model=model_selector or tool_plan.model_selector,
        llm_kwargs=interact_llm_kwargs(InteractModelStep.RESPONSE_STREAM),
        tool_context=AgentToolContext(
            user_id=user_id,
            course_id=course_id,
            session_id=session_id,
            source=source,
            attached_file_ids=tuple(attached_file_ids or ()),
            approved_tool_names=frozenset(approved_tool_names or set()),
        ),
        approved_tool_names=set(approved_tool_names or set()),
        tool_choice=tool_plan.forced_tool_name,
        tool_event_handler=tool_event_handler,
        client_action_handler=client_action_handler,
        extra_metadata=dict(extra_metadata or {}),
    )


__all__ = [
    "DEFAULT_INTERACT_TOOLS",
    "ASK_USER_OPTIONS_TOOL",
    "INTERACT_MODEL_SELECTOR",
    "InteractToolPlan",
    "build_agent_loop_config",
    "is_explicit_ask_user_options_request",
    "resolve_forced_interact_tool_name",
    "resolve_interact_tool_plan",
    "synthesize_ask_user_options_action",
]
