"""Candidate extraction for digest graph workflow."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field
import structlog

from app.shared.infra.llm_support import acompletion_structured
from app.shared.infra.llm_support.routing import TaskType
from app.shared.infra.prompt_loader import populate_prompt
from app.schemas.llm import ChatMessage, SYSTEM, USER
from app.workflows.digest.knowledge_graph.services.candidate_identity import build_candidate_stable_id
from app.workflows.digest.knowledge_graph.services.chunker import QuestionBlock, parse_question_blocks
from app.workflows.digest.prompts import SYSTEM_PROMPT_KG_EXTRACT, USER_PROMPT_KG_EXTRACT
from app.workflows.digest.shared.semantic_titles import (
    DEFAULT_QUESTION_TOPIC,
    choose_semantic_topic_path,
    clean_semantic_title,
    is_generic_semantic_title,
    normalize_semantic_whitespace,
)

logger = structlog.get_logger()

_QUESTION_RANGE_SUFFIX_RE = re.compile(r"\s*/\s*(?:Question|Questions)\s+\d+(?:-\d+)?$", re.IGNORECASE)
_MARKDOWN_DECORATION_RE = re.compile(r"[#*_`>]+")
_MULTISPACE_RE = re.compile(r"\s+")
_MAX_EXAMPLE_NAME_CHARS = 48
_MAX_EXAMPLE_SUMMARY_CHARS = 800
_MAX_TOPIC_SUMMARY_CHARS = 240

# 鈹€鈹€ 鐭ヨ瘑鐐规彁鍙栫浉鍏虫ā寮?鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
# 涓枃瀛︾姒傚康璇嶏紙2-8瀛楋紝鎺掗櫎甯歌鍋滅敤璇嶏級
_CN_CONCEPT_RE = re.compile(
    r"(?:(?:姹倈璁＄畻|璇佹槑|鍒ゆ柇|璁ㄨ|鍒╃敤|鏍规嵁|鐢眧鐢▅鍏充簬|宸茬煡)\s*)"
    r"([\u4e00-\u9fff]{2,8}(?:鐨刐\u4e00-\u9fff]{2,6})?)",
)
# 甯歌瀛︾鏂规硶/瀹氱悊/鍏紡鍚嶇О
_METHOD_KEYWORDS_RE = re.compile(
    r"([\u4e00-\u9fff]{2,6}(?:娉晐瀹氱悊|鍏紡|瀹氬緥|鍘熺悊|鍑嗗垯|鏂圭▼|鍙樻崲|鍒嗚В|灞曞紑|鍒ゅ埆|涓嶇瓑寮?)",
)
# LaTeX 涓殑鍑芥暟鍚?_LATEX_FUNC_RE = re.compile(
    r"\\(?:sin|cos|tan|cot|sec|csc|ln|log|lim|int|sum|prod|det|max|min|sup|inf|arg|exp|sqrt)\b",
)
# 姒傚康鎬у唴瀹规娴?_CONCEPTUAL_KEYWORDS_RE = re.compile(
    r"(?:瀹氫箟|瀹氱悊|鎬ц川|寮曠悊|鎺ㄨ|鍏悊|鍛介|姒傚康|鍘熺悊|娉曞垯|鍏紡)",
)
_INDEPENDENT_FORMULA_RE = re.compile(r"\$\$[^$]+\$\$", re.DOTALL)
# 鍋滅敤璇嶏細杩囦簬瀹芥硾涓嶉€傚悎浣滀负鐭ヨ瘑鐐?_CONCEPT_STOPWORDS = frozenset({
    "閫夋嫨棰?, "濉┖棰?, "瑙ｇ瓟棰?, "鍒ゆ柇棰?, "璁＄畻棰?, "璇佹槑棰?, "绠€绛旈",
    "璁鸿堪棰?, "搴旂敤棰?, "缁煎悎棰?, "澶ч", "灏忛", "鏈", "涓嬪垪",
    "浠ヤ笅", "鍏朵腑", "鎵€鏈?, "浠绘剰", "瀛樺湪", "婊¤冻", "鏉′欢",
    "姝ｇ‘", "閿欒", "绛旀", "瑙ｆ瀽", "鍒嗘瀽", "缁撴灉", "杩囩▼",
})

# LLM 杞婚噺姒傚康鎻愬彇 prompt
_SYSTEM_PROMPT_CONCEPT_EXTRACT = """
浣犳槸涓€鍚嶇煡璇嗙偣璇嗗埆鍔╂墜銆傝浠庝互涓嬮鐩唴瀹逛腑鎻愬彇鑳屽悗鑰冩煡鐨勬牳蹇冪煡璇嗙偣銆?
## 杈撳嚭瑕佹眰
- 姣忎釜鐭ヨ瘑鐐圭敤涓€涓畝鐭悕绉拌〃绀猴紙2-8涓瓧锛?- 鏍囨敞绫诲瀷锛欳oncept锛堟蹇碉級鎴?Method锛堟柟娉?鎶€宸э級
- 鍙彁鍙栧绉戦€氱敤鐭ヨ瘑鐐癸紝涓嶆彁鍙栭鐩笓灞炶瀹?- 鏈€澶氳繑鍥?8 涓煡璇嗙偣
""".strip()

_USER_PROMPT_CONCEPT_EXTRACT = """
## 棰樼洰鍐呭

