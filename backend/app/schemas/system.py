"""系统初始化接口 schema。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

_MAX_FEEDBACK_IMAGE_CHARS = 2_500_000


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


SettingSource = Literal["env", "settings", "system_settings", "user_settings", "runtime"]
SettingStatus = Literal["configured", "missing", "default", "disabled", "enabled", "runtime"]


class SettingEntry(BaseModel):
    """单个后端设置项的展示模型。"""

    key: str = Field(description="稳定设置键。")
    label: str = Field(description="展示名称。")
    source: SettingSource = Field(description="配置来源：env/settings/user_settings/runtime。")
    value: Any | None = Field(default=None, description="可安全展示的当前值。")
    default_value: Any | None = Field(default=None, description="项目默认值。")
    user_value: Any | None = Field(default=None, description="当前用户覆盖值。")
    display_value: str | None = Field(default=None, description="格式化展示值。")
    status: SettingStatus = Field(description="当前配置状态。")
    secret: bool = Field(default=False, description="是否为敏感配置。")
    editable: bool = Field(default=False, description="是否可在页面直接编辑。")
    restart_required: bool = Field(default=True, description="修改后是否需要重启后端。")
    derived: bool = Field(default=False, description="是否为运行时派生值，只读展示。")
    ui_group: str = Field(default="", description="设置页内的展示分组。")
    ui_order: int = Field(default=0, description="设置页内的稳定排序值。")
    description: str = Field(default="", description="说明。")


class SettingSection(BaseModel):
    """设置分组。"""

    id: str = Field(description="分组 ID。")
    label: str = Field(description="分组名称。")
    description: str = Field(description="分组说明。")
    entries: list[SettingEntry] = Field(default_factory=list, description="设置项。")


class SettingsOverviewData(BaseModel):
    """后端设置总览。"""

    settings_source: str = Field(description="当前项目设置来源；无外部 override 时显示 code defaults。")
    mode: str = Field(description="运行模式。")
    sections: list[SettingSection] = Field(default_factory=list, description="设置分组。")
    notes: list[str] = Field(default_factory=list, description="设置说明。")


class UpdateUserSettingsRequest(BaseModel):
    """更新本地模式下的系统级 settings 覆盖。"""

    settings: dict[str, Any] = Field(default_factory=dict, description="与 Settings schema 同构的系统级非敏感覆盖。")
    env: dict[str, str | None] = Field(default_factory=dict, description="仅本地模式可编辑的环境变量覆盖，键使用设置项 key。")
    reset: bool = Field(default=False, description="是否清空系统级覆盖，恢复项目默认值。")


class FeedbackRequest(BaseModel):
    """用户体验与问题反馈请求。"""

    content: str = Field(min_length=1, max_length=2000, description="反馈内容。")
    images: list[str] = Field(default_factory=list, max_length=3, description="可选的 Base64 截图列表。")

    @field_validator("images")
    @classmethod
    def validate_images(cls, images: list[str]) -> list[str]:
        for image in images:
            if len(image) > _MAX_FEEDBACK_IMAGE_CHARS:
                raise ValueError("单张反馈截图过大。")
            if not image.startswith("data:image/") or ";base64," not in image:
                raise ValueError("反馈截图必须是 data:image/*;base64 格式。")
        return images
