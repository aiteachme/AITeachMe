"""内置工具：记忆操作。

注册后，Agent Loop 中的 LLM 可以主动记住和回忆用户信息。
"""

from app.infra.tools.decorator import tool


@tool("remember_info", "记住关于用户的一条信息（学习偏好、强弱项、背景等），用于个性化教学")
async def remember_info_tool(content: str, tag: str = "general", importance: float = 0.5) -> str:
    """记住信息。

    Args:
        content: 要记住的内容。
        tag: 标签（preference/strength/weakness/background/note）。
        importance: 重要度 0~1。
    """
    from app.infra.memory import remember

    key = await remember(content, tag=tag, importance=importance)
    return f"已记住：{content}（标签={tag}，key={key}）"


@tool("recall_info", "回忆关于用户的相关信息，用于了解用户背景和学习状况")
async def recall_info_tool(query: str, top_k: int = 5) -> str:
    """回忆信息。

    Args:
        query: 搜索关键词。
        top_k: 返回数量。
    """
    from app.infra.memory import recall

    entries = await recall(query, top_k=top_k)
    if not entries:
        return "暂无相关记忆。"
    return "\n".join(f"- [{e.tag}] {e.content}" for e in entries)