{{ questions_text }}

璇锋彁鍙栬繖浜涢鐩儗鍚庤€冩煡鐨勬牳蹇冪煡璇嗙偣銆?""".strip()


class _ConceptItem(BaseModel):
    name: str = Field(description="鐭ヨ瘑鐐瑰悕绉?)
    node_type: Literal["Concept", "Method"] = Field(description="鑺傜偣绫诲瀷")


class _ConceptExtractResult(BaseModel):
    """LLM 杞婚噺姒傚康鎻愬彇缁撴灉銆?""

    concepts: list[_ConceptItem] = Field(default_factory=list)


class CandidateNode(BaseModel):
    """A candidate knowledge node extracted from a chunk."""

    candidate_id: str = Field(default="", description="Internal stable candidate id.")
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
    source_candidate_id: str | None = Field(default=None, description="Resolved source candidate id.")
    target_candidate_id: str | None = Field(default=None, description="Resolved target candidate id.")
    source_node_type: str | None = Field(default=None, description="Resolved source node type.")
    target_node_type: str | None = Field(default=None, description="Resolved target node type.")
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
    text = normalize_semantic_whitespace(text)
    return _MULTISPACE_RE.sub(" ", text).strip()


# 鈹€鈹€ 鐭ヨ瘑鐐规彁鍙栧嚱鏁?鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

def _extract_concept_keywords_from_questions(
    questions: list[QuestionBlock],
) -> list[tuple[str, str]]:
    """浠庨鐩腑鐢ㄨ鍒欐彁鍙栧绉戞蹇靛叧閿瘝銆?
    Returns:
        ``(keyword, node_type)`` 瀵瑰垪琛紝node_type 涓?``"Concept"`` 鎴?``"Method"``銆?    """
    seen: set[str] = set()
    results: list[tuple[str, str]] = []

    for q in questions:
        text = _normalize_text(q.stem + " " + q.content)

        # 鏂规硶/瀹氱悊/鍏紡鍚嶇О浼樺厛锛堟洿绮剧‘锛?        for match in _METHOD_KEYWORDS_RE.finditer(text):
            term = match.group(1).strip()
            if term not in seen and term not in _CONCEPT_STOPWORDS and len(term) >= 2:
                seen.add(term)
                results.append((term, "Method"))

        # 涓枃瀛︾姒傚康璇?        for match in _CN_CONCEPT_RE.finditer(text):
            term = match.group(1).strip()
            if term not in seen and term not in _CONCEPT_STOPWORDS and len(term) >= 2:
                seen.add(term)
                results.append((term, "Concept"))

    # LaTeX 鍑芥暟鍚?鈫?瀵瑰簲鏁板姒傚康
    _LATEX_TO_CONCEPT = {
        "sin": "涓夎鍑芥暟", "cos": "涓夎鍑芥暟", "tan": "涓夎鍑芥暟",
        "cot": "涓夎鍑芥暟", "sec": "涓夎鍑芥暟", "csc": "涓夎鍑芥暟",
        "ln": "瀵规暟鍑芥暟", "log": "瀵规暟鍑芥暟",
        "lim": "鏋侀檺", "int": "绉垎", "sum": "绾ф暟姹傚拰",
        "prod": "杩炰箻绉?, "det": "琛屽垪寮?,
        "sqrt": "鏍瑰紡杩愮畻", "exp": "鎸囨暟鍑芥暟",
    }
    all_text = " ".join(_normalize_text(q.content) for q in questions)
    for match in _LATEX_FUNC_RE.finditer(all_text):
        func_name = match.group(0).lstrip("\\")
        concept = _LATEX_TO_CONCEPT.get(func_name)
        if concept and concept not in seen:
            seen.add(concept)
            results.append((concept, "Concept"))

    return results[:10]


