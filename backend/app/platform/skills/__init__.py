"""Skill 框架 — 可加载的教学技能模块。"""
from app.platform.skills.api import list_skills, run_skill
from app.platform.skills.base import skill

__all__ = [
    "list_skills",
    "run_skill",
    "skill",
]
