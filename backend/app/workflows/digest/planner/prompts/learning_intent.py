"""Prompts for planner learning intent extraction."""

from __future__ import annotations

from app.workflows.digest.planner.lib.research_probe import material_topic_hints
from app.workflows.digest.common.models import DigestMaterialContext


_MAX_DIGEST_CHARS = 2000


def _render_material_digest(material_context: DigestMaterialContext) -> str:
    digest = (material_context.material_digest or "").strip()
    if not digest:
        return "暂无资料摘要"
    if len(digest) <= _MAX_DIGEST_CHARS:
        return digest
    return digest[: _MAX_DIGEST_CHARS - 1].rstrip() + "…"


def build_learning_intent_messages(
    *,
    subject: str,
    user_goal: str,
    digest_mode: str,
    material_context: DigestMaterialContext,
    message_history: list[str],
) -> list[dict[str, str]]:
    topics = "、".join(material_topic_hints(material_context, limit=8)) or "暂无明显主题"
    history = "\n".join(f"- {item}" for item in message_history[-4:] if str(item).strip()) or "暂无补充意见"
    digest = _render_material_digest(material_context)
    prompt = (
        "请把用户的学习目标解析成结构化意图和检索计划。\n\n"
        f"学科/主题：{subject}\n"
        f"用户目标：{user_goal}\n"
        f"请求模式：{digest_mode}\n"
        f"资料主题提示：{topics}\n"
        f"资料摘要：\n{digest}\n\n"
        f"最近对话：\n{history}\n\n"
        "请优先本地资料，只有本地资料不足时才建议外部搜索。"
        "检索词要具体，不能是空泛的“学习资料”“相关知识”，"
        "要从资料摘要里挑出真正需要校准的概念边界。"
    )
    return [
        {"role": "system", "content": "你是学习目标分析器，只输出结构化结果。"},
        {"role": "user", "content": prompt},
    ]


__all__ = ["build_learning_intent_messages"]
