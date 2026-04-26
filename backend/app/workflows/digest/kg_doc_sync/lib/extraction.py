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
from app.workflows.digest.kg_doc_sync.lib.candidate_identity import build_candidate_stable_id
from app.workflows.digest.kg_doc_sync.lib.chunker import QuestionBlock, parse_question_blocks
from app.models.knowledge_taxonomy import (
    normalize_knowledge_unit_type,
    normalize_relation_type,
    normalize_type_source,
    validate_relation_direction,
)
from app.utils.knowledge_helpers import normalize_name
from app.workflows.digest.kg_doc_sync.prompts.extraction import (
    SYSTEM_PROMPT_KNOWLEDGE_EXTRACT,
    USER_PROMPT_KNOWLEDGE_EXTRACT,
)
from app.workflows.digest.common.semantic_titles import (
    DEFAULT_QUESTION_TOPIC,
    choose_semantic_topic_path,
    clean_semantic_title,
    is_generic_semantic_title,
    normalize_semantic_whitespace,
)
from app.workflows.digest.common.markdown_knowledge_anchors import extract_markdown_knowledge_units

logger = structlog.get_logger()

_QUESTION_RANGE_SUFFIX_RE = re.compile(r"\s*/\s*(?:Question|Questions)\s+\d+(?:-\d+)?$", re.IGNORECASE)
_MARKDOWN_DECORATION_RE = re.compile(r"[#*_`>]+")
_MULTISPACE_RE = re.compile(r"\s+")
_MAX_EXAMPLE_NAME_CHARS = 48
_MAX_EXAMPLE_SUMMARY_CHARS = 800
_MAX_TOPIC_SUMMARY_CHARS = 240
_DOCS_SYNC_SECTION_LLM_TIMEOUT_S = 25

# ── 知识点提取相关模式 ──────────────────────────────────────────
# 中文学科概念词（2-8字，排除常见停用词）
_CN_CONCEPT_RE = re.compile(
    r"(?:(?:求|计算|证明|判断|讨论|利用|根据|由|用|关于|已知)\s*)"
    r"([\u4e00-\u9fff]{2,8}(?:的[\u4e00-\u9fff]{2,6})?)",
)
# 常见学科方法/定理/公式名称
_METHOD_KEYWORDS_RE = re.compile(
    r"([\u4e00-\u9fff]{2,6}(?:法|定理|公式|定律|原理|准则|方程|变换|分解|展开|判别|不等式))",
)
# LaTeX 中的函数名
_LATEX_FUNC_RE = re.compile(
    r"\\(?:sin|cos|tan|cot|sec|csc|ln|log|lim|int|sum|prod|det|max|min|sup|inf|arg|exp|sqrt)\b",
)
# 概念性内容检测
_CONCEPTUAL_KEYWORDS_RE = re.compile(
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
_DOCS_EXPLANATION_CUE_RE = re.compile(r"(?:几何意义|物理意义|性质|应用|图像|判定|判别|方法|步骤|注意|易错|拓展)")
_DOCS_LABEL_TYPE_MAP = {
    "定义": "definition",
    "definition": "definition",
    "定理": "theorem",
    "theorem": "theorem",
    "公式": "formula",
    "formula": "formula",
    "例题": "example",
    "示例": "example",
    "example": "example",
    "练习": "exercise",
    "exercise": "exercise",
    "证明": "proof_step",
    "proof": "proof_step",
    "备注": "remark",
    "remark": "remark",
}
_DOCS_RETRY_SIGNAL_RE = re.compile(
    r"(?:定义|定理|公式|性质|法则|原理|几何意义|物理意义|判定|判别|方法|步骤|证明|推论|注意|易错|Remark|Definition|Theorem|Formula|Example|Proof)",
    re.IGNORECASE,
)
_DOCS_RELATIVE_TITLE_TYPE_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?:定义|definition)", re.IGNORECASE), "definition"),
    (re.compile(r"(?:定理|性质|引理|推论|theorem|lemma|proposition|property)", re.IGNORECASE), "theorem"),
    (re.compile(r"(?:公式|方程|恒等式|formula|equation|identity)", re.IGNORECASE), "formula"),
    (re.compile(r"(?:例题|示例|example|case)", re.IGNORECASE), "example"),
    (re.compile(r"(?:练习|习题|exercise|problem)", re.IGNORECASE), "exercise"),
    (re.compile(r"(?:证明|推导|proof|derivation)", re.IGNORECASE), "proof_step"),
    (re.compile(r"(?:方法|步骤|策略|algorithm|method|procedure|step)", re.IGNORECASE), "method"),
    (re.compile(r"(?:几何意义|物理意义|应用|注意|易错|备注|说明|remark|note|intuition|interpretation)", re.IGNORECASE), "remark"),
)
# 停用词：过于宽泛不适合作为知识点
_CONCEPT_STOPWORDS = frozenset({
    "选择题", "填空题", "解答题", "判断题", "计算题", "证明题", "简答题",
    "论述题", "应用题", "综合题", "大题", "小题", "本题", "下列",
    "以下", "其中", "所有", "任意", "存在", "满足", "条件",
    "正确", "错误", "答案", "解析", "分析", "结果", "过程",
})

