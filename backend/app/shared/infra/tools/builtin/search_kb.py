"""内置工具：知识库检索。

注册后，Agent Loop 中的 LLM 可以自动调用此工具检索用户上传的知识库内容。
"""

from app.shared.infra.tools.decorator import tool


@tool("search_kb", "在用户上传的知识库中检索与问题相关的知识片段")
async def search_kb_tool(query: str, subject_id: str, top_k: int = 5) -> str:
    """搜索知识库。"""

    from app.shared.infra.search import get_knowledge_search_notice, search_knowledge

    search_notice = await get_knowledge_search_notice(subject_id)
    if search_notice is not None:
        return search_notice

    chunks = await search_knowledge(query, subject_id, top_k=top_k)
    if not chunks:
        return "知识库中未找到相关内容。"
    return "\n\n---\n\n".join(f"**{c.title or '片段'}**\n{c.content}" for c in chunks)
