"""LLM 消息类型定义 — 替代裸 dict，提供类型安全提示。"""

from typing import Literal, TypedDict, Union

# 角色常量，方便调用方引用
SYSTEM: Literal["system"] = "system"
USER: Literal["user"] = "user"
ASSISTANT: Literal["assistant"] = "assistant"

Role = Literal["system", "user", "assistant"]


class ChatMessage(TypedDict, total=False):
    """LLM 消息，本身就是 dict，litellm 直接接受。"""
    role: Role
    content: Union[str, list[dict]]
