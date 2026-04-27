"""Candidate extraction for knowledge-doc graph synchronization."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import re
from typing import Literal
from time import perf_counter

from pydantic import BaseModel, Field
import structlog

from app.shared.infra.llm_support import acompletion_structured
from app.shared.infra.prompt_loader import populate_prompt
from app.schemas.llm import ChatMessage, SYSTEM, USER
from app.workflows.digest.kg_doc_sync.lib.model_policy import (
    KGDocSyncModelStep,
    kg_doc_sync_completion_kwargs_with_metadata,
)
from app.workflows.digest.kg_doc_sync.lib.ontology import relation_endpoint_type_preferences
from app.workflows.digest.kg_doc_sync.lib.candidate_identity import build_candidate_stable_id
from app.workflows.digest.kg_doc_sync.lib.question_blocks import parse_question_blocks
from app.models.knowledge_taxonomy import (
    normalize_knowledge_unit_type,
    normalize_relation_type,
    normalize_type_source,
    validate_relation_direction,
)
from app.workflows.digest.kg_doc_sync.prompts.section_graph import (
    SYSTEM_PROMPT_KNOWLEDGE_EXTRACT,
    USER_PROMPT_KNOWLEDGE_EXTRACT,
)
from app.workflows.digest.common.semantic_titles import (
    choose_semantic_topic_path,
    clean_semantic_title,
    is_generic_semantic_title,
    normalize_semantic_whitespace,
)
from app.workflows.digest.common.markdown_knowledge_anchors import extract_markdown_knowledge_units

logger = structlog.get_logger()

_MARKDOWN_DECORATION_RE = re.compile(r"[#*_`>]+")
_MULTISPACE_RE = re.compile(r"\s+")
_DOCS_SYNC_SECTION_LLM_TIMEOUT_S = 40
_DOCS_SYNC_SECTION_LLM_MAX_CONTENT_CHARS = 9000
_DOCS_SYNC_SUBJECT_CONTEXT_MAX_CHARS = 1600

# 概念性内容检测
_CONCEPTUAL_SIGNAL_RE = re.compile(
    r"(?:定义|定理|性质|引理|推论|公理|命题|概念|原理|法则|公式)",
)
_INDEPENDENT_FORMULA_RE = re.compile(r"\$\$[^$]+\$\$", re.DOTALL)
_DOCS_TYPED_LINE_RE = re.compile(
    r"^\s*(?:[-*]\s*)?(?:\*\*)?"
    r"(?P<label>定义|定理|公式|例题|示例|练习|证明|备注|Definition|Theorem|Formula|Example|Exercise|Proof|Remark)"
    r"(?:\*\*)?\s*[:：]\s*(?P<value>.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_DOCS_SUMMARY_SENTENCE_RE = re.compile(r"(?P<sentence>[^。！？.!?]{0,80}(?:是|指|表示|意味着|可理解为|定义为)[^。！？.!?]{4,120}[。！？.!?])")
_DOCS_RETRY_SIGNAL_RE = re.compile(
    r"(?:定义|定理|公式|性质|法则|原理|几何意义|物理意义|判定|判别|方法|步骤|证明|推论|注意|易错|Remark|Definition|Theorem|Formula|Example|Proof)",
    re.IGNORECASE,
)


class CandidateNode(BaseModel):
    """A candidate knowledge node extracted from a chunk."""

    candidate_id: str = Field(default="", description="内部稳定候选 ID。")
    anchor_id: str = Field(default="", description="Markdown 中已有的 KnowledgeUnit anchor ID。")
    name: str = Field(description="知识单元名称，要求短、准、可展示。")
    knowledge_unit_type: Literal[
        "concept",
        "definition",
        "theorem",
        "formula",
        "example",
        "exercise",
        "method",
        "proof_step",
        "remark",
    ] = Field(
        description="允许的节点类型，必须使用枚举值本身。"
    )
    type_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    type_source: Literal["rule", "llm", "manual"] = Field(default="llm")
    local_summary: str = Field(description="只基于当前片段的简短摘要。")
    taxonomy_hint: str = Field(default="", description="可能的上位主题或分类线索。")
    parent_entity_name: str | None = Field(
        default=None,
        description="定义、公式、例题等节点所属的父概念、方法或主题。",
    )


class CandidateEdge(BaseModel):
    """A candidate edge extracted from a chunk."""

    source_name: str = Field(description="源节点名称，必须匹配本次返回的某个节点名称。")
    target_name: str = Field(description="目标节点名称，必须匹配本次返回的某个节点名称。")
    source_candidate_id: str | None = Field(default=None, description="源节点候选 ID；不确定时可留空。")
    target_candidate_id: str | None = Field(default=None, description="目标节点候选 ID；不确定时可留空。")
    source_node_type: str | None = Field(default=None, description="源节点类型；不确定时可留空。")
    target_node_type: str | None = Field(default=None, description="目标节点类型；不确定时可留空。")
    edge_type: Literal[
        "prerequisite",
        "derivation",
        "application",
        "example_of",
        "similar",
        "contrast",
    ] = Field(description="允许的关系类型，必须使用枚举值本身。")
    description: str = Field(description="一句话说明这条关系在当前片段中的依据。")


class ChunkExtractionResult(BaseModel):
    """Structured extraction result for a single chunk."""

    nodes: list[CandidateNode] = Field(default_factory=list)
    edges: list[CandidateEdge] = Field(default_factory=list)


@dataclass(slots=True)
class CandidateExtractionDiagnostics:
    """Lightweight runtime diagnostics for one candidate-extraction pass."""

    llm_attempted: bool = False
    markdown_anchor_short_circuit_used: bool = False
    question_like_chunk: bool = False
    llm_error_count: int = 0
    empty_llm_result_count: int = 0
    empty_repair_attempt_count: int = 0
    empty_repair_success_count: int = 0
    elapsed_ms: int = 0
    node_count: int = 0
    edge_count: int = 0


def docs_section_llm_timeout_s() -> int:
    return _DOCS_SYNC_SECTION_LLM_TIMEOUT_S


def docs_section_llm_max_content_chars() -> int:
    return _DOCS_SYNC_SECTION_LLM_MAX_CONTENT_CHARS


def _normalize_text(text: str) -> str:
    text = _MARKDOWN_DECORATION_RE.sub(" ", text)
    text = normalize_semantic_whitespace(text)
    return _MULTISPACE_RE.sub(" ", text).strip()


def _limit_llm_text(text: str, *, max_chars: int) -> str:
    cleaned = str(text or "").strip()
    if len(cleaned) <= max_chars:
        return cleaned
    head_chars = max_chars * 2 // 3
    tail_chars = max(0, max_chars - head_chars - 36)
    return (
        cleaned[:head_chars].rstrip()
        + "\n\n...[中间内容已压缩，保留开头和结尾]...\n\n"
        + cleaned[-tail_chars:].lstrip()
    )


def _prepare_llm_chunk_content(chunk_content: str) -> str:
    return _limit_llm_text(
        chunk_content,
        max_chars=_DOCS_SYNC_SECTION_LLM_MAX_CONTENT_CHARS,
    )


def _prepare_llm_subject_context(subject_context: str | None) -> str:
    return _limit_llm_text(
        subject_context or "",
        max_chars=_DOCS_SYNC_SUBJECT_CONTEXT_MAX_CHARS,
    )


def has_conceptual_content(content: str) -> bool:
    """检测文本是否包含概念性内容（定义/定理/公式块等）。

    用于 fast_path 判断：包含概念性内容的 chunk 不应走 fast_path。
    """
    # 包含多处明确知识信号
    if len(_CONCEPTUAL_SIGNAL_RE.findall(content)) >= 2:
        return True
    # 包含独立公式块
    if len(_INDEPENDENT_FORMULA_RE.findall(content)) >= 2:
        return True
    # 非题目文本占比检测：去掉题目块后剩余文本占比 > 30%
    question_blocks = parse_question_blocks(content)
    if question_blocks:
        question_chars = sum(len(q.content) for q in question_blocks)
        total_chars = len(content)
        if total_chars > 0 and (total_chars - question_chars) / total_chars > 0.3:
            return True
    return False


def _clean_topic_name(chunk_title: str, header_path: str) -> str:
    topic_path = choose_semantic_topic_path(
        header_path=header_path,
        fallback_title=chunk_title,
    )
    return topic_path[-1] if topic_path else "学习材料"


def _looks_like_question_chunk(chunk_content: str) -> bool:
    return len(parse_question_blocks(chunk_content)) >= 2


async def _repair_docs_extraction_after_empty(
    *,
    messages: list[ChatMessage],
    chunk_title: str,
    header_path: str,
) -> ChunkExtractionResult:
    repair_messages = list(messages)
    repair_messages.append(
        {
            "role": USER,
            "content": (
                "上一次抽取结果为空。请重新阅读片段：如果其中包含任何概念、定义、公式、方法、例题、"
                "定理、证明步骤或注意事项，请返回非空图谱。若标题本身是一个真实主题，至少包含该主概念。"
            ),
        }
    )
    return await acompletion_structured(
        response_model=ChunkExtractionResult,
        messages=repair_messages,
        **kg_doc_sync_completion_kwargs_with_metadata(
            KGDocSyncModelStep.EMPTY_REPAIR,
            chunk_title=chunk_title,
            header_path=header_path,
        ),
    )


def _should_retry_docs_extraction_after_empty(
    *,
    chunk_content: str,
    chunk_title: str,
) -> bool:
    normalized_title = _normalize_text(chunk_title)
    if _DOCS_TYPED_LINE_RE.search(chunk_content):
        return True
    if _DOCS_SUMMARY_SENTENCE_RE.search(chunk_content):
        return True
    if _DOCS_RETRY_SIGNAL_RE.search(chunk_content) or _DOCS_RETRY_SIGNAL_RE.search(normalized_title):
        return True
    return False


def _finalize_candidate_result(
    result: ChunkExtractionResult,
    *,
    chunk_title: str,
    header_path: str,
    chapter_topic_hints: list[str] | None,
    subject_context: str | None,
    question_mode: bool,
) -> ChunkExtractionResult:
    result = _sanitize_candidate_graph(
        result,
        chunk_title=chunk_title,
        header_path=header_path,
        chapter_topic_hints=chapter_topic_hints,
        subject_context=subject_context,
        question_mode=question_mode,
    )
    return _assign_candidate_ids_and_edge_types(result)


def _sanitize_candidate_graph(
    result: ChunkExtractionResult,
    *,
    chunk_title: str,
    header_path: str,
    chapter_topic_hints: list[str] | None = None,
    subject_context: str | None = None,
    question_mode: bool = False,
) -> ChunkExtractionResult:
    primary_terms = [
        node.name
        for node in result.nodes
        if normalize_knowledge_unit_type(node.knowledge_unit_type) in {"concept", "method"}
    ]
    semantic_topic_path = choose_semantic_topic_path(
        header_path=header_path,
        fallback_title=chunk_title,
        chapter_topic_hints=chapter_topic_hints,
        extracted_terms=primary_terms,
        subject_context=subject_context,
        question_mode=question_mode,
    )
    semantic_topic_name = semantic_topic_path[-1] if semantic_topic_path else _clean_topic_name(chunk_title, header_path)

    rename_map: dict[str, str] = {}
    for node in result.nodes:
        original_name = node.name
        original_type = node.knowledge_unit_type
        is_topic_like = str(original_type).strip().lower() == "topic"
        node.knowledge_unit_type = normalize_knowledge_unit_type(node.knowledge_unit_type)
        node.type_source = normalize_type_source(node.type_source)
        node.type_confidence = max(0.0, min(1.0, float(node.type_confidence)))
        if is_topic_like:
            cleaned_name = clean_semantic_title(node.name) or semantic_topic_name
            node.name = cleaned_name
            if not node.taxonomy_hint or is_generic_semantic_title(node.taxonomy_hint):
                if len(semantic_topic_path) >= 2 and cleaned_name == semantic_topic_path[-1]:
                    node.taxonomy_hint = semantic_topic_path[-2]
                else:
                    node.taxonomy_hint = cleaned_name
        else:
            node.name = _normalize_text(node.name)
            if node.knowledge_unit_type in {"concept", "method"} and (
                not node.taxonomy_hint or is_generic_semantic_title(node.taxonomy_hint)
            ):
                node.taxonomy_hint = semantic_topic_name
            if node.knowledge_unit_type in {"definition", "example", "exercise"} and (
                not node.parent_entity_name or is_generic_semantic_title(node.parent_entity_name)
            ):
                node.parent_entity_name = semantic_topic_name
        rename_map[original_name] = node.name

    for node in result.nodes:
        if node.parent_entity_name:
            node.parent_entity_name = rename_map.get(node.parent_entity_name, node.parent_entity_name)
        if node.taxonomy_hint:
            node.taxonomy_hint = rename_map.get(node.taxonomy_hint, node.taxonomy_hint)

    filtered_edges: list[CandidateEdge] = []
    node_type_by_name = {node.name: node.knowledge_unit_type for node in result.nodes}
    for edge in result.edges:
        edge.source_name = rename_map.get(edge.source_name, edge.source_name)
        edge.target_name = rename_map.get(edge.target_name, edge.target_name)
        edge.edge_type = normalize_relation_type(edge.edge_type)
        edge.source_node_type = normalize_knowledge_unit_type(edge.source_node_type or node_type_by_name.get(edge.source_name))
        edge.target_node_type = normalize_knowledge_unit_type(edge.target_node_type or node_type_by_name.get(edge.target_name))
        if validate_relation_direction(
            edge_type=edge.edge_type,
            source_type=edge.source_node_type,
            target_type=edge.target_node_type,
        ):
            filtered_edges.append(edge)
        else:
            logger.warning(
                "knowledge_edge_dropped_invalid_direction",
                edge_type=edge.edge_type,
                source_type=edge.source_node_type,
                target_type=edge.target_node_type,
            )
    result.edges = filtered_edges
    return result


def _assign_candidate_ids_and_edge_types(result: ChunkExtractionResult) -> ChunkExtractionResult:
    for index, node in enumerate(result.nodes, start=1):
        if not node.candidate_id:
            node.candidate_id = build_candidate_stable_id(
                knowledge_unit_type=node.knowledge_unit_type,
                name=node.name,
                local_index=index,
                scope=node.parent_entity_name or node.taxonomy_hint,
            )

    candidates_by_raw_name: dict[str, list[CandidateNode]] = {}
    candidates_by_norm_name: dict[str, list[CandidateNode]] = {}
    for node in result.nodes:
        candidates_by_raw_name.setdefault(node.name, []).append(node)
        normalized = _normalize_text(node.name)
        if normalized:
            candidates_by_norm_name.setdefault(normalized, []).append(node)

    def _select_local_candidate(
        name: str,
        *,
        endpoint_side: Literal["source", "target"],
        edge_type: str,
    ) -> CandidateNode | None:
        raw_matches = candidates_by_raw_name.get(name, [])
        norm_matches = candidates_by_norm_name.get(_normalize_text(name), [])
        matches = raw_matches or norm_matches
        if not matches:
            return None
        expected_types = relation_endpoint_type_preferences(edge_type, endpoint_side)
        for expected_type in expected_types:
            for node in matches:
                if node.knowledge_unit_type == expected_type:
                    return node
        if len(matches) == 1:
            return matches[0]
        return None

    for edge in result.edges:
        source_node = _select_local_candidate(
            edge.source_name,
            endpoint_side="source",
            edge_type=edge.edge_type,
        )
        target_node = _select_local_candidate(
            edge.target_name,
            endpoint_side="target",
            edge_type=edge.edge_type,
        )
        if source_node is not None:
            edge.source_candidate_id = source_node.candidate_id
            edge.source_node_type = source_node.knowledge_unit_type
        if target_node is not None:
            edge.target_candidate_id = target_node.candidate_id
            edge.target_node_type = target_node.knowledge_unit_type
    return result


def _build_markdown_anchor_result(
    *,
    chunk_content: str,
    chunk_title: str,
    header_path: str,
) -> ChunkExtractionResult | None:
    """Build candidates from explicit Markdown KnowledgeUnit anchors."""

    units = extract_markdown_knowledge_units(chunk_content)
    if not units:
        return None

    nodes: list[CandidateNode] = []
    edges: list[CandidateEdge] = []
    known_names: set[str] = set()
    anchor_topic = clean_semantic_title(chunk_title) or clean_semantic_title(header_path) or ""

    def _ensure_concept(name: str) -> None:
        if not name or name in known_names:
            return
        known_names.add(name)
        nodes.append(
            CandidateNode(
                name=name,
                knowledge_unit_type="concept",
                type_source="manual",
                type_confidence=0.9,
                local_summary=f"Markdown 标记引用了概念：{name}。",
                taxonomy_hint=anchor_topic,
            )
        )

    for unit in units:
        if unit.name in known_names:
            continue
        known_names.add(unit.name)
        nodes.append(
            CandidateNode(
                candidate_id=unit.anchor,
                anchor_id=unit.anchor,
                name=unit.name,
                knowledge_unit_type=unit.knowledge_unit_type,
                type_source="manual",
                type_confidence=1.0,
                local_summary=unit.summary or unit.name,
                taxonomy_hint=anchor_topic,
            )
        )

    for unit in units:
        for prerequisite in unit.prerequisites:
            _ensure_concept(prerequisite)
            edges.append(
                CandidateEdge(
                    source_name=prerequisite,
                    target_name=unit.name,
                    edge_type="prerequisite",
                    description=f"{prerequisite} 是学习 {unit.name} 前需要掌握的前置知识。",
                )
            )
        for related in unit.related:
            _ensure_concept(related)
            edges.append(
                CandidateEdge(
                    source_name=unit.name,
                    target_name=related,
                    edge_type="similar",
                    description=f"{unit.name} 与 {related} 存在相关关系。",
                )
            )

    return ChunkExtractionResult(nodes=nodes, edges=edges)


async def _extract_candidates_internal(
    chunk_content: str,
    chunk_title: str,
    header_path: str,
    doc_source_type: str | None = None,
    subject_context: str | None = None,
    prefer_fast_path: bool = False,
    allow_markdown_anchor_short_circuit: bool = True,
    sibling_topics: str = "",
    digest_mode: str = "",
    chapter_topic_hints: list[str] | None = None,
) -> tuple[ChunkExtractionResult, CandidateExtractionDiagnostics]:
    """Extract candidate nodes and edges plus runtime diagnostics for one chunk."""

    started_at = perf_counter()
    diagnostics = CandidateExtractionDiagnostics()

    if allow_markdown_anchor_short_circuit:
        markdown_anchor_result = _build_markdown_anchor_result(
            chunk_content=chunk_content,
            chunk_title=chunk_title,
            header_path=header_path,
        )
        if markdown_anchor_result is not None:
            result = _sanitize_candidate_graph(
                markdown_anchor_result,
                chunk_title=chunk_title,
                header_path=header_path,
                chapter_topic_hints=chapter_topic_hints,
                subject_context=subject_context,
                question_mode=False,
            )
            result = _assign_candidate_ids_and_edge_types(result)
            logger.info(
                "knowledge_extract_markdown_anchors_used",
                chunk_title=chunk_title,
                header_path=header_path,
                node_count=len(result.nodes),
                edge_count=len(result.edges),
            )
            diagnostics.markdown_anchor_short_circuit_used = True
            diagnostics.question_like_chunk = False
            diagnostics.node_count = len(result.nodes)
            diagnostics.edge_count = len(result.edges)
            diagnostics.elapsed_ms = int((perf_counter() - started_at) * 1000)
            return result, diagnostics

    llm_chunk_content = _prepare_llm_chunk_content(chunk_content)
    llm_subject_context = _prepare_llm_subject_context(subject_context)
    user_content = populate_prompt(
        USER_PROMPT_KNOWLEDGE_EXTRACT,
        chunk_content=llm_chunk_content,
        chunk_title=chunk_title,
        header_path=header_path,
        doc_source_type=doc_source_type or "",
        subject_context=llm_subject_context,
        sibling_topics=sibling_topics,
        digest_mode=digest_mode,
    )

    messages: list[ChatMessage] = [
        {"role": SYSTEM, "content": SYSTEM_PROMPT_KNOWLEDGE_EXTRACT},
        {"role": USER, "content": user_content},
    ]

    if prefer_fast_path:
        logger.info(
            "knowledge_extract_fast_path_disabled",
            chunk_title=chunk_title,
            header_path=header_path,
            reason="knowledge content must come from structured LLM extraction",
        )

    try:
        diagnostics.llm_attempted = True
        llm_call = acompletion_structured(
            response_model=ChunkExtractionResult,
            messages=messages,
            **kg_doc_sync_completion_kwargs_with_metadata(
                KGDocSyncModelStep.SECTION_GRAPH,
                chunk_title=chunk_title,
                header_path=header_path,
                doc_source_type=doc_source_type,
                digest_mode=digest_mode,
                chunk_chars=len(chunk_content),
                llm_chunk_chars=len(llm_chunk_content),
                subject_context_chars=len(subject_context or ""),
                llm_subject_context_chars=len(llm_subject_context),
                section_timeout_s=_DOCS_SYNC_SECTION_LLM_TIMEOUT_S,
            ),
        )
        if doc_source_type == "knowledge_doc_markdown":
            result = await asyncio.wait_for(llm_call, timeout=_DOCS_SYNC_SECTION_LLM_TIMEOUT_S)
        else:
            result = await llm_call
    except Exception as exc:
        diagnostics.llm_error_count += 1
        logger.warning(
            "knowledge_extract_llm_failed",
            chunk_title=chunk_title,
            header_path=header_path,
            error_type=type(exc).__name__,
        )
        raise
    else:
        if not result.nodes and not result.edges:
            diagnostics.empty_llm_result_count += 1
            if doc_source_type == "knowledge_doc_markdown" and _should_retry_docs_extraction_after_empty(
                chunk_content=chunk_content,
                chunk_title=chunk_title,
            ):
                try:
                    diagnostics.empty_repair_attempt_count += 1
                    result = await _repair_docs_extraction_after_empty(
                        messages=messages,
                        chunk_title=chunk_title,
                        header_path=header_path,
                    )
                    if result.nodes or result.edges:
                        diagnostics.empty_repair_success_count += 1
                except Exception as exc:
                    diagnostics.llm_error_count += 1
                    logger.warning(
                        "knowledge_extract_docs_retry_failed",
                        chunk_title=chunk_title,
                        header_path=header_path,
                        error_type=type(exc).__name__,
                    )

    result = _finalize_candidate_result(
        result,
        chunk_title=chunk_title,
        header_path=header_path,
        chapter_topic_hints=chapter_topic_hints,
        subject_context=subject_context,
        question_mode=_looks_like_question_chunk(chunk_content),
    )

    logger.info(
        "knowledge_extract_complete",
        chunk_title=chunk_title,
        header_path=header_path,
        node_count=len(result.nodes),
        edge_count=len(result.edges),
        question_like_chunk=_looks_like_question_chunk(chunk_content),
    )
    diagnostics.question_like_chunk = _looks_like_question_chunk(chunk_content)
    diagnostics.node_count = len(result.nodes)
    diagnostics.edge_count = len(result.edges)
    diagnostics.elapsed_ms = int((perf_counter() - started_at) * 1000)
    return result, diagnostics


async def extract_candidates(
    chunk_content: str,
    chunk_title: str,
    header_path: str,
    doc_source_type: str | None = None,
    subject_context: str | None = None,
    prefer_fast_path: bool = False,
    allow_markdown_anchor_short_circuit: bool = True,
    sibling_topics: str = "",
    digest_mode: str = "",
    chapter_topic_hints: list[str] | None = None,
) -> ChunkExtractionResult:
    """Extract candidate nodes and edges from one chunk."""

    result, _diagnostics = await _extract_candidates_internal(
        chunk_content=chunk_content,
        chunk_title=chunk_title,
        header_path=header_path,
        doc_source_type=doc_source_type,
        subject_context=subject_context,
        prefer_fast_path=prefer_fast_path,
        allow_markdown_anchor_short_circuit=allow_markdown_anchor_short_circuit,
        sibling_topics=sibling_topics,
        digest_mode=digest_mode,
        chapter_topic_hints=chapter_topic_hints,
    )
    return result


async def extract_candidates_with_diagnostics(
    chunk_content: str,
    chunk_title: str,
    header_path: str,
    doc_source_type: str | None = None,
    subject_context: str | None = None,
    prefer_fast_path: bool = False,
    allow_markdown_anchor_short_circuit: bool = True,
    sibling_topics: str = "",
    digest_mode: str = "",
    chapter_topic_hints: list[str] | None = None,
) -> tuple[ChunkExtractionResult, CandidateExtractionDiagnostics]:
    """Extract candidates together with lightweight runtime diagnostics."""

    return await _extract_candidates_internal(
        chunk_content=chunk_content,
        chunk_title=chunk_title,
        header_path=header_path,
        doc_source_type=doc_source_type,
        subject_context=subject_context,
        prefer_fast_path=prefer_fast_path,
        allow_markdown_anchor_short_circuit=allow_markdown_anchor_short_circuit,
        sibling_topics=sibling_topics,
        digest_mode=digest_mode,
        chapter_topic_hints=chapter_topic_hints,
    )


__all__ = [
    "CandidateExtractionDiagnostics",
    "CandidateEdge",
    "CandidateNode",
    "ChunkExtractionResult",
    "docs_section_llm_max_content_chars",
    "docs_section_llm_timeout_s",
    "extract_candidates",
    "extract_candidates_with_diagnostics",
    "has_conceptual_content",
]
