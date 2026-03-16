"""Ingest Engine 提示词模块。

集中导出系统提示词与模板映射，其他模块可直接 from prompts import。
"""

from .prompts import PROMPTS, SYSTEM_PROMPT_IMAGE_PARSE

__all__ = [
    "SYSTEM_PROMPT_IMAGE_PARSE",
    "PROMPTS",
]
