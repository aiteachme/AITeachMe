"""鉴权接口 schema。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.system import RuntimeUser


class RegisterRequest(BaseModel):
    """注册请求。"""

    model_config = ConfigDict(
        json_schema_extra={"example": {"email": "user@example.com", "password": "change-me"}}
    )

    email: str = Field(description="邮箱。")
    password: str = Field(min_length=6, description="密码。")


class LoginRequest(BaseModel):
    """登录请求。"""

    model_config = ConfigDict(
        json_schema_extra={"example": {"email": "user@example.com", "password": "change-me"}}
    )

    email: str = Field(description="邮箱。")
    password: str = Field(min_length=6, description="密码。")


class LogoutRequest(BaseModel):
    """登出请求。"""

    model_config = ConfigDict(json_schema_extra={"example": {}})


class AuthSessionData(BaseModel):
    """鉴权会话数据。"""

    auth_enabled: bool = Field(description="是否启用鉴权。")
    auth_ready: bool = Field(description="鉴权是否就绪。")
    token_type: str = Field(default="bearer", description="令牌类型。")
    access_token: str | None = Field(default=None, description="访问令牌。")
    current_user: RuntimeUser | None = Field(default=None, description="当前用户。")
