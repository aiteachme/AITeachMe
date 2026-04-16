"""Prompts for planner learning intent extraction."""

from __future__ import annotations

from app.workflows.digest.planner.lib.models import material_topic_hints
from app.workflows.digest.common.models import DigestMaterialContext


_MAX_DIGEST_CHARS = 4000


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
        "请把用户的学习目标解析成结构化学习意图。\n\n"
        f"学科/主题：{subject}\n"
        f"用户目标：{user_goal}\n"
        f"请求模式：{digest_mode}\n"
        f"资料主题提示：{topics}\n"
        f"资料摘要：\n{digest}\n\n"
        f"最近对话：\n{history}\n\n"
        "只需要判断目标类型、受众、成功标准、约束和是否需要追问。"
        "不要决定检索器、检索词或工具调用策略；证据探测由后端代码根据资料画像统一处理。"
    )
    return [
        {"role": "system", "content": "你是学习目标分析器，只输出结构化结果。"},
        {"role": "user", "content": prompt},
    ]


__all__ = ["build_learning_intent_messages"]
