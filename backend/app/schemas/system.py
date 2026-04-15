"""系统初始化接口 schema。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class InitRequest(BaseModel):
    """系统初始化请求。"""

    model_config = ConfigDict(json_schema_extra={"example": {}})


class RuntimeUser(BaseModel):
    """当前运行时用户。"""

    user_id: str = Field(description="用户 ID。")
    email: str | None = Field(default=None, description="邮箱。")
    is_local: bool = Field(description="是否为本地模式用户。")
    device_key: str | None = Field(default=None, description="设备标识。")
    is_authenticated: bool = Field(default=False, description="是否已完成账号登录。")


class InitData(BaseModel):
    """系统初始化返回数据。"""

    mode: str = Field(description="运行模式。")
    auth_enabled: bool = Field(description="是否启用鉴权。")
    auth_ready: bool = Field(description="鉴权能力是否就绪。")
    current_user: RuntimeUser | None = Field(default=None, description="当前用户。")
    feature_flags: dict[str, bool] = Field(description="功能开关。")
    version: str = Field(description="版本号。")


SettingSource = Literal["env", "config", "runtime"]
SettingStatus = Literal["configured", "missing", "default", "disabled", "enabled", "runtime"]


class SettingEntry(BaseModel):
    """单个后端设置项的展示模型。"""

    key: str = Field(description="稳定设置键。")
    label: str = Field(description="展示名称。")
    source: SettingSource = Field(description="配置来源：env/config/runtime。")
    value: Any | None = Field(default=None, description="可安全展示的当前值。")
    display_value: str | None = Field(default=None, description="格式化展示值。")
    status: SettingStatus = Field(description="当前配置状态。")
    secret: bool = Field(default=False, description="是否为敏感配置。")
    editable: bool = Field(default=False, description="是否可在页面直接编辑。")
    restart_required: bool = Field(default=True, description="修改后是否需要重启后端。")
    description: str = Field(default="", description="说明。")


class SettingSection(BaseModel):
    """设置分组。"""

    id: str = Field(description="分组 ID。")
    label: str = Field(description="分组名称。")
    description: str = Field(description="分组说明。")
    entries: list[SettingEntry] = Field(default_factory=list, description="设置项。")


class SettingsOverviewData(BaseModel):
    """后端设置总览。"""

    config_path: str = Field(description="当前项目配置文件路径。")
    mode: str = Field(description="运行模式。")
    sections: list[SettingSection] = Field(default_factory=list, description="设置分组。")
    notes: list[str] = Field(default_factory=list, description="设置说明。")
