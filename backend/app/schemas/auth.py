"""鉴权接口 schema。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.system import RuntimeUser


class RegisterRequest(BaseModel):
    """注册请求。"""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "email": "user@example.com",
                "password": "change-me",
                "verification_code": "123456",
            }
        }
    )

    email: str = Field(description="邮箱。")
    password: str = Field(min_length=6, description="密码。")
    verification_code: str = Field(min_length=4, max_length=16, description="邮箱验证码。")


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


class SendEmailCodeRequest(BaseModel):
    """发送邮箱验证码请求。"""

    model_config = ConfigDict(json_schema_extra={"example": {"email": "user@example.com"}})

    email: str = Field(description="目标邮箱。")


class SendEmailCodeData(BaseModel):
    """发送邮箱验证码响应数据。"""

    expires_in_s: int = Field(description="验证码有效期（秒）。", ge=1)
    resend_after_s: int = Field(description="允许再次发送的最短间隔（秒）。", ge=1)


class AuthSessionData(BaseModel):
    """鉴权会话数据。"""

    auth_enabled: bool = Field(description="是否启用鉴权。")
    auth_ready: bool = Field(description="鉴权是否就绪。")
    token_type: str = Field(default="bearer", description="令牌类型。")
    access_token: str | None = Field(default=None, description="访问令牌。")
    current_user: RuntimeUser | None = Field(default=None, description="当前用户。")
