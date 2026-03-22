"""聊天接口 schema。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import PageParams
from app.schemas.enums import ChatRoleValue


class ChatSendRequest(BaseModel):
    """发送消息请求。"""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "question": "什么是条件概率？",
                "source": "quick_chat",
                "selected_context": "条件概率表示在 B 已经发生的前提下 A 发生的概率。",
                "source_chunk_id": 12,
            }
        }
    )

    question: str = Field(description="当前问题。")
    source: str | None = Field(default=None, description="消息来源标识；有值时走直连大模型模式。")
    selected_context: str | None = Field(default=None, description="用户划词上下文。")
    source_chunk_id: int | None = Field(default=None, description="划词来源块 ID。")


class ChatListRequest(PageParams):
    """聊天分页请求。"""


class ChatClearRequest(BaseModel):
    """清空聊天记录请求。"""

    model_config = ConfigDict(json_schema_extra={"example": {}})


class ChatClearData(BaseModel):
    """清空聊天记录结果。"""

    cleared: bool = Field(description="是否清空成功。")
    deleted_count: int = Field(description="删除消息条数。", ge=0)


class SSETokenEvent(BaseModel):
    """SSE token 事件。"""

    content: str = Field(description="增量文本。")


class SSEDoneEvent(BaseModel):
    """SSE done 事件。"""

    turn_id: str = Field(description="对话轮次 ID。")
    contexts: list[dict] | None = Field(default=None, description="命中的上下文列表。")


class SSEErrorEvent(BaseModel):
    """SSE error 事件。"""

    detail: str = Field(description="错误原因。")
    error_code: str = Field(description="错误码。")


class ChatMessageItem(BaseModel):
    """聊天记录项。"""

    id: int = Field(description="消息 ID。")
    turn_id: str = Field(description="轮次 ID。")
    role: ChatRoleValue = Field(description="消息角色。")
    content: str = Field(description="消息内容。")
    contexts: list[dict] | None = Field(default=None, description="关联上下文。")
    created_at: datetime = Field(description="创建时间。")
