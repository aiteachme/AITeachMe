"""
大纲提取节点

调用 LLM 阅读 Markdown 并生成层级知识大纲。
写入 KnowledgeGraphNode 记录，关联 knowledge_id 外键。
更新 Knowledge.pipeline_stage 为 outlined。

需求：7.3
"""

from __future__ import annotations

from pydantic import BaseModel, Field

import structlog

from app.core.llm import acompletion_structured
from app.repositories.models import KnowledgeGraphNode
from app.schemas.llm import ChatMessage, SYSTEM, USER

logger = structlog.get_logger()


# ─── LLM 结构化输出模型 ───


class OutlineItem(BaseModel):
    """大纲节点（LLM 输出格式）"""
    title: str = Field(description="知识点标题")
    level: int = Field(description="层级深度，1 为顶层")
    children: list["OutlineItem"] = Field(default_factory=list, description="子节点列表")


class OutlineResult(BaseModel):
    """LLM 生成的完整大纲"""
    nodes: list[OutlineItem] = Field(description="顶层大纲节点列表")


_SYSTEM_PROMPT = """你是一个知识大纲提取专家。请阅读以下 Markdown 文档，提取出层级化的知识大纲。

要求：
1. 提取文档中的核心知识点，组织为树形结构
2. 顶层节点为主要章节/主题，子节点为具体知识点
3. 层级不超过 3 层
4. 每个节点的 title 应简洁明了
5. level 从 1 开始，1 为顶层
6. 保持原文档的逻辑顺序"""


async def extract_outline(markdown: str) -> list[OutlineItem]:
    """调用 LLM 从 Markdown 中提取层级知识大纲。

    Args:
        markdown: 清洗后的 Markdown 文本。

    Returns:
        大纲节点列表（树形结构）。

    Raises:
        LLMCallError: LLM 调用失败时抛出（由 core/llm 统一处理重试）。
    """
    messages = [
        ChatMessage(role=SYSTEM, content=_SYSTEM_PROMPT),
        ChatMessage(role=USER, content=markdown),
    ]
    result = await acompletion_structured(
        response_model=OutlineResult,
        messages=messages,
    )
    logger.info("outline_extracted", num_top_nodes=len(result.nodes))
    return result.nodes


def flatten_outline(
    nodes: list[OutlineItem],
    knowledge_id: int,
    *,
    parent_id: int | None = None,
    start_order: int = 0,
) -> list[KnowledgeGraphNode]:
    """将树形大纲扁平化为 KnowledgeGraphNode 列表。

    注意：返回的节点 id 为 None（由数据库自动生成），
    parent_id 需要在批量插入后回填。此函数返回的是待插入的节点列表，
    调用方需按顺序插入并处理 parent_id 映射。

    Args:
        nodes: LLM 输出的树形大纲节点。
        knowledge_id: 关联的 Knowledge ID。
        parent_id: 父节点 ID（顶层为 None）。
        start_order: 起始排序索引。

    Returns:
        扁平化的 KnowledgeGraphNode 列表（按深度优先顺序）。
    """
    result: list[KnowledgeGraphNode] = []
    order = start_order

    for item in nodes:
        node = KnowledgeGraphNode(
            knowledge_id=knowledge_id,
            parent_id=parent_id,
            title=item.title,
            level=item.level,
            order_index=order,
        )
        result.append(node)
        order += 1

        if item.children:
            # 子节点的 parent_id 需要在插入后回填
            # 这里先用占位符 None，由 bulk_insert_outline 处理
            children = flatten_outline(
                item.children,
                knowledge_id,
                parent_id=None,  # 占位，后续回填
                start_order=order,
            )
            result.extend(children)
            order += len(children)

    return result


def bulk_insert_outline(
    session: "Session",
    nodes: list[OutlineItem],
    knowledge_id: int,
) -> list[KnowledgeGraphNode]:
    """将大纲树逐层插入数据库，正确处理 parent_id 外键。

    Args:
        session: 数据库会话。
        nodes: LLM 输出的树形大纲节点。
        knowledge_id: 关联的 Knowledge ID。

    Returns:
        已插入的 KnowledgeGraphNode 列表。
    """
    all_inserted: list[KnowledgeGraphNode] = []

    def _insert_level(
        items: list[OutlineItem],
        parent_id: int | None,
        order_start: int,
    ) -> int:
        order = order_start
        for item in items:
            db_node = KnowledgeGraphNode(
                knowledge_id=knowledge_id,
                parent_id=parent_id,
                title=item.title,
                level=item.level,
                order_index=order,
            )
            session.add(db_node)
            session.flush()  # 获取自动生成的 id
            all_inserted.append(db_node)
            order += 1

            if item.children:
                order = _insert_level(item.children, db_node.id, order)
        return order

    _insert_level(nodes, None, 0)
    session.commit()
    for node in all_inserted:
        session.refresh(node)
    return all_inserted