async def _llm_extract_concepts_from_questions(
    questions: list[QuestionBlock],
) -> list[tuple[str, str]]:
    """褰撹鍒欐彁鍙栦负绌烘椂锛岀敤杞婚噺 LLM 浠庨鐩腑鎻愬彇鐭ヨ瘑鐐广€?""
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
            task_type=TaskType.DOCGEN_LIGHT,
        )
        return [
            (item.name.strip(), item.node_type)
            for item in result.concepts
            if item.name.strip() and item.name.strip() not in _CONCEPT_STOPWORDS
        ][:8]
    except Exception:
        logger.debug("llm_concept_extract_failed", exc_info=True)
        return []


def _extract_key_terms(content: str) -> list[str]:
    """浠庢枃鏈唴瀹逛腑鐢ㄨ鍒欐彁鍙栧叧閿湳璇紙鐢ㄤ簬 topic_fallback 澧炲己锛夈€?""
    text = _normalize_text(content)
    seen: set[str] = set()
    terms: list[str] = []

    # 鏂规硶/瀹氱悊/鍏紡鍚嶇О
    for match in _METHOD_KEYWORDS_RE.finditer(text):
        term = match.group(1).strip()
        if term not in seen and term not in _CONCEPT_STOPWORDS and len(term) >= 2:
            seen.add(term)
            terms.append(term)

    # "瀹氫箟"/"瀹氱悊"/"鎬ц川" 鍚庨潰鐨勫悕璇嶇煭璇?    for match in re.finditer(r"(?:瀹氫箟|瀹氱悊|鎬ц川|寮曠悊|鎺ㄨ|鍏紡)\s*[锛?]\s*([\u4e00-\u9fff]{2,8})", text):
        term = match.group(1).strip()
        if term not in seen and term not in _CONCEPT_STOPWORDS:
            seen.add(term)
            terms.append(term)

    # 涓枃瀛︾姒傚康璇?    for match in _CN_CONCEPT_RE.finditer(text):
        term = match.group(1).strip()
        if term not in seen and term not in _CONCEPT_STOPWORDS and len(term) >= 2:
            seen.add(term)
            terms.append(term)

    return terms[:5]


def has_conceptual_content(content: str) -> bool:
    """妫€娴嬫枃鏈槸鍚﹀寘鍚蹇垫€у唴瀹癸紙瀹氫箟/瀹氱悊/鍏紡鍧楃瓑锛夈€?
    鐢ㄤ簬 fast_path 鍒ゆ柇锛氬寘鍚蹇垫€у唴瀹圭殑 chunk 涓嶅簲璧?fast_path銆?    """
    # 鍖呭惈瀹氫箟/瀹氱悊/鎬ц川绛夊叧閿瘝
    if len(_CONCEPTUAL_KEYWORDS_RE.findall(content)) >= 2:
        return True
    # 鍖呭惈鐙珛鍏紡鍧?    if len(_INDEPENDENT_FORMULA_RE.findall(content)) >= 2:
        return True
    # 闈為鐩枃鏈崰姣旀娴嬶細鍘绘帀棰樼洰鍧楀悗鍓╀綑鏂囨湰鍗犳瘮 > 30%
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
        return f"棰榹num}"
    return f"棰榹num}锛歿stem}"


