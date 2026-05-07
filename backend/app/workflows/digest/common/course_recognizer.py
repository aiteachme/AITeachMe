"""Rule-based material signal recognition from prepared content."""

from __future__ import annotations

from collections import Counter

import structlog

from app.workflows.digest.common.models import (
    FastTopicHints,
    SectionPacket,
    SourcePacket,
    CourseProfile,
)

logger = structlog.get_logger()

# 这里只识别资料形态，不用关键词表判断课程学科或学习意图。
# 课程主线来自 confirmed plan、用户目标、资料标题/高频主题和 intent v2。
_CONTENT_TYPE_SIGNALS: dict[str, list[str]] = {
    "exam_paper": [
        "试卷", "满分", "准考证", "考生", "作答", "分值",
    ],
    "lecture_notes": [
        "讲义", "课堂", "笔记", "板书", "教案",
    ],
    "textbook": [
        "教材", "课本",
    ],
}


def recognize_course_profile(
    *,
    course_id: str,
    source_packets: list[SourcePacket],
    section_packets: list[SectionPacket],
    fast_hints: FastTopicHints,
) -> CourseProfile:
    """Build a CourseProfile from generic material signals.

    Course display names are intentionally ignored here. They are UI labels,
    not evidence about the material's discipline or learning target. This
    helper also does not infer course intent; intent is handled by confirmed
    plan + DocGen intent inference.
    """

    content_sample = _build_content_sample(source_packets, section_packets)

    discipline = ""
    sub_discipline = ""

    content_type = _detect_content_type(content_sample, section_packets)

    difficulty_level = _detect_difficulty(content_sample, section_packets)

    key_topics = _extract_key_topics(fast_hints, section_packets)

    has_heavy_formulas = fast_hints.question_density < 0.5 and len(fast_hints.formula_patterns) > 5
    has_heavy_questions = fast_hints.question_density > 0.3
    has_heavy_diagrams = sum(1 for p in source_packets if p.has_images) > len(source_packets) * 0.5
    material_forms = _detect_material_forms(
        source_packets=source_packets,
        section_packets=section_packets,
        has_heavy_formulas=has_heavy_formulas,
        has_heavy_questions=has_heavy_questions,
        has_heavy_diagrams=has_heavy_diagrams,
    )
    assessment_signals = _detect_assessment_signals(content_sample, section_packets)
    knowledge_domain_hints = _knowledge_domain_hints(key_topics=key_topics)

    teaching_style_hint = _build_teaching_style_hint(
        content_type=content_type,
        has_heavy_formulas=has_heavy_formulas,
        has_heavy_questions=has_heavy_questions,
        assessment_signals=assessment_signals,
    )

    profile = CourseProfile(
        course_id=course_id,
        course_name="",
        discipline=discipline,
        sub_discipline=sub_discipline,
        content_type=content_type,
        difficulty_level=difficulty_level,
        key_topics=key_topics[:12],
        has_heavy_formulas=has_heavy_formulas,
        has_heavy_questions=has_heavy_questions,
        has_heavy_diagrams=has_heavy_diagrams,
        teaching_style_hint=teaching_style_hint,
        knowledge_domain_hints=knowledge_domain_hints,
        material_forms=material_forms,
        assessment_signals=assessment_signals,
        profile_confidence=0.60 if key_topics or material_forms else 0.35,
        profile_evidence={
            "content_type": content_type,
            "question_density": f"{fast_hints.question_density:.2f}",
            "topic_hint_count": str(len(key_topics)),
            "material_forms": "；".join(material_forms),
            "assessment_signals": "；".join(assessment_signals),
        },
    )
    logger.info(
        "course_profile_recognized",
        course_id=course_id,
        discipline=discipline,
        sub_discipline=sub_discipline,
        content_type=content_type,
        difficulty=difficulty_level,
        key_topic_count=len(key_topics),
    )
    return profile


def _build_content_sample(
    source_packets: list[SourcePacket],
    section_packets: list[SectionPacket],
) -> str:
    """Build a representative content sample for material-form analysis."""

    parts: list[str] = []
    for packet in source_packets[:3]:
        parts.append(packet.normalized_content[:2000])
    for section in section_packets[:20]:
        parts.append(section.preview)
        parts.append(section.title)
        parts.append(section.header_path)
    return "\n".join(parts).lower()


def _detect_content_type(content_sample: str, section_packets: list[SectionPacket]) -> str:
    """Detect whether content is exam, textbook, lecture notes, or mixed."""

    scores: dict[str, int] = {}
    for content_type, signals in _CONTENT_TYPE_SIGNALS.items():
        score = sum(1 for signal in signals if signal in content_sample)
        if score > 0:
            scores[content_type] = score

    question_sections = sum(1 for p in section_packets if p.question_block_count > 0)
    if section_packets and question_sections / len(section_packets) > 0.45:
        scores["practice_rich_material"] = scores.get("practice_rich_material", 0) + 2

    if not scores:
        return "mixed"

    winner = max(scores, key=lambda k: scores[k])
    return "mixed" if winner == "practice_rich_material" and scores.get("exam_paper", 0) <= 0 else winner


