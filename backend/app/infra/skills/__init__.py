"""Skill 框架 — 可加载的教学技能模块。

对外使用::

    from app.infra.skills import run_skill, list_skills

    # 执行技能
    result = await run_skill("find_resources", topic="线性代数")

    # 列出可用技能
    for s in list_skills():
        print(f"{s['name']}: {s['description']}")
"""

from app.infra.skills.api import list_skills, run_skill
from app.infra.skills.base import skill

__all__ = [
    "list_skills",
    "run_skill",
    "skill",
]
