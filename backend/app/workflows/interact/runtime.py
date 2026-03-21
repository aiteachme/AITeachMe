"""Runtime helpers for the interact workflow."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator, Callable

from fastapi import Request
from pydantic import BaseModel

from app.core.embedding import aembed_texts
from app.core.llm import acompletion_stream
from app.core.prompt_loader import populate_prompt
from app.schemas.llm import ASSISTANT, ChatMessage, SYSTEM, USER
from app.workflows.interact.prompts import SYSTEM_PROMPT_TUTOR


class RetrievedChunkPayload(BaseModel):
    """A raw retrieval payload returned by the repository layer."""

    chunk_id: int
    document_id: int
    title: str
    header_path: str
    content: str
    score: float


class RetrievalResult(BaseModel):
    """A retrieval result formatted for chat prompting."""

    chunk_id: int
    document_id: int
    title: str
    header_path: str
    content: str
    score: float
    low_relevance: bool


SearchFunc = Callable[[list[float], str, int], list[dict]]


def build_chat_messages(
    *,
    subject: str,
    retrieval_results: list[RetrievalResult],
    recent_messages: list[dict],
    weak_points: list[dict],
    recent_mistakes: list[dict],
    question: str,
    selected_context: str | None = None,
    source_chunk_id: int | None = None,
) -> list[ChatMessage]:
    """Build the full chat message list sent to the LLM."""

    system_prompt = populate_prompt(
        SYSTEM_PROMPT_TUTOR,
        subject=subject,
        retrieval_context=_format_retrieval_context(retrieval_results),
        weak_points_context=_format_weak_points_context(weak_points),
        mistakes_context=_format_mistakes_context(recent_mistakes),
        selected_context=_format_selected_context(selected_context, source_chunk_id),
    )
    messages: list[ChatMessage] = [{"role": SYSTEM, "content": system_prompt}]

    for item in recent_messages:
        role = ASSISTANT if item["role"] == "assistant" else USER
        messages.append({"role": role, "content": item["content"]})

    messages.append({"role": USER, "content": question})
    return messages


def build_retrieval_results(
    *,
    items: list[dict],
    similarity_threshold: float,
) -> list[RetrievalResult]:
    """Convert repository search results into prompt-ready records."""

    payloads = [RetrievedChunkPayload.model_validate(item) for item in items]
    return [
        RetrievalResult(
            chunk_id=payload.chunk_id,
            document_id=payload.document_id,
            title=payload.title,
            header_path=payload.header_path,
            content=payload.content,
            score=payload.score,
            low_relevance=payload.score < similarity_threshold,
        )
        for payload in payloads
    ]


async def build_query_embedding(query: str) -> list[float]:
    """Build the embedding used for vector retrieval."""

    return (await aembed_texts([query]))[0]


async def retrieve(
    *,
    query: str,
    subject: str,
    top_k: int,
    similarity_threshold: float,
    search_func: SearchFunc,
) -> list[RetrievalResult]:
    """Run the retrieval flow for one chat request."""

    query_embedding = await build_query_embedding(query)
    items = search_func(query_embedding, subject, top_k)
    return build_retrieval_results(items=items, similarity_threshold=similarity_threshold)


def format_sse_event(event: str, data: dict) -> str:
    """Format one SSE event payload."""

    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def stream_llm_events(
    request: Request,
    messages: list[ChatMessage],
    collected_tokens: list[str],
) -> AsyncGenerator[str, None]:
    """Yield streamed LLM tokens as SSE events."""

    stream = acompletion_stream(messages)
    async for token in stream:
        if await request.is_disconnected():
            await stream.aclose()
            return
        collected_tokens.append(token)
        yield format_sse_event("token", {"content": token})


def _format_retrieval_context(results: list[RetrievalResult]) -> str:
    if not results:
        return "暂无命中资料。"

    return "\n\n".join(
        (
            f"[资料 {index}] 相关度：{'低相关' if result.low_relevance else '高相关'}，分数：{result.score:.4f}\n"
            f"路径：{result.header_path}\n"
            f"内容：{result.content}"
        )
        for index, result in enumerate(results, start=1)
    )


def _format_weak_points_context(weak_points: list[dict]) -> str:
    if not weak_points:
        return "暂无薄弱项数据。"

    return "\n".join(
        f"- {item['knowledge_point']}（掌握度：{item['mastery_text']}）"
        for item in weak_points
    )


def _format_mistakes_context(mistakes: list[dict]) -> str:
    if not mistakes:
        return "暂无近期错题。"

    return "\n\n".join(
        (
            f"题干：{item['question_stem']}\n"
            f"用户答案：{item['user_answer']}\n"
            f"正确答案：{item['correct_answer']}\n"
            f"错因：{item['analysis']}"
        )
        for item in mistakes
    )


def _format_selected_context(selected_context: str | None, source_chunk_id: int | None) -> str:
    if not selected_context:
        return "无。"
    if source_chunk_id is None:
        return selected_context
    return f"[chunk_id={source_chunk_id}]\n{selected_context}"
