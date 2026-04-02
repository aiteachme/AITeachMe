"""教学语义切分服务。

将 SectionPacket 切分为 ContentPrimitive，再组装为 PedagogicalBlock。
80% 靠规则（免费），20% 靠 LLM 批量分类（便宜）。

使用方式：
    from app.workflows.digest.services.segmentation import segment_sections
    primitives, blocks = segment_sections(section_packets)
"""

from __future__ import annotations

import re
import uuid

import structlog

from app.workflows.digest.shared.models import SectionPacket
from app.workflows.digest.shared.primitives import (
    BlockRole,
    ContentPrimitive,
    PedagogicalBlock,
    PrimitiveType,
)

logger = structlog.get_logger()


# ── 规则库 ──────────────────────────────────────────────────────

# 定义/概念 关键词
_DEFINITION_PATTERNS = [
    re.compile(r"(?:^|\s)定义[\s：:．.]", re.MULTILINE),
    re.compile(r"(?:^|\s)概念[\s：:．.]", re.MULTILINE),
    re.compile(r"是指[^。]{5,}。"),
    re.compile(r"称为[^。]{3,}。"),
    re.compile(r"(?i)definition\s*[:：.]", re.MULTILINE),
]

# 定理/推论
_THEOREM_PATTERNS = [
    re.compile(r"(?:^|\s)定理[\s：:．.\d]", re.MULTILINE),
    re.compile(r"(?:^|\s)引理[\s：:．.\d]", re.MULTILINE),
    re.compile(r"(?:^|\s)推论[\s：:．.\d]", re.MULTILINE),
    re.compile(r"(?:^|\s)性质[\s：:．.\d]", re.MULTILINE),
    re.compile(r"(?:^|\s)命题[\s：:．.\d]", re.MULTILINE),
    re.compile(r"(?i)theorem\s*[\d：:.]", re.MULTILINE),
    re.compile(r"(?i)lemma\s*[\d：:.]", re.MULTILINE),
]

# 公式块
_FORMULA_BLOCK_PATTERN = re.compile(r"\$\$[^$]+\$\$", re.DOTALL)
_INLINE_FORMULA_PATTERN = re.compile(r"\$[^$\n]+\$")

# 例题/示例
_EXAMPLE_PATTERNS = [
    re.compile(r"(?:^|\s)例[\s\d：:．.]", re.MULTILINE),
    re.compile(r"(?:^|\s)例题[\s\d：:．.]", re.MULTILINE),
    re.compile(r"(?:^|\s)示例[\s\d：:．.]", re.MULTILINE),
    re.compile(r"(?:^|\s)解[：:．]\s", re.MULTILINE),
    re.compile(r"(?i)example\s*[\d：:.]", re.MULTILINE),
]

# 习题/练习
_EXERCISE_PATTERNS = [
    re.compile(r"(?:^|\s)练习[\s\d：:．.]", re.MULTILINE),
    re.compile(r"(?:^|\s)习题[\s\d：:．.]", re.MULTILINE),
    re.compile(r"(?:^|\s)思考题[\s\d：:．.]", re.MULTILINE),
    re.compile(r"(?:^|\s)作业[\s\d：:．.]", re.MULTILINE),
    re.compile(r"(?i)exercise\s*[\d：:.]", re.MULTILINE),
]

# 方法/步骤
_METHOD_PATTERNS = [
    re.compile(r"(?:^|\s)方法[\s：:．.]", re.MULTILINE),
    re.compile(r"(?:^|\s)步骤[\s：:．.]", re.MULTILINE),
    re.compile(r"(?:^|\s)算法[\s：:．.]", re.MULTILINE),
    re.compile(r"(?:^|\s)求解[\s：:．.]", re.MULTILINE),
    re.compile(r"第[一二三四五六七八九十\d]步", re.MULTILINE),
]

# 易错点/注意
_WARNING_PATTERNS = [
    re.compile(r"(?:^|\s)注意[\s：:．.]", re.MULTILINE),
    re.compile(r"(?:^|\s)易错[\s：:．.]", re.MULTILINE),
    re.compile(r"(?:^|\s)常见错误[\s：:．.]", re.MULTILINE),
    re.compile(r"(?:^|\s)误区[\s：:．.]", re.MULTILINE),
    re.compile(r"(?:^|\s)陷阱[\s：:．.]", re.MULTILINE),
    re.compile(r"(?i)(?:^|\s)(?:note|caution|warning)\s*[:：]", re.MULTILINE),
]

# 对比/区分
_COMPARISON_PATTERNS = [
    re.compile(r"(?:^|\s)区别[\s：:．.]", re.MULTILINE),
    re.compile(r"(?:^|\s)对比[\s：:．.]", re.MULTILINE),
    re.compile(r"(?:^|\s)比较[\s：:．.]", re.MULTILINE),
    re.compile(r"与[^。]+的(?:区别|异同|不同)", re.MULTILINE),
    re.compile(r"vs\.?\s", re.IGNORECASE),
]