def _detect_difficulty(content_sample: str, section_packets: list[SectionPacket]) -> str:
    """Estimate difficulty level from content signals."""
    del content_sample

    # Formula density as difficulty proxy
    avg_formulas = 0.0
    avg_chars = 0.0
    if section_packets:
        avg_formulas = sum(len(p.formula_refs) for p in section_packets) / len(section_packets)
        avg_chars = sum(int(p.char_count or 0) for p in section_packets) / len(section_packets)

    if avg_formulas > 3.0 or avg_chars > 2800:
        return "advanced"
    if avg_formulas < 0.5 and avg_chars < 1200:
        return "introductory"
    return "intermediate"


def _extract_key_topics(
    fast_hints: FastTopicHints,
    section_packets: list[SectionPacket],
) -> list[str]:
    """Extract key topics from hints and section titles."""

    candidates: list[str] = []

    # From chapter candidates
    candidates.extend(fast_hints.chapter_candidates)

    # From high-freq terms
    for term, freq in fast_hints.high_freq_terms[:15]:
        if freq >= 2 and len(term) >= 2:
            candidates.append(term)

    # From section titles (non-generic)
    title_counter: Counter[str] = Counter()
    for packet in section_packets:
        cleaned = packet.title.strip()
        if cleaned and len(cleaned) >= 2 and len(cleaned) <= 20:
            title_counter[cleaned] += 1
    for title, count in title_counter.most_common(10):
        if count >= 1:
            candidates.append(title)

    # Dedupe
    seen: set[str] = set()
    deduped: list[str] = []
    for topic in candidates:
        normalized = topic.strip().lower()
        if normalized and normalized not in seen:
            seen.add(normalized)
            deduped.append(topic.strip())
    return deduped


def _knowledge_domain_hints(
    *,
    key_topics: list[str],
) -> list[str]:
    hints = [*key_topics[:10]]
    return [item for item in dict.fromkeys(str(item or "").strip() for item in hints) if item][:10]


def _detect_assessment_signals(content_sample: str, section_packets: list[SectionPacket]) -> list[str]:
    signals: list[str] = []
    question_sections = sum(1 for p in section_packets if p.question_block_count > 0)
    ratio = question_sections / max(1, len(section_packets))
    if ratio > 0.15:
        signals.append(f"含练习/问题小节 {ratio:.2f}")
    if any(marker in content_sample for marker in ("考试", "考前", "试卷", "真题", "分值")):
        signals.append("含考试或测评措辞")
    if any(marker in content_sample for marker in ("选择题", "填空题", "简答题", "证明题", "计算题")):
        signals.append("含题型化表达")
    return signals[:6]


def _detect_material_forms(
    *,
    source_packets: list[SourcePacket],
    section_packets: list[SectionPacket],
    has_heavy_formulas: bool,
    has_heavy_questions: bool,
    has_heavy_diagrams: bool,
) -> list[str]:
    forms: list[str] = []
    if has_heavy_formulas:
        forms.append("公式/符号密集")
    if has_heavy_questions:
        forms.append("含较多练习或问题")
    if has_heavy_diagrams:
        forms.append("图示较多")
    if any(packet.has_tables for packet in source_packets):
        forms.append("含表格")
    if any("slides" in packet.filetype.lower() or "ppt" in packet.filetype.lower() for packet in source_packets):
        forms.append("课件/幻灯片")
    if any(section.level <= 2 and section.title for section in section_packets):
        forms.append("有章节/小节结构")
    return list(dict.fromkeys(forms or ["混合资料"]))[:8]


def _build_teaching_style_hint(
    *,
    content_type: str,
    has_heavy_formulas: bool,
    has_heavy_questions: bool,
    assessment_signals: list[str] | None = None,
) -> str:
    """Build a teaching style guidance string for the writer prompt."""

    hints: list[str] = []

    if has_heavy_formulas:
        hints.append("资料包含较多公式或符号，生成时需要解释符号含义、适用条件和推导/使用路径")

    assessment_signals = assessment_signals or []
    if content_type == "exam_paper":
        hints.append("这是考试/试卷内容，重点整理题型分类、解题方法和易错点")
        if has_heavy_questions:
            hints.append("题目较多，按知识点归类整理，突出解题策略而非逐题罗列")
    elif content_type == "textbook":
        hints.append("教材内容，保持知识体系的完整性和逻辑递进")
    elif content_type == "lecture_notes":
        hints.append("讲义/笔记内容，补充必要的上下文和过渡，使内容自成体系")
    elif assessment_signals:
        hints.append("资料包含练习或测评信号，但仍应先围绕知识主线组织，再用例子和练习辅助迁移")

    return "；".join(hints) if hints else ""