def _format_example_summary(question: QuestionBlock) -> str:
    return _truncate(_normalize_text(question.content), limit=_MAX_EXAMPLE_SUMMARY_CHARS)


def _looks_like_question_chunk(chunk_content: str) -> bool:
    return len(parse_question_blocks(chunk_content)) >= 2


def _split_header_path(header_path: str, chunk_title: str) -> list[str]:
    return choose_semantic_topic_path(
        header_path=header_path,
        fallback_title=chunk_title,
    )


def _fallback_question_support_name(
    *,
    digest_mode: str,
    leaf_topic_name: str,
) -> tuple[str, Literal["Concept", "Method"]]:
    normalized_leaf = clean_semantic_title(leaf_topic_name)
    if normalized_leaf and normalized_leaf != DEFAULT_QUESTION_TOPIC:
        if digest_mode == "sprint":
            return f"{normalized_leaf}閫熻В鏂规硶", "Method"
        return f"{normalized_leaf}缁煎悎搴旂敤", "Concept"
    if digest_mode == "sprint":
        return "閫熻В鏂规硶涓庨鍨嬪綊绾?, "Method"
    return "缁煎悎搴旂敤涓庡吀鍨嬮鍨?, "Concept"


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
        if node.node_type in {"Topic", "Concept", "Method"}
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
        if node.node_type == "Topic":
            cleaned_name = clean_semantic_title(node.name) or fallback_topic_name
            node.name = cleaned_name
            if not node.taxonomy_hint or is_generic_semantic_title(node.taxonomy_hint):
                if len(fallback_topic_path) >= 2 and cleaned_name == fallback_topic_path[-1]:
                    node.taxonomy_hint = fallback_topic_path[-2]
                else:
                    node.taxonomy_hint = cleaned_name
        else:
            node.name = _normalize_text(node.name)
            if node.node_type in {"Concept", "Method"} and (
                not node.taxonomy_hint or is_generic_semantic_title(node.taxonomy_hint)
            ):
                node.taxonomy_hint = fallback_topic_name
            if node.node_type in {"Definition", "Example"} and (
                not node.parent_entity_name or is_generic_semantic_title(node.parent_entity_name)
            ):
                node.parent_entity_name = fallback_topic_name
        rename_map[original_name] = node.name

    for node in result.nodes:
        if node.parent_entity_name:
            node.parent_entity_name = rename_map.get(node.parent_entity_name, node.parent_entity_name)
        if node.taxonomy_hint:
            node.taxonomy_hint = rename_map.get(node.taxonomy_hint, node.taxonomy_hint)

    for edge in result.edges:
        edge.source_name = rename_map.get(edge.source_name, edge.source_name)
        edge.target_name = rename_map.get(edge.target_name, edge.target_name)
    return result


