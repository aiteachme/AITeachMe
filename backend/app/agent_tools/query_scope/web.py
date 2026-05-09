"""Web-query agent tools."""

from __future__ import annotations

from app.shared.infra.tools.decorator import tool


@tool(
    "web_search",
    "Search the web for recent or external information not covered by course materials.",
    usage=(
        "Use for current events, changing facts, external references, or questions that cannot be answered "
        "reliably from local course material or conversation context alone."
    ),
    tags=["query", "web"],
    source="agent_tools.query_scope",
    risk_level="low",
    scopes=["web:search"],
)
async def web_search_tool(query: str, top_k: int = 5) -> str:
    from app.shared.infra.search import web_search

    results = await web_search(query, top_k=top_k)
    if not results:
        return "No relevant web search results found."
    return "\n\n".join(result.to_text() for result in results)