# OCR 噪声检测
_NOISE_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]{3,}|[□■◆◇]{5,}")
_GARBLED_RATIO_THRESHOLD = 0.3  # 乱码字符超过 30% 视为噪声


def _extract_formulas(content: str) -> list[str]:
    """提取文本中的所有公式。"""
    formulas: list[str] = []
    for match in _FORMULA_BLOCK_PATTERN.finditer(content):
        formulas.append(match.group().strip())
    for match in _INLINE_FORMULA_PATTERN.finditer(content):
        formulas.append(match.group().strip())
    return formulas


def _is_noisy(content: str) -> bool:
    """判断内容是否为 OCR 噪声。"""
    if not content.strip():
        return True
    if _NOISE_PATTERN.search(content):
        return True
    # 统计不可打印和乱码字符
    non_printable = sum(1 for c in content if ord(c) < 32 and c not in "\n\r\t")
    if len(content) > 0 and non_printable / len(content) > _GARBLED_RATIO_THRESHOLD:
        return True
    return False


def _match_any(content: str, patterns: list[re.Pattern]) -> bool:
    """检查内容是否匹配任一模式。"""
    return any(p.search(content) for p in patterns)


def _classify_single(content: str, formulas: list[str]) -> tuple[PrimitiveType, float]:
    """用规则对单个内容块做分类。

    返回 (类型, 置信度)。置信度 < 0.5 表示不确定，应交给 LLM。
    """
    # 噪声优先检测
    if _is_noisy(content):
        return PrimitiveType.NOISE, 0.95

    # 公式块：内容主体是公式
    formula_chars = sum(len(f) for f in formulas)
    if formulas and formula_chars > len(content) * 0.5:
        return PrimitiveType.FORMULA, 0.9

    # 按优先级匹配（更具体的模式优先）
    if _match_any(content, _EXERCISE_PATTERNS):
        return PrimitiveType.EXERCISE, 0.85

    if _match_any(content, _EXAMPLE_PATTERNS):
        return PrimitiveType.EXAMPLE, 0.85

    if _match_any(content, _THEOREM_PATTERNS):
        return PrimitiveType.THEOREM, 0.85

    if _match_any(content, _DEFINITION_PATTERNS):
        return PrimitiveType.DEFINITION, 0.80

    if _match_any(content, _WARNING_PATTERNS):
        return PrimitiveType.WARNING, 0.80

    if _match_any(content, _METHOD_PATTERNS):
        return PrimitiveType.METHOD, 0.70

    if _match_any(content, _COMPARISON_PATTERNS):
        return PrimitiveType.COMPARISON, 0.75

    # 兜底
    return PrimitiveType.NARRATIVE, 0.40


# ── 核心 API ────────────────────────────────────────────────────


def classify_primitives_by_rules(
    sections: list[SectionPacket],
) -> list[ContentPrimitive]:
    """规则分类：将 SectionPacket 转为 ContentPrimitive。

    约 80% 的内容可以通过规则高置信度分类，剩余 20% 标记为
    narrative（低置信度），后续可交给 LLM 做二次分类。
    """
    primitives: list[ContentPrimitive] = []

    for section in sections:
        content = section.normalized_content
        if not content.strip():
            continue

        formulas = _extract_formulas(content)
        existing = section.formula_refs or []
        all_formulas = list(dict.fromkeys(existing + formulas))

        ptype, confidence = _classify_single(content, all_formulas)

        primitive = ContentPrimitive(
            uid=f"prim_{section.digest_chunk_uid}_{uuid.uuid4().hex[:6]}",
            type=ptype,
            content=content,
            source_file_id=section.source_file_id,
            source_filename=section.source_filename,
            source_page=section.page_num,
            section_uid=section.digest_chunk_uid,
            chunk_index=section.chunk_index,
            formulas=all_formulas,
            confidence=confidence,
            classifier="rule",
        )
        primitives.append(primitive)

    rule_classified = sum(1 for p in primitives if p.confidence >= 0.6)
    logger.info(
        "primitives_classified_by_rules",
        total=len(primitives),
        high_confidence=rule_classified,
        low_confidence=len(primitives) - rule_classified,
        pct_rule=f"{rule_classified / max(len(primitives), 1) * 100:.0f}%",
    )
    return primitives


def get_uncertain_primitives(primitives: list[ContentPrimitive]) -> list[ContentPrimitive]:
    """筛选出需要 LLM 二次分类的低置信度 primitive。"""
    return [p for p in primitives if p.confidence < 0.6 and p.type != PrimitiveType.NOISE]


