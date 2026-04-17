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
) -> list[dict[str, str]]:
    topics = "、".join(material_topic_hints(material_context)) or "暂无明显主题"
    history = "\n".join(f"- {item}" for item in message_history[-4:] if str(item).strip()) or "暂无补充意见"
    material_excerpt = _render_material_context(material_context)
    prompt = (
        "请把用户学习目标解析成极简结构化意图。Planner 阶段不做检索。\n\n"
        f"学科/主题：{subject}\n"
        f"用户目标：{user_goal}\n"
        f"请求模式：{digest_mode}\n"
        f"资料主题提示：{topics}\n"
        f"资料上下文：\n{material_excerpt}\n\n"
        f"最近对话：\n{history}\n\n"
        "字段要求：\n"
        "1. goal_type 用短枚举风格，例如 exam_sprint / systematic_learning / concept_review。\n"
        "2. success_criteria 最多 3 条，constraints 最多 4 条，clarifying_questions 最多 2 条。\n"
        "3. focus_concepts 输出 4-8 个资料中最关键的概念、题型、公式、方法或易错边界。\n"
        "4. 不要输出来源名单、检索器策略、长解释或重复内容。"
    )
    return [
        {"role": "system", "content": "你是学习目标分析器，只输出短小结构化结果。"},
        {"role": "user", "content": prompt},
    ]


__all__ = ["build_learning_intent_messages"]
