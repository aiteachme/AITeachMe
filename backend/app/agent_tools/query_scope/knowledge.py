"""Knowledge-query agent tools."""

from __future__ import annotations

from app.shared.infra.tools.decorator import tool


@tool(
    "search_kb",
    "Search the active course knowledge base for passages relevant to the question.",
    usage=(
        "Use when the answer should be grounded in the current course materials, uploaded documents, "
        "or generated knowledge base, especially when the prompt lacks enough evidence."
    ),
    tags=["query", "knowledge", "course"],
    source="agent_tools.query_scope",
    risk_level="low",
    scopes=["course", "knowledge:read"],
    requires_course=True,
    hidden_args=["course_id"],
)
async def search_kb_tool(
    query: str,
    top_k: int = 5,
    course_id: str | None = None,
) -> str:
    from app.shared.infra.search import get_knowledge_search_notice, search_knowledge

    resolved_course_id = (course_id or "").strip()
    if not resolved_course_id:
        return "A course context is required before searching the knowledge base."

    search_notice = await get_knowledge_search_notice(resolved_course_id)
    if search_notice is not None:
        return search_notice

    chunks = await search_knowledge(query, resolved_course_id, top_k=top_k)
    if not chunks:
        return "No relevant content was found in the knowledge base."
    return "\n\n---\n\n".join(f"**{chunk.title or 'Passage'}**\n{chunk.content}" for chunk in chunks)
