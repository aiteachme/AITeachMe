"""Translate planner diagnosis answers into concrete generation actions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


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
        question_text = question or "诊断问题"
        purpose_part = f"；文档落点：{purpose_text}" if purpose_text else ""
        lines.append(f"- {question_text}：选择“{answer}”{purpose_part}")

    if not lines:
        return "暂无已回答诊断选项：不要编造诊断偏好。"
    return "\n".join(lines)


__all__ = ["render_diagnose_action_policy"]
