"""内部 LLM 消息结构。"""

from __future__ import annotations

from typing import Literal, TypedDict

SYSTEM: Literal["system"] = "system"
USER: Literal["user"] = "user"
ASSISTANT: Literal["assistant"] = "assistant"
TOOL: Literal["tool"] = "tool"

Role = Literal["system", "user", "assistant", "tool"]


class ChatMessage(TypedDict, total=False):
    """LiteLLM 可直接消费的消息结构。"""

    role: Role
    content: str | list[dict] | None
    tool_call_id: str          # role="tool" 时必填
    tool_calls: list[dict]     # role="assistant" 且有工具调用时
    name: str                  # 工具名称（可选）

