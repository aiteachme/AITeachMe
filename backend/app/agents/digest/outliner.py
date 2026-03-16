"""Outline extraction for one digest document."""

from __future__ import annotations

from pydantic import BaseModel, Field
import structlog

from app.core.llm import acompletion_structured
from app.repositories.models import DocumentOutlineNode
from app.schemas.llm import ChatMessage, SYSTEM, USER

logger = structlog.get_logger()


class OutlineItem(BaseModel):
    title: str = Field(description="Outline node title.")
    level: int = Field(description="Outline depth where 1 is the top level.")
    children: list["OutlineItem"] = Field(default_factory=list, description="Nested child nodes.")


class OutlineResult(BaseModel):
    nodes: list[OutlineItem] = Field(description="Top-level outline nodes.")


_SYSTEM_PROMPT = """You extract a concise hierarchical outline from markdown study material.

Requirements:
1. Return the core concepts in tree form.
2. Keep the outline close to the source order.
3. Prefer 1-3 levels of depth.
4. Keep titles short and readable.
"""


async def extract_outline(markdown: str) -> list[OutlineItem]:
    messages = [
        ChatMessage(role=SYSTEM, content=_SYSTEM_PROMPT),
        ChatMessage(role=USER, content=markdown),
    ]
    result = await acompletion_structured(
        response_model=OutlineResult,
        messages=messages,
    )
    logger.info("outline_extracted", top_nodes=len(result.nodes))
    return result.nodes


def bulk_insert_outline(
    session: "Session",
    nodes: list[OutlineItem],
    document_id: int,
) -> list[DocumentOutlineNode]:
    inserted: list[DocumentOutlineNode] = []

    def _insert_level(
        items: list[OutlineItem],
        parent_id: int | None,
        order_start: int,
    ) -> int:
        order = order_start
        for item in items:
            db_node = DocumentOutlineNode(
                document_id=document_id,
                parent_id=parent_id,
                title=item.title,
                level=item.level,
                order_index=order,
            )
            session.add(db_node)
            session.flush()
            inserted.append(db_node)
            order += 1

            if item.children:
                order = _insert_level(item.children, db_node.id, order)
        return order

    _insert_level(nodes, None, 0)
    session.commit()
    for node in inserted:
        session.refresh(node)
    return inserted