# LLM 轻量概念提取 prompt
_SYSTEM_PROMPT_CONCEPT_EXTRACT = """
你是一名知识点识别助手。请从以下题目内容中提取背后考查的核心知识点。

## 输出要求
- 每个知识点用一个简短名称表示（2-8个字）
- 标注类型：`concept`（概念）或 `method`（方法/技巧）
- 只提取学科通用知识点，不提取题目专属设定
- 最多返回 8 个知识点
""".strip()

_USER_PROMPT_CONCEPT_EXTRACT = """
## 题目内容

{{ questions_text }}

请提取这些题目背后考查的核心知识点。
""".strip()


class _ConceptItem(BaseModel):
    name: str = Field(description="知识点名称")
    knowledge_unit_type: Literal["concept", "method"] = Field(description="标准节点类型")


class _ConceptExtractResult(BaseModel):
    """LLM 轻量概念提取结果。"""

    concepts: list[_ConceptItem] = Field(default_factory=list)


class CandidateNode(BaseModel):
    """A candidate knowledge node extracted from a chunk."""

    candidate_id: str = Field(default="", description="Internal stable candidate id.")
    anchor_id: str = Field(default="", description="Markdown-carried KnowledgeUnit anchor id.")
    name: str = Field(description="KnowledgeUnit name.")
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
        description="Allowed node type."
    )
    type_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    type_source: Literal["rule", "llm", "manual"] = Field(default="llm")
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
    source_candidate_id: str | None = Field(default=None, description="Resolved source candidate id.")
    target_candidate_id: str | None = Field(default=None, description="Resolved target candidate id.")
    source_node_type: str | None = Field(default=None, description="Resolved source node type.")
    target_node_type: str | None = Field(default=None, description="Resolved target node type.")
    edge_type: Literal[
        "prerequisite",
        "derivation",
        "application",
        "example_of",
        "similar",
        "contrast",
    ] = Field(description="Allowed edge type.")
    description: str = Field(description="Short relation description.")


class ChunkExtractionResult(BaseModel):
    """Structured extraction result for a single chunk."""

    nodes: list[CandidateNode] = Field(default_factory=list)
    edges: list[CandidateEdge] = Field(default_factory=list)


@dataclass(slots=True)
class CandidateExtractionDiagnostics:
    """Lightweight runtime diagnostics for one candidate-extraction pass."""

    llm_attempted: bool = False
    used_question_fallback: bool = False
    used_topic_fallback: bool = False
    markdown_anchor_short_circuit_used: bool = False
    question_like_chunk: bool = False
    elapsed_ms: int = 0
    node_count: int = 0
    edge_count: int = 0


def _normalize_text(text: str) -> str:
    text = _MARKDOWN_DECORATION_RE.sub(" ", text)
    text = normalize_semantic_whitespace(text)
    return _MULTISPACE_RE.sub(" ", text).strip()


# ── 知识点提取函数 ──────────────────────────────────────────────

def _extract_concept_keywords_from_questions(
    questions: list[QuestionBlock],
) -> list[tuple[str, str]]:
    """从题目中用规则提取学科概念关键词。

    Returns:
        ``(keyword, knowledge_unit_type)`` 对列表，knowledge_unit_type 为 ``"concept"`` 或 ``"method"``。
    """
    seen: set[str] = set()
    results: list[tuple[str, str]] = []

    for q in questions:
        text = _normalize_text(q.stem + " " + q.content)

        # 方法/定理/公式名称优先（更精确）
        for match in _METHOD_KEYWORDS_RE.finditer(text):
            term = match.group(1).strip()
            if term not in seen and term not in _CONCEPT_STOPWORDS and len(term) >= 2:
                seen.add(term)
                results.append((term, "method"))

        # 中文学科概念词
        for match in _CN_CONCEPT_RE.finditer(text):
            term = match.group(1).strip()
            if term not in seen and term not in _CONCEPT_STOPWORDS and len(term) >= 2:
                seen.add(term)
                results.append((term, "concept"))

    # LaTeX 函数名 → 对应数学概念
    _LATEX_TO_CONCEPT = {
        "sin": "三角函数", "cos": "三角函数", "tan": "三角函数",
        "cot": "三角函数", "sec": "三角函数", "csc": "三角函数",
        "ln": "对数函数", "log": "对数函数",
        "lim": "极限", "int": "积分", "sum": "级数求和",
        "prod": "连乘积", "det": "行列式",
        "sqrt": "根式运算", "exp": "指数函数",
    }
    all_text = " ".join(_normalize_text(q.content) for q in questions)
    for match in _LATEX_FUNC_RE.finditer(all_text):
        func_name = match.group(0).lstrip("\\")
        concept = _LATEX_TO_CONCEPT.get(func_name)
        if concept and concept not in seen:
            seen.add(concept)
            results.append((concept, "concept"))

    return results[:10]


