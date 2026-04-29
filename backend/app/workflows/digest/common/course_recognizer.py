"""Rule-based course/discipline recognition from content signals."""

from __future__ import annotations

import re
from collections import Counter

import structlog

from app.workflows.digest.common.models import (
    FastTopicHints,
    SectionPacket,
    SourcePacket,
    CourseProfile,
)

logger = structlog.get_logger()

# ── discipline keyword maps ──────────────────────────────────────────

_DISCIPLINE_KEYWORDS: dict[str, list[str]] = {
    "数学": [
        "函数", "导数", "积分", "极限", "微分", "矩阵", "向量", "行列式",
        "概率", "方程", "不等式", "数列", "集合", "映射", "线性", "特征值",
        "拉格朗日", "泰勒", "傅里叶", "高斯", "欧拉", "柯西",
        "定理", "证明", "推论", "引理", "公理",
        "sin", "cos", "tan", "log", "ln", "lim", "sum", "int",
        "frac", "sqrt", "infty", "partial", "nabla",
    ],
    "物理": [
        "力", "速度", "加速度", "动量", "能量", "功", "电场", "磁场",
        "电流", "电压", "电阻", "波", "光", "热", "熵", "量子",
        "牛顿", "麦克斯韦", "薛定谔", "玻尔兹曼",
        "焦耳", "安培", "伏特", "赫兹",
    ],
    "化学": [
        "分子", "原子", "离子", "化学键", "反应", "氧化", "还原",
        "酸", "碱", "盐", "溶液", "摩尔", "浓度", "催化",
        "有机", "无机", "高分子", "电化学",
    ],
    "计算机科学": [
        "算法", "数据结构", "复杂度", "排序", "搜索", "图论",
        "编程", "函数式", "面向对象", "递归", "迭代",
        "数据库", "网络", "操作系统", "编译", "机器学习",
        "python", "java", "javascript", "sql", "api",
    ],
    "经济学": [
        "供给", "需求", "均衡", "边际", "效用", "成本", "利润",
        "gdp", "通货膨胀", "利率", "汇率", "货币", "财政",
        "博弈", "纳什", "帕累托",
    ],
    "生物": [
        "细胞", "基因", "dna", "rna", "蛋白质", "酶", "代谢",
        "遗传", "进化", "生态", "光合作用", "呼吸作用",
    ],
}

_MATH_SUB_DISCIPLINES: dict[str, list[str]] = {
    "线性代数": ["矩阵", "向量", "行列式", "特征值", "线性变换", "线性空间", "秩"],
    "微积分": ["导数", "积分", "极限", "微分", "连续", "泰勒", "级数"],
    "概率论与数理统计": ["概率", "随机变量", "期望", "方差", "分布", "假设检验", "回归"],
    "离散数学": ["图论", "组合", "逻辑", "集合", "关系", "布尔"],
    "数学分析": ["实数", "收敛", "一致连续", "黎曼积分", "勒贝格"],
}

_CONTENT_TYPE_SIGNALS: dict[str, list[str]] = {
    "exam_paper": [
        "试卷", "考试", "满分", "答题", "选择题", "填空题", "解答题",
        "准考证", "考生", "作答", "分值",
    ],
    "lecture_notes": [
        "讲义", "课堂", "笔记", "板书", "教案",
    ],
    "textbook": [
        "教材", "课本", "章", "节", "习题", "例题", "定义", "定理",
    ],
}


