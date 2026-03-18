"""候选知识抽取：从 DocumentChunk 中抽取候选节点和候选边。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field
import structlog

from app.agents.digest.prompts import SYSTEM_PROMPT_KG_EXTRACT, USER_PROMPT_KG_EXTRACT
from app.core.llm import acompletion_structured
from app.core.prompt_loader import populate_prompt
from app.schemas.llm import ChatMessage, SYSTEM, USER

logger = structlog.get_logger()


# ── Pydantic 模型 ──────────────────────────────────────────────


class CandidateNode(BaseModel):
    """从 chunk 中抽取的候选知识节点。"""

    name: str = Field(description="知识节点名称，其中数学公式用 LaTeX 语法 $...$ 包裹。")
    node_type: Literal["Topic", "Concept", "Definition", "Method", "Example"] = Field(
        description="节点类型，限定为 Topic/Concept/Definition/Method/Example。"
    )
    local_summary: str = Field(description="该知识点在本段文本中的核心内容摘要，内容较多时可分段（用换行分隔）。数学公式必须使用 LaTeX 语法，行内公式用 $...$ 包裹，独立公式用 $$...$$ 包裹。")
    taxonomy_hint: str = Field(
        default="",
        description="该节点最可能归属的上层主题名称，用于后续主题树对齐。",
    )
    parent_entity_name: str | None = Field(
        default=None,
        description="Definition/Example 类型必填：所属的 Concept 或 Method 名称。",
    )


class CandidateEdge(BaseModel):
    """从 chunk 中抽取的候选知识边。"""

    source_name: str = Field(description="源节点名称，须与抽取出的节点 name 一致。")
    target_name: str = Field(description="目标节点名称，须与抽取出的节点 name 一致。")
    edge_type: Literal[
        "belongs_to_topic",
        "prerequisite_of",
        "defined_by",
        "illustrated_by",
        "part_of",
    ] = Field(description="边类型。")
    description: str = Field(description="关系描述，其中数学公式用 LaTeX 语法 $...$ 包裹。")


class ChunkExtractionResult(BaseModel):
    """单个 chunk 的抽取结果。"""

    nodes: list[CandidateNode] = Field(default_factory=list, description="候选知识节点列表。")
    edges: list[CandidateEdge] = Field(default_factory=list, description="候选知识边列表。")


# ── 抽取函数 ───────────────────────────────────────────────────


async def extract_candidates(
    chunk_content: str,
    chunk_title: str,
    header_path: str,
    doc_source_type: str | None = None,
) -> ChunkExtractionResult:
    """对单个 chunk 调用 LLM 抽取候选知识节点和候选边。

    Args:
        chunk_content: chunk 文本内容。
        chunk_title: chunk 标题。
        header_path: 文档结构路径（如 "第一章 > 1.1 导数"）。
        doc_source_type: 文档来源类型（如 "textbook"、"lecture_note"）。

    Returns:
        ChunkExtractionResult 包含候选节点和候选边。
    """
    user_content = populate_prompt(
        USER_PROMPT_KG_EXTRACT,
        chunk_content=chunk_content,
        chunk_title=chunk_title,
        header_path=header_path,
        doc_source_type=doc_source_type or "",
    )

    messages: list[ChatMessage] = [
        {"role": SYSTEM, "content": SYSTEM_PROMPT_KG_EXTRACT},
        {"role": USER, "content": user_content},
    ]

    result = await acompletion_structured(
        response_model=ChunkExtractionResult,
        messages=messages,
    )

    logger.info(
        "kg_extract_complete",
        chunk_title=chunk_title,
        node_count=len(result.nodes),
        edge_count=len(result.edges),
    )
    return result
