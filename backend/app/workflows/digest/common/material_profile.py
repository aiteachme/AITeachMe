"""Material profiling and digest mode decision helpers.

These helpers are shared by multiple digest lanes through ``SharedInputs``.
"""

from __future__ import annotations

import re

import structlog

from app.workflows.digest.common.models import (
    DigestMode,
    DigestModeDecision,
    MaterialProfile,
    MaterialStats,
    SectionPacket,
    SourcePacket,
    CourseProfile,
)

logger = structlog.get_logger()

# ── 统计相关模式 ────────────────────────────────────────────────

_FORMULA_PATTERN = re.compile(r"\$[^$\n]+\$|\$\$[^$]+\$\$", re.DOTALL)
_EXERCISE_PATTERN = re.compile(
    r"(?:^|\s)(?:练习|习题|思考题|作业|exercise)\s*[\d：:．.]",
    re.MULTILINE | re.IGNORECASE,
)
_QUESTION_PATTERN = re.compile(
    r"(?:^|\s)(?:[\d一二三四五六七八九十]+[\s\.、）)]\s*(?:选择|填空|计算|证明|简答|判断|论述))",
    re.MULTILINE,
)
_TABLE_PATTERN = re.compile(r"^\s*\|.+\|.+\|\s*$", re.MULTILINE)
_IMAGE_PATTERN = re.compile(r"!\[[^\]]*\]\([^)]+\)", re.IGNORECASE)
_NOISE_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f□■◆◇●○]")
# RISK-4 FIX: 用于在噪声检测前剥离公式块和代码块
_STRIP_FORMULA_BLOCK = re.compile(r"\$\$[^$]+\$\$", re.DOTALL)
_STRIP_INLINE_FORMULA = re.compile(r"\$[^$\n]+\$")
_STRIP_CODE_BLOCK = re.compile(r"```[^`]*```", re.DOTALL)


def _strip_structured_content(content: str) -> str:
    """剥离公式块、行内公式和代码块，用于纯净噪声检测。"""
    text = _STRIP_FORMULA_BLOCK.sub("", content)
    text = _STRIP_INLINE_FORMULA.sub("", text)
    text = _STRIP_CODE_BLOCK.sub("", text)
    return text


def compute_material_stats(sections: list[SectionPacket]) -> MaterialStats:
    """纯规则计算材料统计指标。0 API 调用，毫秒级。"""
    if not sections:
        return MaterialStats()

    total_chars = 0
    formula_count = 0
    exercise_count = 0
    concept_signal_count = 0
    image_count = 0
    table_count = 0
    noisy_sections = 0
    source_ids: set[int] = set()

    for section in sections:
        content = section.normalized_content
        total_chars += len(content)
        source_ids.add(section.source_file_id)

        # 公式计数
        formula_count += len(_FORMULA_PATTERN.findall(content))

        # 习题计数
        exercise_count += len(_EXERCISE_PATTERN.findall(content))
        exercise_count += len(_QUESTION_PATTERN.findall(content))

        title_text = f"{section.title} {section.header_path} {' '.join(section.header_candidates)}"
        if any(marker in title_text for marker in ("定义", "概念", "性质", "原理", "方法", "模型", "公式", "规则", "定理")):
            concept_signal_count += 1

        # 图片
        image_count += len(_IMAGE_PATTERN.findall(content))

        # 表格
        table_count += len(_TABLE_PATTERN.findall(content))

        # RISK-4 FIX: OCR 噪声检测 — 先剥离公式和代码块，再统计噪声字符比例
        stripped = _strip_structured_content(content)
        if stripped:
            noise_chars = len(_NOISE_CHARS.findall(stripped))
            if noise_chars / len(stripped) > 0.1:
                noisy_sections += 1

    n = max(len(sections), 1)
    return MaterialStats(
        total_sources=len(source_ids),
        total_sections=len(sections),
        total_chars=total_chars,
        formula_count=formula_count,
        formula_density=round(formula_count / n, 3),
        exercise_count=exercise_count,
        exercise_density=round(exercise_count / n, 3),
        concept_density=round(concept_signal_count / n, 3),
        image_count=image_count,
        table_count=table_count,
        ocr_noise_ratio=round(noisy_sections / n, 3),
        source_overlap=0.0,  # TODO: 后续可添加跨文件重复度计算
    )


