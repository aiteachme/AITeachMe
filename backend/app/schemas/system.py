"""系统初始化接口 schema。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class InitRequest(BaseModel):
    """系统初始化请求。"""

    model_config = ConfigDict(json_schema_extra={"example": {}})


class RuntimeUser(BaseModel):
    """当前运行时用户。"""

    user_id: str = Field(description="用户 ID。")
    email: str | None = Field(default=None, description="邮箱。")
    is_local: bool = Field(description="是否为本地模式用户。")


class InitData(BaseModel):
    """系统初始化返回数据。"""

    mode: str = Field(description="运行模式。")
    auth_enabled: bool = Field(description="是否启用鉴权。")
    auth_ready: bool = Field(description="鉴权能力是否就绪。")
    current_user: RuntimeUser | None = Field(default=None, description="当前用户。")
    feature_flags: dict[str, bool] = Field(description="功能开关。")
    version: str = Field(description="版本号。")
