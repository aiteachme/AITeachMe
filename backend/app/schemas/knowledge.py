"""知识集合接口 schema。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import PageParams
from app.schemas.enums import DigestStepValue, TaskStatusValue


class KnowledgeBuildRequest(BaseModel):
    """知识构建请求。"""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "file_ids": [1, 2],
                "title": "概率论期中复习",
                "desc": "课件与笔记",
            }
        }
    )

    file_ids: list[int] = Field(min_length=1, description="参与构建的已解析文件 ID。")
    title: str = Field(description="知识集合标题。")
    desc: str = Field(default="", description="知识集合描述。")


class KnowledgeStatusRequest(BaseModel):
    """知识状态请求。"""

    docset_id: int = Field(description="知识集合 ID。")


class KnowledgeGetRequest(KnowledgeStatusRequest):
    """知识详情请求。"""


class KnowledgeTreeRequest(KnowledgeStatusRequest):
    """知识树请求。"""


class KnowledgeRetryRequest(KnowledgeStatusRequest):
    """知识重试请求。"""


class KnowledgeDeleteRequest(KnowledgeStatusRequest):
    """知识删除请求。"""


class KnowledgeListRequest(PageParams):
    """知识集合列表请求。"""


class KnowledgeBuildData(BaseModel):
    """知识构建返回数据。"""

    docset_id: int = Field(description="知识集合 ID。")
    build_job_id: int = Field(description="构建任务 ID。")


class KnowledgeDeleteData(BaseModel):
    """知识删除返回数据。"""

    deleted: bool = Field(description="是否删除成功。")
    docset_id: int = Field(description="知识集合 ID。")


class KnowledgeStatusData(BaseModel):
    """知识构建状态。"""

    docset_id: int = Field(description="知识集合 ID。")
    build_job_id: int | None = Field(default=None, description="最新构建任务 ID。")
    status: TaskStatusValue = Field(description="构建任务状态。")
    current_step: DigestStepValue | None = Field(default=None, description="当前构建步骤。")
    progress: int = Field(description="构建进度。", ge=0, le=100)
    message: str = Field(description="进度说明。")
    docs_count: int = Field(description="文档数量。", ge=0)
    chunks_count: int = Field(description="切块数量。", ge=0)
    error_message: str | None = Field(default=None, description="失败原因。")


class DocSetItem(BaseModel):
    """知识集合列表项。"""

    id: int = Field(description="知识集合 ID。")
    title: str = Field(description="标题。")
    description: str = Field(description="描述。")
    status: TaskStatusValue | None = Field(default=None, description="最新构建状态。")
    documents_count: int = Field(description="文档数。", ge=0)
    created_at: datetime = Field(description="创建时间。")
    updated_at: datetime = Field(description="更新时间。")


class DocumentItem(BaseModel):
    """文档项。"""

    id: int = Field(description="文档 ID。")
    source_file_id: int = Field(description="源文件 ID。")
    title: str = Field(description="标题。")
    markdown_content: str = Field(description="文档 Markdown。")
    current_step: DigestStepValue | None = Field(default=None, description="文档当前步骤。")


class KnowledgeGetData(BaseModel):
    """知识集合详情。"""

    docset_id: int = Field(description="知识集合 ID。")
    title: str = Field(description="标题。")
    description: str = Field(description="描述。")
    status: TaskStatusValue | None = Field(default=None, description="最新构建状态。")
    documents: list[DocumentItem] = Field(default_factory=list, description="文档列表。")


class OutlineNode(BaseModel):
    """大纲树节点。"""

    id: int = Field(description="节点 ID。")
    title: str = Field(description="节点标题。")
    level: int = Field(description="层级。", ge=1)
    children: list["OutlineNode"] = Field(default_factory=list, description="子节点。")


class DocumentTreeItem(BaseModel):
    """单文档大纲树。"""

    document_id: int = Field(description="文档 ID。")
    title: str = Field(description="文档标题。")
    nodes: list[OutlineNode] = Field(default_factory=list, description="树节点列表。")


class KnowledgeTreeData(BaseModel):
    """知识树数据。"""

    docset_id: int = Field(description="知识集合 ID。")
    title: str = Field(description="知识集合标题。")
    documents: list[DocumentTreeItem] = Field(default_factory=list, description="各文档大纲树。")
