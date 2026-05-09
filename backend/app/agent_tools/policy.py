"""Tool exposure policy for agent-capable workflow lanes."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.utils.course import is_global_course

COURSE_LEARNING_TOOLS = ("search_kb",)
GLOBAL_QUERY_TOOLS = ("web_search", "recall_info")
GLOBAL_WRITE_TOOLS = ("remember_info", "create_course_from_home_intake")
BUILD_TOOLS: tuple[str, ...] = ()
EDITING_TOOLS: tuple[str, ...] = ()

_GLOBAL_ASSISTANT_SOURCES = frozenset({"home", "home_intake", "global_assistant"})
_BUILD_SOURCES = frozenset({"build_assistant"})
_EDITING_SOURCES = frozenset({"course_editor", "content_editor"})


@dataclass(frozen=True)
class AgentToolPolicyRequest:
    """Inputs used to decide which tools one model turn can see."""

    source: str | None = None
    course_id: str | None = None
    allow_write_tools: bool = False
    approved_tool_names: frozenset[str] = field(default_factory=frozenset)


def resolve_agent_tool_names(
    request: AgentToolPolicyRequest | None = None,
    **kwargs: object,
) -> list[str]:
    """Return tool names visible to one agent turn."""

    resolved = request or AgentToolPolicyRequest(**kwargs)
    source = (resolved.source or "").strip()
    course_id = (resolved.course_id or "").strip()
    has_course = bool(course_id and not is_global_course(course_id))

    tool_names: list[str] = []
    if has_course:
        tool_names.extend(COURSE_LEARNING_TOOLS)
        if source in _BUILD_SOURCES:
            tool_names.extend(BUILD_TOOLS)
        if source in _EDITING_SOURCES and resolved.allow_write_tools:
            tool_names.extend(EDITING_TOOLS)
    elif is_global_assistant_source(source):
        tool_names.extend(GLOBAL_QUERY_TOOLS)

    if resolved.allow_write_tools:
        tool_names.extend(
            name
            for name in GLOBAL_WRITE_TOOLS
            if name in resolved.approved_tool_names
        )

    return _dedupe(tool_names)


def is_global_assistant_source(source: str | None) -> bool:
    """Return whether a source tag should behave as the global assistant lane."""

    normalized = (source or "").strip()
    return not normalized or normalized in _GLOBAL_ASSISTANT_SOURCES


def _dedupe(names: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for name in names:
        if name in seen:
            continue
        seen.add(name)
        result.append(name)
    return result
