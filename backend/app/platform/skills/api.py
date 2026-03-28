"""Skill 对外 API — 外部模块的唯一入口。"""

from __future__ import annotations

import structlog

from app.platform.skills.base import get_skill_registry

logger = structlog.get_logger()


async def run_skill(name: str, **kwargs) -> str:
    """执行指定技能。

    这是外部调用 Skill 的**唯一入口**。

    Args:
        name: Skill 名称。
        **kwargs: Skill 参数。

    Returns:
        Skill 执行结果（字符串）。

    Raises:
        ValueError: Skill 未注册。

    Example::

        from app.platform.skills.api import run_skill
        result = await run_skill("find_resources", topic="微积分")
    """

    registry = get_skill_registry()
    sd = registry.get(name)
    if sd is None:
        raise ValueError(f"Skill `{name}` 未注册。可用：{[s.name for s in registry.list_all()]}")

    if sd.is_async:
        result = await sd.handler(**kwargs)
    else:
        import asyncio
        result = await asyncio.to_thread(sd.handler, **kwargs)

    return str(result)


def list_skills() -> list[dict]:
    """列出所有已注册的 Skill。

    Returns:
        包含 name, description, tags 的字典列表。

    Example::

        from app.platform.skills.api import list_skills
        for s in list_skills():
            print(f"{s['name']}: {s['description']}")
    """

    registry = get_skill_registry()
    return [
        {
            "name": sd.name,
            "description": sd.description,
            "tags": sd.tags,
        }
        for sd in registry.list_all()
    ]
