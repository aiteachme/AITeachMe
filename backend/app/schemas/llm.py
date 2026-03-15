"""Typed helpers for internal LLM message payloads."""

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
