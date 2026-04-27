"""Quality guards for docs-sync graph candidates."""

from __future__ import annotations

import re

from app.models.knowledge_taxonomy import normalize_knowledge_unit_type
from app.workflows.digest.kg_doc_sync.lib.extraction import CandidateNode, ChunkExtractionResult

_DOCS_UNIT_WRAPPER_TERMS = (
    "题型例练",
    "例题精练",
    "典型题型",
    "速判口诀",
    "速判例题",
    "考前复盘",
    "复盘口诀",
    "回看清单",
    "本章自检",
    "本章小结",
    "本章摘要",
    "章节导读",
    "学习目标",
    "知识主线",
    "应试策略",
    "解题入口",
    "解题模板",
    "速判",
    "题眼",
    "必会",
    "主干划分",
    "学习顺序",
    "认知难度",
    "区分标准",
    "常见误解",
    "错误推理",
    "失分点",
    "预警",
    "过渡设计",
    "解决思路",
    "综合题结构",
    "知识组合",
    "跨模块",
)
_DOCS_UNIT_META_PHRASE_RE = re.compile(
    r"(?:"
    r"主干划分|学习顺序|认知难度(?:排序)?|区分标准|常见误解|错误推理|"
    r"路径的归纳|解释路径|关键判断逻辑|步骤拆解|失分点|预警|"
    r"过渡设计|解决思路|体现方式|完整推导链条|综合题结构|知识组合|跨模块|"
    r"(?:各模块|模块).{0,12}(?:权重|认知难度|排序)|"
    r"(?:考试|常考).{0,12}(?:权重|排序|模块|结构|题)|"
    r"(?:实验设计|现象解释).{0,12}对应关系"
    r")"
)
_DOCS_UNIT_ACTION_PREFIX_RE = re.compile(
    r"^(?:"
    r"分析|总结|提炼|设计|建立|明确|强调|归纳|梳理|围绕|揭示|说明|复述|判断|区分|比较|"
    r"计算|求|证明|写出|改造|构造|抓住|先标|标出|把|找|寻找"
    r")"
)
_DOCS_UNIT_QUESTION_STEM_RE = re.compile(
    r"^(?:题\s*\d*|例题\s*\d*|练习\s*\d*|问题\s*\d*)\s*[:：]"
    r"|^点\s*[A-Za-z]\s*\("
    r"|^(?:已知|若|设|求|计算|证明|判断)(?:\s|$|[，,：:])"
)
_DOCS_UNIT_OUTLINE_PREFIX_RE = re.compile(r"^\s*[一二三四五六七八九十]+[、.．]\s*")
_DOCS_UNIT_FORMULA_HINT_RE = re.compile(
    r"(?:\\[A-Za-z]+|\$|[=<>≤≥≈∑∫√]|λ|alpha|beta|gamma|theta|det|lim|sin|cos|tan)"
)


def _strip_docs_unit_outline_prefix(name: str) -> str:
    return _DOCS_UNIT_OUTLINE_PREFIX_RE.sub("", str(name or "").strip()).strip()


def _looks_like_formula_unit_name(name: str, *, node_type: str = "") -> bool:
    normalized_type = normalize_knowledge_unit_type(node_type or "concept")
    return normalized_type == "formula" or bool(_DOCS_UNIT_FORMULA_HINT_RE.search(str(name or "")))


def is_low_quality_docs_unit_name(name: str, *, node_type: str = "") -> bool:
    """Reject doc-sync candidates that are teaching wrappers rather than KUs."""

    raw = str(name or "").strip()
    cleaned = _strip_docs_unit_outline_prefix(raw)
    normalized_type = normalize_knowledge_unit_type(node_type or "concept")
    if not cleaned or len(cleaned) <= 1:
        return True
    if _looks_like_formula_unit_name(cleaned, node_type=normalized_type):
        return False
    if _DOCS_UNIT_OUTLINE_PREFIX_RE.match(raw):
        return True
    if any(term in cleaned for term in _DOCS_UNIT_WRAPPER_TERMS):
        return True
    if normalized_type in {"concept", "method", "remark", "example", "exercise"} and _DOCS_UNIT_META_PHRASE_RE.search(cleaned):
        return True
    if _DOCS_UNIT_QUESTION_STEM_RE.search(cleaned):
        return True
    if normalized_type in {"example", "exercise"} and re.search(r"[；;。]|[:：]", cleaned):
        return True
    if normalized_type in {"concept", "method", "remark"} and _DOCS_UNIT_ACTION_PREFIX_RE.search(cleaned):
        return True
    if len(cleaned) > 34 and re.search(r"[，,；;。！？!?：:]", cleaned):
        return True
    return False


def filter_docs_candidate_result(result: ChunkExtractionResult) -> ChunkExtractionResult:
    kept_nodes: list[CandidateNode] = []
    dropped_candidate_ids: set[str] = set()
    dropped_names: set[str] = set()
    for node in result.nodes:
        if is_low_quality_docs_unit_name(node.name, node_type=node.knowledge_unit_type):
            dropped_candidate_ids.add(str(node.candidate_id or ""))
            dropped_names.add(str(node.name or "").strip())
            continue
        kept_nodes.append(node)
    if not dropped_candidate_ids and not dropped_names:
        return result

    kept_edges = [
        edge
        for edge in result.edges
        if edge.source_candidate_id not in dropped_candidate_ids
        and edge.target_candidate_id not in dropped_candidate_ids
        and edge.source_name not in dropped_names
        and edge.target_name not in dropped_names
    ]
    return result.model_copy(update={"nodes": kept_nodes, "edges": kept_edges})


__all__ = ["filter_docs_candidate_result", "is_low_quality_docs_unit_name"]