async def _llm_extract_concepts_from_questions(
    questions: list[QuestionBlock],
) -> list[tuple[str, str]]:
    """当规则提取为空时，用轻量 LLM 从题目中提取知识点。"""
    stems = [_normalize_text(q.stem or q.content)[:200] for q in questions[:8]]
    questions_text = "\n".join(f"- {s}" for s in stems if s)
    if not questions_text:
        return []

    user_content = populate_prompt(
        _USER_PROMPT_CONCEPT_EXTRACT,
        questions_text=questions_text,
    )
    messages: list[ChatMessage] = [
        {"role": SYSTEM, "content": _SYSTEM_PROMPT_CONCEPT_EXTRACT},
        {"role": USER, "content": user_content},
    ]
    try:
        result = await acompletion_structured(
            response_model=_ConceptExtractResult,
            messages=messages,
            **kg_doc_sync_completion_kwargs_with_metadata(
                KGDocSyncModelStep.QUESTION_CONCEPTS,
                question_count=len(questions),
            ),
        )
        return [
            (item.name.strip(), item.knowledge_unit_type)
            for item in result.concepts
            if item.name.strip() and item.name.strip() not in _CONCEPT_STOPWORDS
        ][:8]
    except Exception:
        logger.debug("llm_concept_extract_failed", exc_info=True)
        return []


def _extract_key_terms(content: str) -> list[str]:
    """从文本内容中用规则提取关键术语（用于 topic_fallback 增强）。"""
    text = _normalize_text(content)
    seen: set[str] = set()
    terms: list[str] = []

    # 方法/定理/公式名称
    for match in _METHOD_KEYWORDS_RE.finditer(text):
        term = match.group(1).strip()
        if term not in seen and term not in _CONCEPT_STOPWORDS and len(term) >= 2:
            seen.add(term)
            terms.append(term)

    # "定义"/"定理"/"性质" 后面的名词短语
    for match in re.finditer(r"(?:定义|定理|性质|引理|推论|公式)\s*[：:]\s*([\u4e00-\u9fff]{2,8})", text):
        term = match.group(1).strip()
        if term not in seen and term not in _CONCEPT_STOPWORDS:
            seen.add(term)
            terms.append(term)

    # 中文学科概念词
    for match in _CN_CONCEPT_RE.finditer(text):
        term = match.group(1).strip()
        if term not in seen and term not in _CONCEPT_STOPWORDS and len(term) >= 2:
            seen.add(term)
            terms.append(term)

    return terms[:5]


def has_conceptual_content(content: str) -> bool:
    """检测文本是否包含概念性内容（定义/定理/公式块等）。

    用于 fast_path 判断：包含概念性内容的 chunk 不应走 fast_path。
    """
    # 包含定义/定理/性质等关键词
    if len(_CONCEPTUAL_KEYWORDS_RE.findall(content)) >= 2:
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
    return topic_path[-1] if topic_path else "Study material"