def assemble_blocks(primitives: list[ContentPrimitive]) -> list[PedagogicalBlock]:
    """将相邻的同源 primitive 组装为 PedagogicalBlock。

    组装逻辑：
    1. 同一个 source_file_id 的相邻 primitive 尝试合并
    2. definition + formula + example → concept block
    3. method + example → method block
    4. exercise 连续块 → practice block
    5. 其余为 mixed block
    """
    if not primitives:
        return []

    # 按 source_file_id + chunk_index 排序
    sorted_prims = sorted(primitives, key=lambda p: (p.source_file_id, p.chunk_index))

    blocks: list[PedagogicalBlock] = []
    current_group: list[ContentPrimitive] = [sorted_prims[0]]

    for prim in sorted_prims[1:]:
        prev = current_group[-1]

        # 同源 + 相邻 chunk → 合并
        same_source = prim.source_file_id == prev.source_file_id
        adjacent = abs(prim.chunk_index - prev.chunk_index) <= 1

        if same_source and adjacent:
            current_group.append(prim)
        else:
            blocks.append(_make_block(current_group))
            current_group = [prim]

    if current_group:
        blocks.append(_make_block(current_group))

    logger.info(
        "blocks_assembled",
        total_blocks=len(blocks),
        total_primitives=sum(len(b.primitives) for b in blocks),
    )
    return blocks


def _make_block(primitives: list[ContentPrimitive]) -> PedagogicalBlock:
    """从一组 primitive 创建一个 PedagogicalBlock。"""
    types = {p.type for p in primitives}

    # 推断 role
    if types & {PrimitiveType.EXERCISE}:
        role = BlockRole.PRACTICE
    elif types & {PrimitiveType.EXAMPLE} and not types & {PrimitiveType.DEFINITION, PrimitiveType.THEOREM}:
        role = BlockRole.PRACTICE
    elif types & {PrimitiveType.METHOD}:
        role = BlockRole.METHOD
    elif types & {PrimitiveType.DEFINITION, PrimitiveType.THEOREM, PrimitiveType.FORMULA}:
        role = BlockRole.CONCEPT
    else:
        role = BlockRole.MIXED

    # 推断 topic hint（取第一个非 narrative primitive 的标题段）
    topic_hint = ""
    for p in primitives:
        if p.type != PrimitiveType.NARRATIVE:
            # 取内容的前 30 个字符作为 hint
            clean = p.content.strip().split("\n")[0][:30].strip()
            if clean:
                topic_hint = clean
                break

    return PedagogicalBlock(
        uid=f"block_{uuid.uuid4().hex[:8]}",
        topic_hint=topic_hint,
        primitives=primitives,
        role=role,
    )


def segment_sections(
    sections: list[SectionPacket],
) -> tuple[list[ContentPrimitive], list[PedagogicalBlock]]:
    """教学语义切分的主入口。

    Step 1: 规则分类 → ContentPrimitive[]
    Step 2: 组装 → PedagogicalBlock[]

    LLM 二次分类是可选的，调用方可以通过 get_uncertain_primitives()
    获取不确定项，再调用 LLM 批量分类后更新。

    Args:
        sections: 来自 shared prepare 的 SectionPacket 列表

    Returns:
        (primitives, blocks) 元组
    """
    primitives = classify_primitives_by_rules(sections)

    # 过滤掉噪声
    valid_primitives = [p for p in primitives if p.type != PrimitiveType.NOISE]

    blocks = assemble_blocks(valid_primitives)

    logger.info(
        "segmentation_completed",
        total_sections=len(sections),
        total_primitives=len(primitives),
        valid_primitives=len(valid_primitives),
        noise_filtered=len(primitives) - len(valid_primitives),
        total_blocks=len(blocks),
    )
    return primitives, blocks


# ── LLM 批量分类 Prompt ────────────────────────────────────────

PRIMITIVE_CLASSIFY_PROMPT = """\
你是一个教学内容分类助手。请把下面的内容片段分别归类。

可选类别：
- definition: 定义/概念
- theorem: 定理/引理/推论/性质
- formula: 独立公式块
- method: 方法/步骤/算法/求解流程
- example: 例题/示例（含解答）
- exercise: 习题/练习（无解答）
- warning: 易错点/注意事项
- narrative: 叙述/背景/过渡
- comparison: 对比/区分
- historical: 历史背景/人物事件

以下是需要分类的片段（用 --- 分隔）：

{segments}

输出要求：
返回严格 JSON 数组，每个元素包含 index 和 type：
[{{"index": 0, "type": "definition"}}, {{"index": 1, "type": "method"}}]
"""


__all__ = [
    "PRIMITIVE_CLASSIFY_PROMPT",
    "assemble_blocks",
    "classify_primitives_by_rules",
    "get_uncertain_primitives",
    "segment_sections",
]
