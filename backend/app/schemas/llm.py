"""内部 LLM 消息结构。"""

from __future__ import annotations

from typing import Literal, TypedDict

SYSTEM: Literal["system"] = "system"
USER: Literal["user"] = "user"
ASSISTANT: Literal["assistant"] = "assistant"

Role = Literal["system", "user", "assistant"]


class ChatMessage(TypedDict, total=False):
    """LiteLLM 可直接消费的消息结构。"""

    role: Role
    content: str | list[dict]