def _estimate_content_type(
    source_packets: list[SourcePacket],
    stats: MaterialStats,
) -> dict[str, int]:
    """根据统计推断材料类型分布。"""
    types: dict[str, int] = {}

    for packet in source_packets:
        content = packet.normalized_content.lower()

        # 启发式判断
        if "试卷" in content or "准考证" in content or ("满分" in content and "考试" in content):
            types["exam_paper"] = types.get("exam_paper", 0) + 1
        elif stats.formula_density > 0.3 and len(content) > 5000:
            types["textbook"] = types.get("textbook", 0) + 1
        elif "笔记" in content or "课堂" in content or "slides" in content:
            types["lecture_notes"] = types.get("lecture_notes", 0) + 1
        elif "讲义" in content or "总结" in content:
            types["study_guide"] = types.get("study_guide", 0) + 1
        elif stats.exercise_density > 0.4:
            types["practice_rich_material"] = types.get("practice_rich_material", 0) + 1
        else:
            types["mixed"] = types.get("mixed", 0) + 1

    return types if types else {"mixed": len(source_packets)}


def _assessment_signals(source_packets: list[SourcePacket], stats: MaterialStats) -> list[str]:
    signals: list[str] = []
    combined = "\n".join(packet.normalized_content[:2000].lower() for packet in source_packets)
    if stats.exercise_density > 0.18:
        signals.append(f"练习密度 {stats.exercise_density:.2f}")
    if any(marker in combined for marker in ("考试", "试卷", "考前", "真题", "分值")):
        signals.append("出现考试/测评相关措辞")
    if any(marker in combined for marker in ("选择题", "填空题", "简答题", "计算题", "证明题")):
        signals.append("包含题型化内容")
    return signals[:6]


def _material_forms(source_packets: list[SourcePacket], stats: MaterialStats) -> list[str]:
    forms: list[str] = []
    if stats.formula_density > 0.2:
        forms.append("公式/符号密集")
    if stats.exercise_density > 0.18:
        forms.append("含练习或题目")
    if stats.concept_density > 0.2:
        forms.append("概念/方法标题较多")
    if stats.image_count > 0:
        forms.append("含图片或图示")
    if stats.table_count > 0:
        forms.append("含表格")
    for packet in source_packets:
        text = packet.normalized_content[:2500].lower()
        if "slides" in text or "ppt" in packet.filetype.lower():
            forms.append("课件/幻灯片")
            break
    return list(dict.fromkeys(forms or ["混合资料"]))[:8]