def _truncate(text: str, *, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _format_example_name(question: QuestionBlock, fallback_index: int) -> str:
    num = question.number if question.number is not None else fallback_index
    stem = _truncate(_normalize_text(question.stem), limit=_MAX_EXAMPLE_NAME_CHARS)
    if not stem:
        return f"题{num}"
    return f"题{num}：{stem}"


def _format_example_summary(question: QuestionBlock) -> str:
    return _truncate(_normalize_text(question.content), limit=_MAX_EXAMPLE_SUMMARY_CHARS)


def _looks_like_question_chunk(chunk_content: str) -> bool:
    return len(parse_question_blocks(chunk_content)) >= 2


def _should_prepare_question_fallback(
    *,
    chunk_content: str,
    chunk_title: str,
    doc_source_type: str | None,
) -> bool:
    if not _looks_like_question_chunk(chunk_content):
        return False
    if doc_source_type != "knowledge_doc_markdown":
        return True
    normalized_title = _normalize_text(chunk_title).lower()
    return any(
        token in normalized_title
        for token in ("题", "练习", "例题", "模板", "流程", "策略", "速查", "复盘", "考试须知")
    )


def _split_header_path(header_path: str, chunk_title: str) -> list[str]:
    return choose_semantic_topic_path(
        header_path=header_path,
        fallback_title=chunk_title,
    )


def _hint_edge_type_for_node(node_type: str) -> Literal["derivation", "example_of", "application"]:
    normalized = normalize_knowledge_unit_type(node_type)
    if normalized in {"example", "exercise"}:
        return "example_of"
    if normalized in {"remark"}:
        return "application"
    return "derivation"


def _merge_candidate_results(
    primary: ChunkExtractionResult,
    supplement: ChunkExtractionResult | None,
) -> ChunkExtractionResult:
    if supplement is None:
        return primary

    merged = ChunkExtractionResult(
        nodes=list(primary.nodes),
        edges=list(primary.edges),
    )
    seen_nodes = {
        (_normalize_text(node.name), normalize_knowledge_unit_type(node.knowledge_unit_type))
        for node in merged.nodes
    }
    for node in supplement.nodes:
        key = (_normalize_text(node.name), normalize_knowledge_unit_type(node.knowledge_unit_type))
        if key in seen_nodes:
            continue
        seen_nodes.add(key)
        merged.nodes.append(node)

    seen_edges = {
        (
            _normalize_text(edge.source_name),
            _normalize_text(edge.target_name),
            normalize_relation_type(edge.edge_type),
        )
        for edge in merged.edges
    }
    for edge in supplement.edges:
        key = (
            _normalize_text(edge.source_name),
            _normalize_text(edge.target_name),
            normalize_relation_type(edge.edge_type),
        )
        if key in seen_edges:
            continue
        seen_edges.add(key)
        merged.edges.append(edge)
    return merged


def _build_docs_section_support_result(
    *,
    chunk_content: str,
    chunk_title: str,
    header_path: str,
    chapter_topic_hints: list[str] | None = None,
    subject_context: str | None = None,
) -> ChunkExtractionResult:
    support = ChunkExtractionResult(nodes=[], edges=[])
    topic_path = choose_semantic_topic_path(
        header_path=header_path,
        fallback_title=chunk_title,
        chapter_topic_hints=chapter_topic_hints,
        extracted_terms=_extract_key_terms(chunk_content),
        subject_context=subject_context,
    )
    leaf_name = _qualify_docs_unit_name(
        chunk_title=chunk_title,
        header_path=header_path,
        topic_path=topic_path,
    )
    existing_names = {node.name for node in support.nodes}
    typed_line_count = len(list(_DOCS_TYPED_LINE_RE.finditer(chunk_content)))

    def _append_node(name: str, node_type: str, summary: str) -> None:
        cleaned_name = _normalize_text(name)
        if not cleaned_name or cleaned_name in existing_names:
            return
        existing_names.add(cleaned_name)
        support.nodes.append(
            CandidateNode(
                name=cleaned_name,
                knowledge_unit_type=node_type,
                local_summary=_truncate(_normalize_text(summary), limit=_MAX_EXAMPLE_SUMMARY_CHARS) or cleaned_name,
                taxonomy_hint=leaf_name,
                parent_entity_name=(leaf_name if normalize_knowledge_unit_type(node_type) not in {"concept", "method"} else None),
            )
        )
        if cleaned_name != leaf_name:
            support.edges.append(
                CandidateEdge(
                    source_name=cleaned_name,
                    target_name=leaf_name,
                    edge_type=_hint_edge_type_for_node(node_type),
                    description=f"{cleaned_name} is grounded in section {leaf_name}.",
                )
            )

    primary_type = _infer_docs_primary_node_type(chunk_title=chunk_title, chunk_content=chunk_content)
    if leaf_name and (typed_line_count == 0 or primary_type == "concept"):
        _append_node(leaf_name, primary_type, chunk_content or chunk_title)

    for match in _DOCS_TYPED_LINE_RE.finditer(chunk_content):
        label = (match.group("label") or "").strip().lower()
        node_type = _DOCS_LABEL_TYPE_MAP.get(label)
        value = _normalize_text(match.group("value") or "")
        if not node_type or not value:
            continue
        unit_name = value[:64]
        if (
            node_type in {"definition", "formula", "theorem"}
            and leaf_name
            and (
                leaf_name not in value
                or len(value) > 18
                or bool(re.search(r"[。！？.!?=\s]", value))
            )
        ):
            unit_name = f"{leaf_name}{match.group('label')}"
        _append_node(unit_name, node_type, value)

    summary_match = _DOCS_SUMMARY_SENTENCE_RE.search(chunk_content)
    if (
        summary_match is not None
        and leaf_name
        and f"{leaf_name}定义" not in existing_names
        and typed_line_count == 0
        and primary_type == "concept"
    ):
        sentence = _normalize_text(summary_match.group("sentence") or "")
        if sentence:
            _append_node(f"{leaf_name}定义", "definition", sentence)

    return support


def _infer_docs_primary_node_type(*, chunk_title: str, chunk_content: str) -> str:
    for pattern, node_type in _DOCS_RELATIVE_TITLE_TYPE_RULES:
        if pattern.search(chunk_title):
            return node_type
    if _INDEPENDENT_FORMULA_RE.search(chunk_content):
        return "formula"
    return "concept"


def _qualify_docs_unit_name(
    *,
    chunk_title: str,
    header_path: str,
    topic_path: list[str] | None = None,
) -> str:
    cleaned_title = clean_semantic_title(chunk_title) or _normalize_text(chunk_title)
    if not cleaned_title:
        return ""
    parts = [part.strip() for part in (topic_path or _split_header_path(header_path, chunk_title)) if part.strip()]
    if len(parts) < 2:
        return cleaned_title

    parent_name = parts[-2]
    for pattern, _node_type in _DOCS_RELATIVE_TITLE_TYPE_RULES:
        if pattern.search(cleaned_title):
            if re.search(r"[\u4e00-\u9fff]", cleaned_title):
                return f"{parent_name}的{cleaned_title}"
            return f"{parent_name} {cleaned_title}"

    if normalize_name(cleaned_title) == normalize_name(parent_name):
        return parent_name
    return cleaned_title


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
                "The previous extraction was empty. Re-read the chunk and return a non-empty graph if the "
                "section contains any concept, definition, formula, method, example, theorem, proof step, or note. "
                "At minimum, include the main concept named by the heading when it is a real topic."
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
    key_terms = _extract_key_terms(chunk_content)
    return len(key_terms) >= 2


def _fallback_question_support_name(
    *,
    digest_mode: str,
    leaf_topic_name: str,
) -> tuple[str, Literal["concept", "method"]]:
    normalized_leaf = clean_semantic_title(leaf_topic_name)
    if normalized_leaf and normalized_leaf != DEFAULT_QUESTION_TOPIC:
        if digest_mode == "sprint":
            return f"{normalized_leaf}速解方法", "method"
        return f"{normalized_leaf}综合应用", "concept"
    if digest_mode == "sprint":
        return "速解方法与题型归纳", "method"
    return "综合应用与典型题型", "concept"


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
    fallback_topic_path = choose_semantic_topic_path(
        header_path=header_path,
        fallback_title=chunk_title,
        chapter_topic_hints=chapter_topic_hints,
        extracted_terms=primary_terms,
        subject_context=subject_context,
        question_mode=question_mode,
    )
    fallback_topic_name = fallback_topic_path[-1] if fallback_topic_path else _clean_topic_name(chunk_title, header_path)

    rename_map: dict[str, str] = {}
    for node in result.nodes:
        original_name = node.name
        original_type = node.knowledge_unit_type
        is_topic_like = str(original_type).strip().lower() == "topic"
        node.knowledge_unit_type = normalize_knowledge_unit_type(node.knowledge_unit_type)
        node.type_source = normalize_type_source(node.type_source)
        node.type_confidence = max(0.0, min(1.0, float(node.type_confidence)))
        if is_topic_like:
            cleaned_name = clean_semantic_title(node.name) or fallback_topic_name
            node.name = cleaned_name
            if not node.taxonomy_hint or is_generic_semantic_title(node.taxonomy_hint):
                if len(fallback_topic_path) >= 2 and cleaned_name == fallback_topic_path[-1]:
                    node.taxonomy_hint = fallback_topic_path[-2]
                else:
                    node.taxonomy_hint = cleaned_name
        else:
            node.name = _normalize_text(node.name)
            if node.knowledge_unit_type in {"concept", "method"} and (
                not node.taxonomy_hint or is_generic_semantic_title(node.taxonomy_hint)
            ):
                node.taxonomy_hint = fallback_topic_name
            if node.knowledge_unit_type in {"definition", "example", "exercise"} and (
                not node.parent_entity_name or is_generic_semantic_title(node.parent_entity_name)
            ):
                node.parent_entity_name = fallback_topic_name
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

    expected_types_by_edge = {
        "application": {
            "source": ("concept", "method", "definition", "formula", "theorem", "exercise", "remark"),
            "target": ("concept",),
        },
        "prerequisite": {
            "source": ("concept", "method", "definition", "theorem", "formula", "exercise", "proof_step", "remark"),
            "target": ("concept", "method", "definition", "theorem", "formula", "exercise", "proof_step", "remark"),
        },
        "derivation": {
            "source": ("definition", "theorem", "formula", "proof_step", "concept", "method"),
            "target": ("concept", "method", "theorem", "formula", "proof_step"),
        },
        "example_of": {
            "source": ("example", "exercise"),
            "target": ("concept", "method", "theorem", "formula"),
        },
    }

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
        expected_types = expected_types_by_edge.get(edge_type, {}).get(endpoint_side, ())
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


def _build_topic_fallback(
    *,
    chunk_content: str,
    chunk_title: str,
    header_path: str,
    chapter_topic_hints: list[str] | None = None,
    subject_context: str | None = None,
) -> ChunkExtractionResult:
    """Build a multi-level concept hierarchy from the header path.

    Also extracts key terms from the content as concept units so that
    downstream clustering and curriculum derivation see richer structure
    beyond just hierarchy shells.
    """
    cleaned_parts = choose_semantic_topic_path(
        header_path=header_path,
        fallback_title=chunk_title,
        chapter_topic_hints=chapter_topic_hints,
        extracted_terms=_extract_key_terms(chunk_content),
        subject_context=subject_context,
    )

    leaf_name = cleaned_parts[-1]
    summary = _truncate(_normalize_text(chunk_content), limit=_MAX_TOPIC_SUMMARY_CHARS)
    if not summary:
        summary = f"知识主题，来源于文档结构：{header_path or chunk_title or leaf_name}。"

    nodes: list[CandidateNode] = []
    edges: list[CandidateEdge] = []

    # Create concept units for each level of the hierarchy.
    for i, part_name in enumerate(cleaned_parts):
        is_leaf = i == len(cleaned_parts) - 1
        parent_name = cleaned_parts[i - 1] if i > 0 else None
        nodes.append(
            CandidateNode(
                name=part_name,
                knowledge_unit_type="concept",
                local_summary=summary if is_leaf else f"上层主题：{part_name}。",
                taxonomy_hint=parent_name or part_name,
                parent_entity_name=None,
            )
        )
        if parent_name:
            edges.append(
                CandidateEdge(
                    source_name=part_name,
                    target_name=parent_name,
                    edge_type="derivation",
                    description=f"{part_name} 是 {parent_name} 的子主题。",
                )
            )

    # Extract key terms from content as concept units.
    existing_names = {n.name for n in nodes}
    key_terms = _extract_key_terms(chunk_content)
    for term in key_terms:
        if term in existing_names:
            continue
        existing_names.add(term)
        nodes.append(
            CandidateNode(
                name=term,
                knowledge_unit_type="concept",
                local_summary=f"从文本中识别的关键概念：{term}。",
                taxonomy_hint=leaf_name,
                parent_entity_name=None,
            )
        )
        edges.append(
            CandidateEdge(
                source_name=term,
                target_name=leaf_name,
                edge_type="application",
                description=f"{term} 属于主题 {leaf_name}。",
            )
        )

    return ChunkExtractionResult(nodes=nodes, edges=edges)


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
    fallback_topic = clean_semantic_title(chunk_title) or clean_semantic_title(header_path) or ""

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
                local_summary=f"Markdown tag referenced concept: {name}.",
                taxonomy_hint=fallback_topic,
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
                taxonomy_hint=fallback_topic,
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
                    description=f"{prerequisite} is a prerequisite for {unit.name}.",
                )
            )
        for related in unit.related:
            _ensure_concept(related)
            edges.append(
                CandidateEdge(
                    source_name=unit.name,
                    target_name=related,
                    edge_type="similar",
                    description=f"{unit.name} is related to {related}.",
                )
            )

    return ChunkExtractionResult(nodes=nodes, edges=edges)