def recognize_course_profile(
    *,
    course_id: str,
    source_packets: list[SourcePacket],
    section_packets: list[SectionPacket],
    fast_hints: FastTopicHints,
) -> CourseProfile:
    """Build a CourseProfile from material content signals.

    Course display names are intentionally ignored here. They are UI labels,
    not evidence about the material's discipline or learning target.
    """

    content_sample = _build_content_sample(source_packets, section_packets)

    discipline, sub_discipline = _detect_discipline(
        content_sample=content_sample,
        fast_hints=fast_hints,
    )

    content_type = _detect_content_type(content_sample, section_packets)

    difficulty_level = _detect_difficulty(content_sample, section_packets)

    key_topics = _extract_key_topics(fast_hints, section_packets, discipline)

    has_heavy_formulas = fast_hints.question_density < 0.5 and len(fast_hints.formula_patterns) > 5
    has_heavy_questions = fast_hints.question_density > 0.3
    has_heavy_diagrams = sum(1 for p in source_packets if p.has_images) > len(source_packets) * 0.5

    teaching_style_hint = _build_teaching_style_hint(
        discipline=discipline,
        content_type=content_type,
        has_heavy_formulas=has_heavy_formulas,
        has_heavy_questions=has_heavy_questions,
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
    """Build a representative content sample for keyword analysis."""

    parts: list[str] = []
    for packet in source_packets[:3]:
        parts.append(packet.normalized_content[:2000])
    for section in section_packets[:20]:
        parts.append(section.preview)
        parts.append(section.title)
        parts.append(section.header_path)
    return "\n".join(parts).lower()


def _detect_discipline(
    *,
    content_sample: str,
    fast_hints: FastTopicHints,
) -> tuple[str, str]:
    """Detect primary discipline and sub-discipline."""

    combined = content_sample.lower()
    for term, _ in fast_hints.high_freq_terms[:20]:
        combined += f" {term.lower()}"

    # Score each discipline
    scores: dict[str, int] = {}
    for discipline, keywords in _DISCIPLINE_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw.lower() in combined)
        if score > 0:
            scores[discipline] = score

    if not scores:
        return "", ""

    discipline = max(scores, key=lambda k: scores[k])

    # Detect sub-discipline for math
    sub_discipline = ""
    if discipline == "数学":
        sub_scores: dict[str, int] = {}
        for sub, keywords in _MATH_SUB_DISCIPLINES.items():
            sub_score = sum(1 for kw in keywords if kw.lower() in combined)
            if sub_score > 0:
                sub_scores[sub] = sub_score
        if sub_scores:
            sub_discipline = max(sub_scores, key=lambda k: sub_scores[k])

    return discipline, sub_discipline


def _detect_content_type(content_sample: str, section_packets: list[SectionPacket]) -> str:
    """Detect whether content is exam, textbook, lecture notes, or mixed."""

    scores: dict[str, int] = {}
    for content_type, signals in _CONTENT_TYPE_SIGNALS.items():
        score = sum(1 for signal in signals if signal in content_sample)
        if score > 0:
            scores[content_type] = score

    # Also check question density from section packets
    question_sections = sum(1 for p in section_packets if p.question_block_count > 0)
    if section_packets and question_sections / len(section_packets) > 0.4:
        scores["exam_paper"] = scores.get("exam_paper", 0) + 5

    if not scores:
        return "mixed"

    return max(scores, key=lambda k: scores[k])


def _detect_difficulty(content_sample: str, section_packets: list[SectionPacket]) -> str:
    """Estimate difficulty level from content signals."""

    advanced_signals = [
        "证明", "推导", "抽象", "泛函", "拓扑", "测度", "流形",
        "同构", "同态", "范畴", "伽罗瓦", "黎曼",
    ]
    intro_signals = [
        "基础", "入门", "初步", "简介", "概述", "基本概念",
    ]

    advanced_count = sum(1 for s in advanced_signals if s in content_sample)
    intro_count = sum(1 for s in intro_signals if s in content_sample)

    # Formula density as difficulty proxy
    avg_formulas = 0.0
    if section_packets:
        avg_formulas = sum(len(p.formula_refs) for p in section_packets) / len(section_packets)

    if advanced_count >= 3 or avg_formulas > 3.0:
        return "advanced"
    if intro_count >= 2 or avg_formulas < 0.5:
        return "introductory"
    return "intermediate"


def _extract_key_topics(
    fast_hints: FastTopicHints,
    section_packets: list[SectionPacket],
    discipline: str,
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


def _build_teaching_style_hint(
    *,
    discipline: str,
    content_type: str,
    has_heavy_formulas: bool,
    has_heavy_questions: bool,
) -> str:
    """Build a teaching style guidance string for the writer prompt."""

    hints: list[str] = []

    if discipline == "数学":
        hints.append("注重公式推导过程和直觉解释，用具体例子辅助抽象概念理解")
        if has_heavy_formulas:
            hints.append("公式密集型内容，确保每个关键公式都有清晰的推导或解释")
    elif discipline == "物理":
        hints.append("强调物理直觉和实验现象，公式推导与物理意义并重")
    elif discipline == "化学":
        hints.append("注重反应机理和实验现象的关联，结构式和方程式要准确")
    elif discipline == "计算机科学":
        hints.append("注重算法思路和代码实现的对应，用伪代码或流程图辅助说明")
    elif discipline == "经济学":
        hints.append("注重模型假设和现实应用的对比，图表辅助理解供需关系")

    if content_type == "exam_paper":
        hints.append("这是考试/试卷内容，重点整理题型分类、解题方法和易错点")
        if has_heavy_questions:
            hints.append("题目较多，按知识点归类整理，突出解题策略而非逐题罗列")
    elif content_type == "textbook":
        hints.append("教材内容，保持知识体系的完整性和逻辑递进")
    elif content_type == "lecture_notes":
        hints.append("讲义/笔记内容，补充必要的上下文和过渡，使内容自成体系")

    return "；".join(hints) if hints else ""