def decide_digest_mode(
    profile: MaterialProfile,
    user_prompt: str | None = None,
    course_profile: CourseProfile | None = None,
) -> DigestModeDecision:
    """综合判定 Digest 模式。

    优先级：用户显式指定 > course 元数据 > 材料自动识别
    """
    evidence: dict[str, str] = {}

    # === 优先级 1：用户显式指定 ===
    if user_prompt:
        prompt_lower = user_prompt.lower()
        if any(kw in prompt_lower for kw in ["速成", "冲刺", "快速", "sprint", "考前"]):
            evidence["user_prompt"] = "用户明确要求速成课模式"
            return DigestModeDecision(
                mode=DigestMode.SPRINT,
                confidence=0.95,
                reason="用户明确要求速成课模式",
                user_override=True,
                evidence=evidence,
            )
        if any(kw in prompt_lower for kw in ["系统", "完整", "详细", "systematic"]):
            evidence["user_prompt"] = "用户明确要求系统/完整模式"
            return DigestModeDecision(
                mode=DigestMode.SYSTEMATIC,
                confidence=0.95,
                reason="用户明确要求系统/完整模式",
                user_override=True,
                evidence=evidence,
            )
        evidence["user_prompt"] = "用户提示词未明确指定模式"

    # === 优先级 2：course 元数据 ===
    if course_profile:
        if course_profile.content_type == "exam_paper":
            evidence["course"] = "课程识别为试卷/考题类型"
            return DigestModeDecision(
                mode=DigestMode.SPRINT,
                confidence=0.85,
                reason="材料识别为试卷/考题，适合速成课",
                evidence=evidence,
            )
        if course_profile.difficulty_level == "advanced":
            evidence["course"] = "课程难度为高级/进阶"

    # === 优先级 3：材料自动识别 ===
    stats = profile.stats

    if stats.exercise_density > 0.45 and "exam_paper" in profile.material_types:
        evidence["material"] = f"习题密度 {stats.exercise_density:.2f} 偏高"
        return DigestModeDecision(
            mode=DigestMode.SPRINT,
            confidence=0.80,
            reason=f"材料以习题为主（密度 {stats.exercise_density:.2f}），适合速成课",
            evidence=evidence,
        )

    if stats.formula_density > 0.2 and "textbook" in profile.material_types:
        evidence["material"] = f"公式密度 {stats.formula_density:.2f}，教材类型"
        return DigestModeDecision(
            mode=DigestMode.SYSTEMATIC,
            confidence=0.80,
            reason=f"教材类型且公式密集（密度 {stats.formula_density:.2f}），适合系统课学习",
            evidence=evidence,
        )

    # 默认：系统课模式
    evidence["default"] = "未检测到强信号，默认系统课模式"
    return DigestModeDecision(
        mode=DigestMode.SYSTEMATIC,
        confidence=0.60,
        reason="未检测到明确的模式信号，默认使用系统课模式",
        evidence=evidence,
    )


def build_material_profile(
    source_packets: list[SourcePacket],
    section_packets: list[SectionPacket],
    course_profile: CourseProfile | None = None,
) -> MaterialProfile:
    """构建材料画像（Phase 0 主入口）。

    纯规则 + 复用 course_profile，不额外调用 LLM。
    """
    stats = compute_material_stats(section_packets)
    material_types = _estimate_content_type(source_packets, stats)
    assessment_signals = _assessment_signals(source_packets, stats)
    material_forms = _material_forms(source_packets, stats)
    semantic_course = ""
    if course_profile is not None:
        semantic_course = (
            course_profile.sub_discipline
            or course_profile.discipline
            or (course_profile.key_topics[0] if course_profile.key_topics else "")
        )
    domain_hints = []
    if course_profile is not None:
        domain_hints.extend([course_profile.discipline, course_profile.sub_discipline, *course_profile.key_topics[:6]])
    domain_hints = [item for item in dict.fromkeys(str(item or "").strip() for item in domain_hints) if item]

    profile = MaterialProfile(
        course_name=semantic_course,
        sub_courses=course_profile.key_topics[:5] if course_profile else [],
        material_types=material_types,
        stats=stats,
        discipline=course_profile.discipline if course_profile else "",
        difficulty_level=course_profile.difficulty_level if course_profile else "",
        knowledge_domain_hints=domain_hints[:8],
        material_forms=material_forms,
        assessment_signals=assessment_signals,
        confidence=0.72 if domain_hints else 0.45,
        evidence={
            "material_forms": "；".join(material_forms),
            "assessment_signals": "；".join(assessment_signals),
            "density": (
                f"formula={stats.formula_density:.2f}; "
                f"exercise={stats.exercise_density:.2f}; "
                f"concept={stats.concept_density:.2f}"
            ),
        },
    )

    logger.info(
        "material_profile_built",
        course_name=profile.course_name,
        total_sources=stats.total_sources,
        total_sections=stats.total_sections,
        formula_density=stats.formula_density,
        exercise_density=stats.exercise_density,
        material_types=material_types,
    )
    return profile


__all__ = [
    "build_material_profile",
    "compute_material_stats",
    "decide_digest_mode",
]
