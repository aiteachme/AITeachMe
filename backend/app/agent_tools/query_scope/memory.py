"""Memory-query agent tools."""

from __future__ import annotations

from app.shared.infra.tools.decorator import tool


@tool(
    "recall_info",
    "Recall user-specific background or learning information relevant to a query.",
    tags=["query", "memory"],
    source="agent_tools.query_scope",
    risk_level="low",
    scopes=["memory:read"],
    hidden_args=["user_id"],
)
async def recall_info_tool(
    query: str,
    top_k: int = 5,
    user_id: str | None = None,
) -> str:
    from app.shared.infra.memory import recall

    entries = await recall(query, user_id=user_id or "default", top_k=top_k)
    if not entries:
        return "No relevant memories found."
    return "\n".join(f"- [{entry.tag}] {entry.content}" for entry in entries)
