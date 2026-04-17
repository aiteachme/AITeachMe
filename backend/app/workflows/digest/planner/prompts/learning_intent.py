"""Prompts for planner learning intent extraction."""

from __future__ import annotations

from app.workflows.digest.planner.lib.models import material_topic_hints
from app.workflows.digest.common.models import DigestMaterialContext


def _render_material_context(material_context: DigestMaterialContext) -> str:
    digest = (material_context.material_digest or "").strip()
    if not digest:
        return "暂无资料正文上下文"
    return digest


def build_learning_intent_messages(
    *,
    subject: str,
    user_goal: str,
    digest_mode: str,
    material_context: DigestMaterialContext,
    message_history: list[str],
    query_count: int,
) -> list[dict[str, str]]:
    topics = "、".join(material_topic_hints(material_context, limit=8)) or "暂无明显主题"
    history = "\n".join(f"- {item}" for item in message_history[-4:] if str(item).strip()) or "暂无补充意见"
    material_excerpt = _render_material_context(material_context)
    prompt = (
        "请把用户的学习目标解析成结构化学习意图，并给后续证据检索生成少量查询。\n\n"
        f"学科/主题：{subject}\n"
        f"用户目标：{user_goal}\n"
        f"请求模式：{digest_mode}\n"
        f"资料主题提示：{topics}\n"
        f"资料原文上下文（每份资料最多前 10000 tokens）：\n{material_excerpt}\n\n"
        f"最近对话：\n{history}\n\n"
        "字段要求：\n"
        "1. goal_type、audience、success_criteria、constraints、clarifying_questions 和 confidence 用于表达用户意图。\n"
        f"2. evidence_queries 输出 {query_count} 条中文检索查询，后端会用全部可用检索器执行。\n"
        "3. focus_concepts 输出 4-8 个资料中的关键概念、题型、公式、方法或易错边界。\n"
        "4. constraints 请输出短句列表，不要输出嵌套对象。\n"
        "5. 不要决定检索器、工具调用策略或来源名单，只生成学习意图和查询文本。"
    )
    return [
        {"role": "system", "content": "你是学习目标和检索查询分析器，只输出结构化结果。"},
        {"role": "user", "content": prompt},
    ]


__all__ = ["build_learning_intent_messages"]
