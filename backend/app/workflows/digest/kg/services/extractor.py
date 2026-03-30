"""Candidate extraction for digest graph workflow."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field
import structlog

from app.infra.llm import acompletion_structured
from app.infra.model_router import TaskType
from app.infra.prompt_loader import populate_prompt
from app.schemas.llm import ChatMessage, SYSTEM, USER
from app.workflows.digest.kg.services.chunker import QuestionBlock, parse_question_blocks
from app.workflows.digest.prompts import SYSTEM_PROMPT_KG_EXTRACT, USER_PROMPT_KG_EXTRACT

logger = structlog.get_logger()

_QUESTION_RANGE_SUFFIX_RE = re.compile(r"\s*/\s*(?:Question|Questions)\s+\d+(?:-\d+)?$", re.IGNORECASE)
_MARKDOWN_DECORATION_RE = re.compile(r"[#*_`>]+")
_MULTISPACE_RE = re.compile(r"\s+")
_MAX_EXAMPLE_NAME_CHARS = 48
_MAX_EXAMPLE_SUMMARY_CHARS = 800
_MAX_TOPIC_SUMMARY_CHARS = 240


class CandidateNode(BaseModel):
    """A candidate knowledge node extracted from a chunk."""

    name: str = Field(description="Knowledge node name.")
    node_type: Literal["Topic", "Concept", "Definition", "Method", "Example"] = Field(
        description="Allowed node type."
    )
    local_summary: str = Field(description="Summary grounded in the current chunk.")
    taxonomy_hint: str = Field(default="", description="Likely parent topic.")
    parent_entity_name: str | None = Field(
        default=None,
        description="Parent concept, method, or topic for definition/example nodes.",
    )


class CandidateEdge(BaseModel):
    """A candidate edge extracted from a chunk."""

    source_name: str = Field(description="Source node name.")
    target_name: str = Field(description="Target node name.")
    edge_type: Literal[
        "belongs_to_topic",
        "prerequisite_of",
        "defined_by",
        "illustrated_by",
        "part_of",
    ] = Field(description="Allowed edge type.")
    description: str = Field(description="Short relation description.")


class ChunkExtractionResult(BaseModel):
    """Structured extraction result for a single chunk."""

    nodes: list[CandidateNode] = Field(default_factory=list)
    edges: list[CandidateEdge] = Field(default_factory=list)


def _normalize_text(text: str) -> str:
    text = _MARKDOWN_DECORATION_RE.sub(" ", text)
    text = _MULTISPACE_RE.sub(" ", text)
    return text.strip()


def _clean_topic_name(chunk_title: str, header_path: str) -> str:
    raw_name = chunk_title if chunk_title and chunk_title != "(root)" else header_path
    raw_name = _QUESTION_RANGE_SUFFIX_RE.sub("", raw_name).strip()
    cleaned = _normalize_text(raw_name)
    return cleaned or "Study material"


def _truncate(text: str, *, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _format_example_name(question: QuestionBlock, fallback_index: int) -> str:
    prefix = f"Question {question.number}" if question.number is not None else f"Question {fallback_index}"
    stem = _truncate(_normalize_text(question.stem), limit=_MAX_EXAMPLE_NAME_CHARS)
    if not stem:
        return prefix
    return f"{prefix}: {stem}"


def _format_example_summary(question: QuestionBlock) -> str:
    return _truncate(_normalize_text(question.content), limit=_MAX_EXAMPLE_SUMMARY_CHARS)


def _looks_like_question_chunk(chunk_content: str) -> bool:
    return len(parse_question_blocks(chunk_content)) >= 2


def _split_header_path(header_path: str, chunk_title: str) -> list[str]:
    raw_path = header_path or chunk_title
    return [part.strip() for part in raw_path.split(">") if part and part.strip() and part.strip() != "(root)"]


def _build_topic_fallback(
    *,
    chunk_content: str,
    chunk_title: str,
    header_path: str,
) -> ChunkExtractionResult:
    topic_name = _clean_topic_name(chunk_title, header_path)
    summary = _truncate(_normalize_text(chunk_content), limit=_MAX_TOPIC_SUMMARY_CHARS)
    if not summary:
        summary = f"Topic fallback extracted from {header_path or chunk_title or topic_name}."

    nodes = [
        CandidateNode(
            name=topic_name,
            node_type="Topic",
            local_summary=summary,
            taxonomy_hint=topic_name,
            parent_entity_name=None,
        )
    ]
    edges: list[CandidateEdge] = []

    path_parts = _split_header_path(header_path, chunk_title)
    if len(path_parts) >= 2:
        parent_name = _normalize_text(_QUESTION_RANGE_SUFFIX_RE.sub("", path_parts[-2]))
        if parent_name and parent_name != topic_name:
            nodes.insert(
                0,
                CandidateNode(
                    name=parent_name,
                    node_type="Topic",
                    local_summary=f"Parent topic for {topic_name} extracted from document structure.",
                    taxonomy_hint=parent_name,
                    parent_entity_name=None,
                ),
            )
            edges.append(
                CandidateEdge(
                    source_name=topic_name,
                    target_name=parent_name,
                    edge_type="part_of",
                    description=f"{topic_name} is part of {parent_name}.",
                )
            )

    return ChunkExtractionResult(nodes=nodes, edges=edges)


def _build_question_fallback(
    *,
    chunk_content: str,
    chunk_title: str,
    header_path: str,
) -> ChunkExtractionResult | None:
    question_blocks = parse_question_blocks(chunk_content)
    if len(question_blocks) < 2:
        return None

    topic_name = _clean_topic_name(chunk_title, header_path)
    topic_node = CandidateNode(
        name=topic_name,
        node_type="Topic",
        local_summary=(
            f"Question-bank chunk extracted from {header_path or chunk_title}. "
            "Examples below are individual questions parsed from the source material."
        ),
        taxonomy_hint=topic_name,
        parent_entity_name=None,
    )

    nodes: list[CandidateNode] = [topic_node]
    edges: list[CandidateEdge] = []

    for index, question in enumerate(question_blocks, start=1):
        example_name = _format_example_name(question, index)
        nodes.append(
            CandidateNode(
                name=example_name,
                node_type="Example",
                local_summary=_format_example_summary(question),
                taxonomy_hint=topic_name,
                parent_entity_name=topic_name,
            )
        )
        edges.append(
            CandidateEdge(
                source_name=example_name,
                target_name=topic_name,
                edge_type="belongs_to_topic",
                description=f"{example_name} belongs to the topic {topic_name}.",
            )
        )

    return ChunkExtractionResult(nodes=nodes, edges=edges)


async def extract_candidates(
    chunk_content: str,
    chunk_title: str,
    header_path: str,
    doc_source_type: str | None = None,
    subject_context: str | None = None,
    prefer_fast_path: bool = False,
) -> ChunkExtractionResult:
    """Extract candidate nodes and edges from one chunk."""

    user_content = populate_prompt(
        USER_PROMPT_KG_EXTRACT,
        chunk_content=chunk_content,
        chunk_title=chunk_title,
        header_path=header_path,
        doc_source_type=doc_source_type or "",
        subject_context=subject_context or "",
    )

    messages: list[ChatMessage] = [
        {"role": SYSTEM, "content": SYSTEM_PROMPT_KG_EXTRACT},
        {"role": USER, "content": user_content},
    ]

    question_fallback = _build_question_fallback(
        chunk_content=chunk_content,
        chunk_title=chunk_title,
        header_path=header_path,
    )
    topic_fallback = _build_topic_fallback(
        chunk_content=chunk_content,
        chunk_title=chunk_title,
        header_path=header_path,
    )

    used_question_fallback = False
    used_topic_fallback = False

    if prefer_fast_path and question_fallback is not None:
        logger.info(
            "kg_extract_fast_path_used",
            chunk_title=chunk_title,
            header_path=header_path,
            question_count=len(question_fallback.nodes) - 1,
        )
        return question_fallback

    try:
        result = await acompletion_structured(
            response_model=ChunkExtractionResult,
            messages=messages,
            task_type=TaskType.EXTRACT,
        )
    except Exception:
        if question_fallback is not None:
            logger.warning(
                "kg_extract_question_fallback_after_error",
                chunk_title=chunk_title,
                header_path=header_path,
                question_count=len(question_fallback.nodes) - 1,
                exc_info=True,
            )
            result = question_fallback
            used_question_fallback = True
        else:
            logger.warning(
                "kg_extract_topic_fallback_after_error",
                chunk_title=chunk_title,
                header_path=header_path,
                exc_info=True,
            )
            result = topic_fallback
            used_topic_fallback = True
    else:
        if not result.nodes and not result.edges:
            if question_fallback is not None:
                logger.warning(
                    "kg_extract_question_fallback_after_empty_result",
                    chunk_title=chunk_title,
                    header_path=header_path,
                    question_count=len(question_fallback.nodes) - 1,
                )
                result = question_fallback
                used_question_fallback = True
            else:
                logger.warning(
                    "kg_extract_topic_fallback_after_empty_result",
                    chunk_title=chunk_title,
                    header_path=header_path,
                )
                result = topic_fallback
                used_topic_fallback = True

    logger.info(
        "kg_extract_complete",
        chunk_title=chunk_title,
        header_path=header_path,
        node_count=len(result.nodes),
        edge_count=len(result.edges),
        used_question_fallback=used_question_fallback,
        used_topic_fallback=used_topic_fallback,
        question_like_chunk=_looks_like_question_chunk(chunk_content),
    )
    return result


__all__ = [
    "CandidateEdge",
    "CandidateNode",
    "ChunkExtractionResult",
    "extract_candidates",
]