async def _build_question_fallback(
    *,
    chunk_content: str,
    chunk_title: str,
    header_path: str,
    chapter_topic_hints: list[str] | None = None,
    subject_context: str | None = None,
    digest_mode: str = "",
) -> ChunkExtractionResult | None:
    """Build a structured fallback for question-heavy chunks.

    Creates the full header-path hierarchy, attaches questions as example
    units, and extracts concept/method units from the questions using a
    hybrid strategy (rule-based first, LLM fallback if rules yield nothing).
    """
    question_blocks = parse_question_blocks(chunk_content)
    if len(question_blocks) < 2:
        return None

    nodes: list[CandidateNode] = []
    edges: list[CandidateEdge] = []

    # Extract concept/method units from questions (hybrid: rules -> LLM).
    concept_pairs = _extract_concept_keywords_from_questions(question_blocks)
    if not concept_pairs:
        concept_pairs = await _llm_extract_concepts_from_questions(question_blocks)

    semantic_topic_path = choose_semantic_topic_path(
        header_path=header_path,
        fallback_title=chunk_title,
        chapter_topic_hints=chapter_topic_hints,
        extracted_terms=[name for name, _ in concept_pairs],
        subject_context=subject_context,
        question_mode=True,
    )
    leaf_topic_name = semantic_topic_path[-1]

    # Create concept units for each hierarchy level.
    for index, part_name in enumerate(semantic_topic_path):
        is_leaf = index == len(semantic_topic_path) - 1
        parent_name = semantic_topic_path[index - 1] if index > 0 else None
        nodes.append(
            CandidateNode(
                name=part_name,
                knowledge_unit_type="concept",
                local_summary=(
                    f"题型专题，包含 {len(question_blocks)} 道题目。来源：{header_path or chunk_title}。"
                    if is_leaf
                    else f"上层主题：{part_name}。"
                ),
                taxonomy_hint=parent_name or part_name,
                parent_entity_name=None,
            )
        )
        if parent_name:
            edges.append(
                CandidateEdge(
                    source_name=part_name,
                    target_name=parent_name,
                    edge_type="derivation",
                    description=f"{part_name} 是 {parent_name} 的子主题。",
                )
            )

    existing_names = {n.name for n in nodes}
    concept_names: list[str] = []
    for concept_name, knowledge_unit_type in concept_pairs:
        if concept_name in existing_names:
            continue
        existing_names.add(concept_name)
        concept_names.append(concept_name)
        nodes.append(
            CandidateNode(
                name=concept_name,
                knowledge_unit_type=knowledge_unit_type,
                local_summary=f"从题目中识别的核心知识点：{concept_name}。",
                taxonomy_hint=leaf_topic_name,
                parent_entity_name=None,
            )
        )
        edges.append(
            CandidateEdge(
                source_name=concept_name,
                target_name=leaf_topic_name,
                edge_type="application",
                description=f"{concept_name} 属于主题 {leaf_topic_name}。",
            )
        )

    if not concept_names:
        fallback_support_name, fallback_support_type = _fallback_question_support_name(
            digest_mode=digest_mode,
            leaf_topic_name=leaf_topic_name,
        )
        concept_names.append(fallback_support_name)
        nodes.append(
            CandidateNode(
                name=fallback_support_name,
                knowledge_unit_type=fallback_support_type,
                local_summary="从题目集合中归纳出的题型/方法支点，用于承接典型题与综合应用。",
                taxonomy_hint=leaf_topic_name,
                parent_entity_name=None,
            )
        )
        edges.append(
            CandidateEdge(
                source_name=fallback_support_name,
                target_name=leaf_topic_name,
                edge_type="application",
                description=f"{fallback_support_name} 属于主题 {leaf_topic_name}。",
            )
        )

    # Attach questions to the leaf topic and link to extracted concepts
    for index, question in enumerate(question_blocks, start=1):
        example_name = _format_example_name(question, index)
        nodes.append(
            CandidateNode(
                name=example_name,
                knowledge_unit_type="example",
                local_summary=_format_example_summary(question),
                taxonomy_hint=leaf_topic_name,
                parent_entity_name=concept_names[0],
            )
        )
        # Link example units to relevant concepts.
        stem_lower = _normalize_text(question.stem + " " + question.content).lower()
        matched = False
        for cname in concept_names:
            if cname.lower() in stem_lower or any(
                c in stem_lower for c in cname.lower().split()
            ):
                matched = True
                edges.append(
                    CandidateEdge(
                        source_name=cname,
                        target_name=example_name,
                        edge_type="example_of",
                        description=f"{cname} 由 {example_name} 举例说明。",
                    )
                )
        if not matched:
            edges.append(
                CandidateEdge(
                    source_name=concept_names[0],
                    target_name=example_name,
                    edge_type="example_of",
                    description=f"{concept_names[0]} 由 {example_name} 举例说明。",
                )
            )

    logger.info(
        "knowledge_question_fallback_built",
        chunk_title=chunk_title,
        question_count=len(question_blocks),
        concept_count=len(concept_names),
        concept_names=concept_names[:5],
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

    user_content = populate_prompt(
        USER_PROMPT_KNOWLEDGE_EXTRACT,
        chunk_content=chunk_content,
        chunk_title=chunk_title,
        header_path=header_path,
        doc_source_type=doc_source_type or "",
        subject_context=subject_context or "",
        sibling_topics=sibling_topics,
        digest_mode=digest_mode,
    )

    messages: list[ChatMessage] = [
        {"role": SYSTEM, "content": SYSTEM_PROMPT_KNOWLEDGE_EXTRACT},
        {"role": USER, "content": user_content},
    ]

    question_fallback: ChunkExtractionResult | None = None
    question_fallback_eligible = _should_prepare_question_fallback(
        chunk_content=chunk_content,
        chunk_title=chunk_title,
        doc_source_type=doc_source_type,
    )
    if question_fallback_eligible:
        question_fallback = await _build_question_fallback(
            chunk_content=chunk_content,
            chunk_title=chunk_title,
            header_path=header_path,
            chapter_topic_hints=chapter_topic_hints,
            subject_context=subject_context,
            digest_mode=digest_mode,
        )
    topic_fallback = _build_topic_fallback(
        chunk_content=chunk_content,
        chunk_title=chunk_title,
        header_path=header_path,
        chapter_topic_hints=chapter_topic_hints,
        subject_context=subject_context,
    )
    docs_section_support = (
        _build_docs_section_support_result(
            chunk_content=chunk_content,
            chunk_title=chunk_title,
            header_path=header_path,
            chapter_topic_hints=chapter_topic_hints,
            subject_context=subject_context,
        )
        if doc_source_type == "knowledge_doc_markdown"
        else None
    )

    used_question_fallback = False
    used_topic_fallback = False

    if prefer_fast_path and question_fallback is not None:
        logger.info(
            "knowledge_extract_fast_path_used",
            chunk_title=chunk_title,
            header_path=header_path,
            node_count=len(question_fallback.nodes),
        )
        diagnostics.used_question_fallback = True
        diagnostics.question_like_chunk = True
        diagnostics.node_count = len(question_fallback.nodes)
        diagnostics.edge_count = len(question_fallback.edges)
        diagnostics.elapsed_ms = int((perf_counter() - started_at) * 1000)
        return question_fallback, diagnostics

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
            ),
        )
        if doc_source_type == "knowledge_doc_markdown":
            result = await asyncio.wait_for(llm_call, timeout=_DOCS_SYNC_SECTION_LLM_TIMEOUT_S)
        else:
            result = await llm_call
    except Exception as exc:
        if question_fallback is not None:
            logger.warning(
                "knowledge_extract_question_fallback_after_error",
                chunk_title=chunk_title,
                header_path=header_path,
                node_count=len(question_fallback.nodes),
                error_type=type(exc).__name__,
            )
            result = question_fallback
            used_question_fallback = True
        else:
            logger.warning(
                "knowledge_extract_topic_fallback_after_error",
                chunk_title=chunk_title,
                header_path=header_path,
                error_type=type(exc).__name__,
            )
            result = docs_section_support or topic_fallback
            used_topic_fallback = True
    else:
        if not result.nodes and not result.edges:
            if doc_source_type == "knowledge_doc_markdown" and _should_retry_docs_extraction_after_empty(
                chunk_content=chunk_content,
                chunk_title=chunk_title,
            ):
                try:
                    result = await _repair_docs_extraction_after_empty(
                        messages=messages,
                        chunk_title=chunk_title,
                        header_path=header_path,
                    )
                except Exception as exc:
                    logger.warning(
                        "knowledge_extract_docs_retry_failed",
                        chunk_title=chunk_title,
                        header_path=header_path,
                        error_type=type(exc).__name__,
                    )
            if question_fallback is not None:
                if not result.nodes and not result.edges:
                    logger.warning(
                        "knowledge_extract_question_fallback_after_empty_result",
                        chunk_title=chunk_title,
                        header_path=header_path,
                        node_count=len(question_fallback.nodes),
                    )
                    result = question_fallback
                    used_question_fallback = True
            else:
                if not result.nodes and not result.edges:
                    logger.warning(
                        "knowledge_extract_topic_fallback_after_empty_result",
                        chunk_title=chunk_title,
                        header_path=header_path,
                    )
                    result = docs_section_support or topic_fallback
                    used_topic_fallback = True

    if doc_source_type == "knowledge_doc_markdown":
        concept_like_count = sum(
            1 for node in result.nodes if normalize_knowledge_unit_type(node.knowledge_unit_type) in {"concept", "method"}
        )
        if concept_like_count == 0 or len(result.nodes) <= 1 or (not result.edges and docs_section_support is not None):
            result = _merge_candidate_results(result, docs_section_support)

    result = _sanitize_candidate_graph(
        result,
        chunk_title=chunk_title,
        header_path=header_path,
        chapter_topic_hints=chapter_topic_hints,
        subject_context=subject_context,
        question_mode=question_fallback is not None or _looks_like_question_chunk(chunk_content),
    )
    result = _assign_candidate_ids_and_edge_types(result)

    logger.info(
        "knowledge_extract_complete",
        chunk_title=chunk_title,
        header_path=header_path,
        node_count=len(result.nodes),
        edge_count=len(result.edges),
        used_question_fallback=used_question_fallback,
        used_topic_fallback=used_topic_fallback,
        question_like_chunk=_looks_like_question_chunk(chunk_content),
    )
    diagnostics.used_question_fallback = used_question_fallback
    diagnostics.used_topic_fallback = used_topic_fallback
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
    "extract_candidates",
    "extract_candidates_with_diagnostics",
    "has_conceptual_content",
]