def _assign_candidate_ids_and_edge_types(result: ChunkExtractionResult) -> ChunkExtractionResult:
    for index, node in enumerate(result.nodes, start=1):
        if not node.candidate_id:
            node.candidate_id = build_candidate_stable_id(
                node_type=node.node_type,
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
        "belongs_to_topic": {
            "source": ("Concept", "Method", "Definition", "Example", "Topic"),
            "target": ("Topic",),
        },
        "prerequisite_of": {
            "source": ("Topic", "Concept", "Method"),
            "target": ("Topic", "Concept", "Method"),
        },
        "defined_by": {
            "source": ("Concept", "Method", "Topic"),
            "target": ("Definition",),
        },
        "illustrated_by": {
            "source": ("Concept", "Method", "Topic"),
            "target": ("Example",),
        },
        "part_of": {
            "source": ("Topic", "Concept", "Method"),
            "target": ("Topic", "Concept", "Method"),
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
                if node.node_type == expected_type:
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
            edge.source_node_type = source_node.node_type
        if target_node is not None:
            edge.target_candidate_id = target_node.candidate_id
            edge.target_node_type = target_node.node_type
    return result


def _build_topic_fallback(
    *,
    chunk_content: str,
    chunk_title: str,
    header_path: str,
    chapter_topic_hints: list[str] | None = None,
    subject_context: str | None = None,
) -> ChunkExtractionResult:
    """Build a multi-level Topic hierarchy from the header path.

    Also extracts key terms from the content as Concept nodes so that
    downstream clustering and curriculum derivation see richer structure
    beyond just Topic shells.
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
        summary = f"鐭ヨ瘑涓婚锛屾潵婧愪簬鏂囨。缁撴瀯锛歿header_path or chunk_title or leaf_name}銆?

    nodes: list[CandidateNode] = []
    edges: list[CandidateEdge] = []

    # Create Topic nodes for each level of the hierarchy
    for i, part_name in enumerate(cleaned_parts):
        is_leaf = i == len(cleaned_parts) - 1
        parent_name = cleaned_parts[i - 1] if i > 0 else None
        nodes.append(
            CandidateNode(
                name=part_name,
                node_type="Topic",
                local_summary=summary if is_leaf else f"涓婂眰涓婚锛歿part_name}銆?,
                taxonomy_hint=parent_name or part_name,
                parent_entity_name=None,
            )
        )
        if parent_name:
            edges.append(
                CandidateEdge(
                    source_name=part_name,
                    target_name=parent_name,
                    edge_type="part_of",
                    description=f"{part_name} 鏄?{parent_name} 鐨勫瓙涓婚銆?,
                )
            )

    # Extract key terms from content as Concept nodes
    existing_names = {n.name for n in nodes}
    key_terms = _extract_key_terms(chunk_content)
    for term in key_terms:
        if term in existing_names:
            continue
        existing_names.add(term)
        nodes.append(
            CandidateNode(
                name=term,
                node_type="Concept",
                local_summary=f"浠庢枃鏈腑璇嗗埆鐨勫叧閿蹇碉細{term}銆?,
                taxonomy_hint=leaf_name,
                parent_entity_name=None,
            )
        )
        edges.append(
            CandidateEdge(
                source_name=term,
                target_name=leaf_name,
                edge_type="belongs_to_topic",
                description=f"{term} 灞炰簬涓婚 {leaf_name}銆?,
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

    Creates the full header-path hierarchy, attaches questions as Example
    nodes, and extracts Concept/Method nodes from the questions using a
    hybrid strategy (rule-based first, LLM fallback if rules yield nothing).
    """
    question_blocks = parse_question_blocks(chunk_content)
    if len(question_blocks) < 2:
        return None

    nodes: list[CandidateNode] = []
    edges: list[CandidateEdge] = []

    # Extract Concept/Method nodes from questions (hybrid: rules 鈫?LLM)
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

    # Create Topic nodes for each hierarchy level
    for index, part_name in enumerate(semantic_topic_path):
        is_leaf = index == len(semantic_topic_path) - 1
        parent_name = semantic_topic_path[index - 1] if index > 0 else None
        nodes.append(
            CandidateNode(
                name=part_name,
                node_type="Topic",
                local_summary=(
                    f"棰樺瀷涓撻锛屽寘鍚?{len(question_blocks)} 閬撻鐩€傛潵婧愶細{header_path or chunk_title}銆?
                    if is_leaf
                    else f"涓婂眰涓婚锛歿part_name}銆?
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
                    edge_type="part_of",
                    description=f"{part_name} 鏄?{parent_name} 鐨勫瓙涓婚銆?,
                )
            )

    existing_names = {n.name for n in nodes}
    concept_names: list[str] = []
    for concept_name, node_type in concept_pairs:
        if concept_name in existing_names:
            continue
        existing_names.add(concept_name)
        concept_names.append(concept_name)
        nodes.append(
            CandidateNode(
                name=concept_name,
                node_type=node_type,
                local_summary=f"浠庨鐩腑璇嗗埆鐨勬牳蹇冪煡璇嗙偣锛歿concept_name}銆?,
                taxonomy_hint=leaf_topic_name,
                parent_entity_name=None,
            )
        )
        edges.append(
            CandidateEdge(
                source_name=concept_name,
                target_name=leaf_topic_name,
                edge_type="belongs_to_topic",
                description=f"{concept_name} 灞炰簬涓婚 {leaf_topic_name}銆?,
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
                node_type=fallback_support_type,
                local_summary="浠庨鐩泦鍚堜腑褰掔撼鍑虹殑棰樺瀷/鏂规硶鏀偣锛岀敤浜庢壙鎺ュ吀鍨嬮涓庣患鍚堝簲鐢ㄣ€?,
                taxonomy_hint=leaf_topic_name,
                parent_entity_name=None,
            )
        )
        edges.append(
            CandidateEdge(
                source_name=fallback_support_name,
                target_name=leaf_topic_name,
                edge_type="belongs_to_topic",
                description=f"{fallback_support_name} 灞炰簬涓婚 {leaf_topic_name}銆?,
            )
        )

    # Attach questions to the leaf topic and link to extracted concepts
    for index, question in enumerate(question_blocks, start=1):
        example_name = _format_example_name(question, index)
        nodes.append(
            CandidateNode(
                name=example_name,
                node_type="Example",
                local_summary=_format_example_summary(question),
                taxonomy_hint=leaf_topic_name,
                parent_entity_name=concept_names[0],
            )
        )
        # Link example to relevant concepts via illustrated_by
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
                        edge_type="illustrated_by",
                        description=f"{cname} 鐢?{example_name} 涓句緥璇存槑銆?,
                    )
                )
        if not matched:
            edges.append(
                CandidateEdge(
                    source_name=concept_names[0],
                    target_name=example_name,
                    edge_type="illustrated_by",
                    description=f"{concept_names[0]} 鐢?{example_name} 涓句緥璇存槑銆?,
                )
            )

    logger.info(
        "kg_question_fallback_built",
        chunk_title=chunk_title,
        question_count=len(question_blocks),
        concept_count=len(concept_names),
        concept_names=concept_names[:5],
    )
    return ChunkExtractionResult(nodes=nodes, edges=edges)


async def extract_candidates(
    chunk_content: str,
    chunk_title: str,
    header_path: str,
    doc_source_type: str | None = None,
    subject_context: str | None = None,
    prefer_fast_path: bool = False,
    sibling_topics: str = "",
    digest_mode: str = "",
    chapter_topic_hints: list[str] | None = None,
) -> ChunkExtractionResult:
    """Extract candidate nodes and edges from one chunk."""

    user_content = populate_prompt(
        USER_PROMPT_KG_EXTRACT,
        chunk_content=chunk_content,
        chunk_title=chunk_title,
        header_path=header_path,
        doc_source_type=doc_source_type or "",
        subject_context=subject_context or "",
        sibling_topics=sibling_topics,
        digest_mode=digest_mode,
    )

    messages: list[ChatMessage] = [
        {"role": SYSTEM, "content": SYSTEM_PROMPT_KG_EXTRACT},
        {"role": USER, "content": user_content},
    ]

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

    used_question_fallback = False
    used_topic_fallback = False

    if prefer_fast_path and question_fallback is not None:
        logger.info(
            "kg_extract_fast_path_used",
            chunk_title=chunk_title,
            header_path=header_path,
            node_count=len(question_fallback.nodes),
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
                node_count=len(question_fallback.nodes),
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
                    node_count=len(question_fallback.nodes),
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
    "has_conceptual_content",
]

