"""Checker / Rubric 框架 — 自动判卷与评分。

支持多种判定方式：精确匹配、关键词匹配、LLM 语义判定。

对外使用::

    from app.shared.infra.checker import check_answer, load_rubric

    rubric = load_rubric("math/eigenvalue")
    result = await check_answer(
        question="求矩阵 A 的特征值",
        student_answer="λ = 2, 3",
        expected="λ = 2, 3",
        rubric=rubric,
    )
    print(result.passed, result.score, result.feedback)
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger()


# ── 数据结构 ──────────────────────────────────────────────────


@dataclass
class RubricCriterion:
    """评分标准的单个维度。"""

    name: str
    weight: float = 1.0
    description: str = ""


@dataclass
class CommonMistake:
    """常见错误模式。"""

    pattern: str
    feedback: str
    deduction: float = 0.0


@dataclass
class Rubric:
    """评分标准（rubric）。"""

    full_marks: float = 10.0
    criteria: list[RubricCriterion] = field(default_factory=list)
    common_mistakes: list[CommonMistake] = field(default_factory=list)
    pass_threshold: float = 0.6
    grading_prompt: str = ""   # 可选：自定义 LLM 判卷提示词


@dataclass
class CheckResult:
    """判定结果。"""

    passed: bool
    score: float
    full_marks: float
    feedback: str
    matched_mistakes: list[str] = field(default_factory=list)
    criteria_scores: dict[str, float] = field(default_factory=dict)


# ── 判定策略 ──────────────────────────────────────────────────


async def check_exact(
    student_answer: str,
    expected: str,
    *,
    rubric: Rubric | None = None,
) -> CheckResult:
    """精确匹配判定（忽略空格和大小写）。"""

    norm_student = student_answer.strip().lower()
    norm_expected = expected.strip().lower()
    passed = norm_student == norm_expected
    full = rubric.full_marks if rubric else 10.0

    return CheckResult(
        passed=passed,
        score=full if passed else 0.0,
        full_marks=full,
        feedback="回答正确！" if passed else f"答案不正确。参考答案：{expected}",
    )


async def check_keywords(
    student_answer: str,
    expected: str,
    *,
    rubric: Rubric | None = None,
) -> CheckResult:
    """关键词匹配判定。"""

    keywords = [k.strip() for k in expected.split(",") if k.strip()]
    answer_lower = student_answer.lower()
    hits = [k for k in keywords if k.lower() in answer_lower]

    full = rubric.full_marks if rubric else 10.0
    ratio = len(hits) / max(len(keywords), 1)
    score = round(full * ratio, 1)
    threshold = rubric.pass_threshold if rubric else 0.6
    passed = ratio >= threshold

    # 检查常见错误
    matched_mistakes = []
    if rubric:
        for mistake in rubric.common_mistakes:
            if mistake.pattern.lower() in answer_lower:
                matched_mistakes.append(mistake.feedback)
                score = max(0, score - mistake.deduction)

    if passed:
        fb = "回答正确！" if ratio == 1.0 else f"基本正确，命中关键词 {len(hits)}/{len(keywords)}"
    else:
        missing = [k for k in keywords if k.lower() not in answer_lower]
        fb = f"不完整。缺少关键点：{'、'.join(missing[:3])}"

    return CheckResult(
        passed=passed,
        score=score,
        full_marks=full,
        feedback=fb,
        matched_mistakes=matched_mistakes,
    )


# BUG-6 FIX: 剥离大模型常见的 Markdown 代码块包裹和前缀后缀杂言
_JSON_FENCE_RE = re.compile(
    r"```(?:json)?\s*\n?(.*?)\n?\s*```", re.DOTALL
)


def _clean_json_payload(raw: str) -> str:
    """清洗 LLM 返回的 JSON：去除 Markdown 代码围栏和前后缀杂言。"""
    # 1. 尝试提取 ```json ... ``` 代码块内容
    match = _JSON_FENCE_RE.search(raw)
    if match:
        return match.group(1).strip()
    # 2. 尝试找到第一个 { 和最后一个 } 之间的内容
    first_brace = raw.find("{")
    last_brace = raw.rfind("}")
    if first_brace != -1 and last_brace > first_brace:
        return raw[first_brace : last_brace + 1]
    # 3. 原样返回（后续 json.loads 会报错，由调用方处理）
    return raw.strip()


async def check_with_llm(
    question: str,
    student_answer: str,
    expected: str,
    *,
    rubric: Rubric | None = None,
) -> CheckResult:
    """LLM 语义判定 — 适用于简答题、论述题。"""

    full = rubric.full_marks if rubric else 10.0

    prompt = rubric.grading_prompt if rubric and rubric.grading_prompt else ""
    if not prompt:
        criteria_text = ""
        if rubric and rubric.criteria:
            criteria_text = "\n评分维度：\n" + "\n".join(
                f"- {c.name}（权重{c.weight}）：{c.description}" for c in rubric.criteria
            )
        prompt = f"""你是一位专业教师，请批改以下作答。

