"""Global user-memory write tools for agent calls."""

from __future__ import annotations

from app.shared.infra.tools.decorator import tool


@tool(
    "remember_info",
    "Remember one user-specific learning preference, background fact, strength, weakness, or note.",
    tags=["global", "memory", "write"],
    source="agent_tools.global_scope",
    risk_level="medium",
    scopes=["global", "memory:write"],
    requires_approval=True,
    hidden_args=["user_id"],
)
async def remember_info_tool(
    content: str,
    tag: str = "general",
    importance: float = 0.5,
    user_id: str | None = None,
) -> str:
    from app.shared.infra.memory import remember

    key = await remember(
        content,
        user_id=user_id or "default",
        tag=tag,
        importance=importance,
    )
    return f"Remembered: {content} (tag={tag}, key={key})"
