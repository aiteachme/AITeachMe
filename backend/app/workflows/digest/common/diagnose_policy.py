"""Translate planner diagnosis answers into concrete generation actions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _contains_any(text: str, markers: Sequence[str]) -> bool:
    return any(marker in text for marker in markers)


def diagnose_answer_action(
    answer: Any,
    *,
    question: Any = "",
    purpose: Any = "",
) -> str:
    """Return the concrete planner/docgen action implied by one diagnosis answer."""

    answer_text = _clean_text(answer)
    context_text = " ".join(
        item for item in [_clean_text(question), _clean_text(purpose), answer_text] if item
    )
    if not answer_text:
        return ""

    if _contains_any(answer_text, ("只给要点", "答案要点", "要点精简")):
        return "DocGen 在例题、练习和章末小测中只保留答案要点和关键依据，减少长步骤。"
    if _contains_any(answer_text, ("步骤解析", "写清依据", "步骤", "依据")):
        return "DocGen 在例题、练习和章末小测中写出分步依据、检查点和答案判定口径。"
    if _contains_any(answer_text, ("错因", "易错", "误区", "反例")):
        return "Planner 在章节要点中保留具体易错对象；DocGen 增加 pitfall_targets、错因提醒和反例/边界辨析。"
    if _contains_any(answer_text, ("变式", "迁移", "举一反三")):
        return "Planner 保留变式训练需求；DocGen 在 example_coverage_plan 或 chapter_end_practice_plan 安排同目标变式检查。"
    if _contains_any(answer_text, ("章末小测", "每节小练", "小练", "小测", "少量精练", "多练")):
        return "Planner 调整练习/小测密度；DocGen 改变随堂练习和章末小测的数量、覆盖范围与解析密度。"
    if _contains_any(answer_text, ("基础", "入门", "补课", "零基础", "先补")):
        return "Planner 增加前置铺垫并降低首批例题难度；DocGen 先补概念边界和低门槛示例。"
    if _contains_any(answer_text, ("概念", "定义", "原理")):
        return "Planner 和 DocGen 优先讲清定义边界、概念关系和最小反例，再进入题型。"
    if _contains_any(answer_text, ("例题", "案例", "带路")):
        return "Planner 和 DocGen 增加 worked example/案例带路，并把关键方法落到 example_coverage_plan。"
    if _contains_any(context_text, ("解析", "答案", "判定", "订正")):
        return "DocGen 按该选择调整文档内例题、练习和章末小测的答案、依据、错因或订正写法。"
    return "Planner 和 DocGen 必须把该选择转成章节顺序、讲解起点、例题、练习、解析或章末小测配置的可见差异。"


def render_diagnose_action_policy(
    items: Sequence[Mapping[str, Any]] | None,
    *,
    status: str = "",
    limit: int = 5,
) -> str:
    """Render answered diagnosis choices as prompt-visible execution policies."""

    if _clean_text(status) == "skipped":
        return "用户跳过前置诊断：不要虚构诊断偏好，按 confirmed plan 和资料边界生成。"

    lines: list[str] = []
    for raw in list(items or [])[:limit]:
        if not isinstance(raw, Mapping):
            continue
        question = _clean_text(raw.get("question"))
        answer = _clean_text(raw.get("answer"))
        if not answer:
            continue
        purpose = _clean_text(raw.get("purpose"))
        purpose_text = purpose.removeprefix("文档落点：").removeprefix("文档落点:").strip()
        action = diagnose_answer_action(answer, question=question, purpose=purpose)
        question_text = question or "诊断问题"
        purpose_part = f"；文档落点：{purpose_text}" if purpose_text else ""
        lines.append(f"- {question_text}：选择“{answer}”{purpose_part}；执行策略：{action}")

    if not lines:
        return "暂无已回答诊断选项：不要编造诊断偏好。"
    return "\n".join(lines)


__all__ = ["diagnose_answer_action", "render_diagnose_action_policy"]
