"""文件接口 schema。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.common import PageParams
from app.schemas.enums import TaskStatusValue


class FilesParseRequest(BaseModel):
    """批量解析文件请求。"""

    file_ids: list[int] = Field(min_length=1, description="待解析文件 ID 列表。")


class FileStatusRequest(BaseModel):
    """单文件状态请求。"""

    file_id: int = Field(description="文件 ID。")


class FileGetRequest(FileStatusRequest):
    """单文件详情请求。"""


class FileRetryRequest(FileStatusRequest):
    """文件重试请求。"""


class FileDeleteRequest(BaseModel):
    """文件删除请求。"""

    file_id: int | None = Field(default=None, description="单个文件 ID。")
    file_ids: list[int] | None = Field(default=None, description="多个文件 ID。")

    @model_validator(mode="after")
    def validate_ids(self) -> "FileDeleteRequest":
        if self.file_id is None and not self.file_ids:
            raise ValueError("file_id 和 file_ids 至少提供一个。")
        return self


class FileListRequest(PageParams):
    """文件列表请求。"""

    status: TaskStatusValue | None = Field(default=None, description="可选状态过滤。")


class FilesUploadData(BaseModel):
    """上传返回数据。"""

    subject: str = Field(description="学科标识。")
    file_ids: list[int] = Field(description="新建文件 ID 列表。")
    filenames: list[str] = Field(description="原始文件名列表。")


class FilesParseData(BaseModel):
    """解析触发返回数据。"""

    accepted_file_ids: list[int] = Field(description="已受理解析的文件 ID。")


class FileDeleteData(BaseModel):
    """文件删除结果。"""

    deleted_file_ids: list[int] = Field(description="已删除文件 ID。")


class FileItem(BaseModel):
    """文件列表项。"""

    id: int = Field(description="文件 ID。")
    filename: str = Field(description="文件名。")
    filetype: str = Field(description="文件扩展名。")
    status: TaskStatusValue = Field(description="解析状态。")
    markdown_ready: bool = Field(description="Markdown 是否已生成。")
    latest_updated_at: datetime = Field(description="最近更新时间。")
    created_at: datetime = Field(description="创建时间。")


class FileStatusData(BaseModel):
    """文件状态数据。"""

    file_id: int = Field(description="文件 ID。")
    upload_status: str = Field(description="上传状态。")
    status: TaskStatusValue = Field(description="解析任务状态。")
    markdown_ready: bool = Field(description="Markdown 是否可用。")
    asset_ready: bool = Field(description="资源目录是否可用。")
    error_message: str | None = Field(default=None, description="失败原因。")
    latest_updated_at: datetime = Field(description="最近更新时间。")


class FileAssetItem(BaseModel):
    """资源文件项。"""

    path: str = Field(description="资源路径。")


class FileGetData(BaseModel):
    """文件解析结果。"""

    file_id: int = Field(description="文件 ID。")
    filename: str = Field(description="文件名。")
    status: TaskStatusValue = Field(description="解析任务状态。")
    markdown_content: str = Field(description="解析后的 Markdown。")
    assets: list[FileAssetItem] = Field(default_factory=list, description="资源列表。")
