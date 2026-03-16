"""知识大纲提取器。"""

from __future__ import annotations

from pydantic import BaseModel, Field
import structlog

from app.core.llm import acompletion_structured
from app.core.prompt_loader import render_prompt
from app.schemas.llm import ChatMessage, SYSTEM, USER

logger = structlog.get_logger()


class OutlineItem(BaseModel):
    """大纲节点。"""

    title: str = Field(description="节点标题。")
    level: int = Field(description="层级。")
    children: list["OutlineItem"] = Field(default_factory=list, description="子节点。")


class OutlineResult(BaseModel):
    """大纲结果。"""

    nodes: list[OutlineItem] = Field(default_factory=list, description="根节点列表。")


async def extract_outline(markdown: str) -> list[OutlineItem]:
    """从 Markdown 中提取层级大纲。"""

    messages: list[ChatMessage] = [
        {"role": SYSTEM, "content": render_prompt("digest/prompts/outline_extract.j2")},
        {"role": USER, "content": markdown},
    ]
    result = await acompletion_structured(response_model=OutlineResult, messages=messages)
    logger.info("extract_outline_complete", node_count=len(result.nodes))
    return result.nodes
