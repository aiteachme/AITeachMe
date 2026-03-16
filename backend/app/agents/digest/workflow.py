"""纯内存的知识消化工作流。"""

from __future__ import annotations

from typing import TypedDict

from app.agents.digest.chunker import chunk_markdown
from app.agents.digest.cleaner import clean_markdown
from app.agents.digest.embedder import embed_chunks
from app.agents.digest.outliner import OutlineItem, extract_outline
from app.models import DigestStep


class DigestWorkflowResult(TypedDict):
    """知识消化工作流输出。"""

    cleaned_markdown: str
    outline_items: list[OutlineItem]
    chunks: list[ChunkData]
    embeddings: list[list[float]]
    final_step: str


async def run_digest_workflow(raw_markdown: str) -> DigestWorkflowResult:
    """执行纯内存知识消化流程。"""

    cleaned_markdown = clean_markdown(raw_markdown)
    outline_items = await extract_outline(cleaned_markdown)
    chunks = chunk_markdown(cleaned_markdown)
    embeddings = await embed_chunks(chunks)
    return {
        "cleaned_markdown": cleaned_markdown,
        "outline_items": outline_items,
        "chunks": chunks,
        "embeddings": embeddings,
        "final_step": DigestStep.EMBEDDED.value,
    }
