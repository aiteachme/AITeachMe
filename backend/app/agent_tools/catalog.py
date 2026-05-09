"""Prompt-facing catalog for registered agent tools."""

from __future__ import annotations

from app.agent_tools.policy import (
    GLOBAL_WRITE_TOOLS,
    AgentToolPolicyRequest,
    is_global_assistant_source,
    resolve_agent_tool_names,
)
from app.shared.infra.tools.api import ensure_project_tool_modules_loaded
from app.shared.infra.tools.definition import ToolDefinition
from app.shared.infra.tools.registry import get_tool_registry
from app.utils.course import is_global_course


def build_agent_tool_catalog(
    request: AgentToolPolicyRequest,
    *,
    include_pending_write_tools: bool = True,
    active_tool_names: list[str] | None = None,
) -> str:
    """Return a compact, prompt-ready catalog for the current agent lane."""

    ensure_project_tool_modules_loaded()
    registry = get_tool_registry()
    policy_names = resolve_agent_tool_names(request)
    callable_names = _dedupe(active_tool_names if active_tool_names is not None else policy_names)
    visible_names = _dedupe([*policy_names, *callable_names])
    pending_names = _pending_write_tool_names(
        request,
        visible_names=visible_names,
        include_pending_write_tools=include_pending_write_tools,
    )

    lines: list[str] = []
    callable_set = set(callable_names)
    for name in visible_names:
        definition = registry.get(name)
        if definition is not None:
            status = "callable_now" if name in callable_set else "available_by_policy"
            lines.extend(_format_tool_entry(definition, status=status))

    for name in pending_names:
        definition = registry.get(name)
        if definition is not None:
            lines.extend(_format_tool_entry(definition, status="requires_user_confirmation"))

    return "\n".join(lines).strip()


def _pending_write_tool_names(
    request: AgentToolPolicyRequest,
    *,
    visible_names: list[str],
    include_pending_write_tools: bool,
) -> list[str]:
    if not include_pending_write_tools:
        return []
    if not is_global_course(request.course_id):
        return []
    scene = (request.scene or "").strip()
    if scene not in {"global_assistant", "home_intake"} and not is_global_assistant_source(request.source):
        return []
    active = set(visible_names)
    return [name for name in GLOBAL_WRITE_TOOLS if name not in active]


def _dedupe(names: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for name in names:
        if name in seen:
            continue
        seen.add(name)
        result.append(name)
    return result


def _format_tool_entry(definition: ToolDefinition, *, status: str) -> list[str]:
    usage = definition.usage.strip() or _fallback_usage(definition)
    return [
        f"- `{definition.name}` [{status}, risk={definition.risk_level}]: {definition.description}",
        f"  Usage: {usage}",
        f"  Arguments: {_format_visible_arguments(definition)}",
    ]


def _format_visible_arguments(definition: ToolDefinition) -> str:
    parameters = definition.to_openai_format().get("function", {}).get("parameters", {})
    properties = parameters.get("properties") if isinstance(parameters, dict) else {}
    if not isinstance(properties, dict) or not properties:
        return "none"
    required = set(parameters.get("required") or []) if isinstance(parameters, dict) else set()
    parts: list[str] = []
    for name in properties:
        requirement = "required" if name in required else "optional"
        parts.append(f"{name} ({requirement})")
    return ", ".join(parts)


def _fallback_usage(definition: ToolDefinition) -> str:
    arguments = _format_visible_arguments(definition)
    if arguments == "none":
        return "Call when this capability directly helps satisfy the user's request."
    return f"Call with {arguments} when this capability directly helps satisfy the user's request."


__all__ = ["build_agent_tool_catalog"]
