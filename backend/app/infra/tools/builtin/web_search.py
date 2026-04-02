"""内置工具：Web 搜索。

注册后，Agent Loop 中的 LLM 可以自动调用此工具搜索互联网信息。
"""

from app.infra.tools.decorator import tool


@tool("web_search", "搜索互联网获取最新相关信息，适用于知识库中没有覆盖的内容")
async def web_search_tool(query: str, top_k: int = 5) -> str:
    """搜索互联网。

    Args:
        query: 搜索查询。
        top_k: 返回结果数量。
    """

    from app.infra.search import web_search

    results = await web_search(query, top_k=top_k)
    if not results:
        return "未找到相关搜索结果。"
    return "\n\n".join(r.to_text() for r in results)
