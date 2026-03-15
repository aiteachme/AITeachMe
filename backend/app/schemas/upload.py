"""上传相关 Schema — UploadResponse、PipelineStatusResponse、FileListResponse"""

from datetime import datetime
from pydantic import BaseModel


class UploadResponse(BaseModel):
    task_id: int
    filename: str
    subject: str


class PipelineStatusResponse(BaseModel):
    stage: str          # upload | parse | digest | done | failed
    progress: int       # 0~100
    message: str
    error: str | None = None


class FileItem(BaseModel):
    id: int
    filename: str
    filetype: str
    parse_status: str
    created_at: datetime


class FileListResponse(BaseModel):
    items: list[FileItem]
    total: int