题目：{question}
参考答案：{expected}
学生作答：{student_answer}
{criteria_text}

请严格按以下 JSON 格式返回（不要额外文字）：
{{"score": 得分(0~{full}), "passed": true/false, "feedback": "一句话反馈", "criteria_scores": {{"维度名": 得分}}}}"""

    try:
        from app.shared.infra.llm_support import acompletion

        raw = await acompletion(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            response_format={"type": "json_object"},
        )
    except Exception as exc:
        # LLM 调用本身失败（网络/超时），退回关键词匹配
        logger.warning("llm_grading_call_failed", error=str(exc))
        return await check_keywords(student_answer, expected, rubric=rubric)

    # 解析 LLM 返回的 JSON
    try:
        cleaned = _clean_json_payload(raw)
        parsed = json.loads(cleaned)
        return CheckResult(
            passed=parsed.get("passed", False),
            score=float(parsed.get("score", 0)),
            full_marks=full,
            feedback=parsed.get("feedback", ""),
            criteria_scores=parsed.get("criteria_scores", {}),
        )
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        # JSON 解析失败，说明模型吐了非标格式，退回关键词但记录警告
        logger.warning(
            "llm_grading_json_parse_failed",
            raw_preview=raw[:200],
            error=str(exc),
        )
        return await check_keywords(student_answer, expected, rubric=rubric)


# ── 统一入口 ──────────────────────────────────────────────────


async def check_answer(
    *,
    question: str = "",
    student_answer: str,
    expected: str,
    rubric: Rubric | None = None,
    strategy: str = "auto",
) -> CheckResult:
    """判定学生作答（统一入口）。

    Args:
        question: 题目文本。
        student_answer: 学生答案。
        expected: 参考答案。
        rubric: 评分标准。
        strategy: 判定策略（"exact" / "keywords" / "llm" / "auto"）。

    Returns:
        CheckResult 对象。

    Example::

        result = await check_answer(
            question="HTTP 状态码 200 表示什么？",
            student_answer="请求成功",
            expected="请求成功,OK,正常",
            strategy="keywords",
        )
    """

    if strategy == "exact":
        return await check_exact(student_answer, expected, rubric=rubric)
    elif strategy == "keywords":
        return await check_keywords(student_answer, expected, rubric=rubric)
    elif strategy == "llm":
        return await check_with_llm(question, student_answer, expected, rubric=rubric)
    else:
        # auto: 短答案用精确匹配，中答案用关键词，长答案用 LLM
        if len(student_answer) < 20 and "," not in expected:
            return await check_exact(student_answer, expected, rubric=rubric)
        elif len(student_answer) < 200:
            return await check_keywords(student_answer, expected, rubric=rubric)
        else:
            return await check_with_llm(
                question, student_answer, expected, rubric=rubric,
            )


def load_rubric(path_or_name: str) -> Rubric | None:
    """加载评分标准。

    支持：
    - 文件路径（JSON）
    - 名称（从 backend/rubrics/ 目录查找）

    Args:
        path_or_name: 文件路径或 rubric 名称。

    Returns:
        Rubric 对象，文件不存在则返回 None。
    """

    # 尝试直接路径
    p = Path(path_or_name)
    if not p.exists():
        # 从 backend/rubrics/ 查找
        base = Path(__file__).parent.parent.parent / "rubrics"
        p = base / f"{path_or_name}.json"
    if not p.exists():
        return None

    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        criteria = [
            RubricCriterion(**c) for c in data.get("criteria", [])
        ]
        mistakes = [
            CommonMistake(**m) for m in data.get("common_mistakes", [])
        ]
        return Rubric(
            full_marks=data.get("full_marks", 10.0),
            criteria=criteria,
            common_mistakes=mistakes,
            pass_threshold=data.get("pass_threshold", 0.6),
            grading_prompt=data.get("grading_prompt", ""),
        )
    except Exception as exc:
        logger.warning("rubric_load_failed", path=str(p), error=str(exc))
        return None
