"""Prompts for planner learning intent extraction."""

from __future__ import annotations

from app.workflows.digest.common.models import DigestMaterialContext
from app.workflows.digest.planner.prompts.context import (
    render_material_digest,
    render_material_overview,
    render_message_history,
)


def build_learning_intent_messages(
    *,
    subject: str,
    user_goal: str,
    digest_mode: str,
    material_context: DigestMaterialContext,
    message_history: list[str],
) -> list[dict[str, str]]:
    # 这个 prompt 只做意图归纳，不让模型提前承诺检索或写作细节。
    prompt = f"""
请把用户学习目标解析成极简结构化意图。Planner 阶段不做检索。

学科/主题：{subject}
用户目标：{user_goal}
请求模式：{digest_mode}

资料画像：
{render_material_overview(material_context)}

资料上下文：
{render_material_digest(material_context)}

最近对话：
{render_message_history(message_history)}

字段要求：
1. goal_type 用短枚举风格，例如 exam_sprint / systematic_learning / concept_review。
2. success_criteria 最多 3 条，constraints 最多 4 条。
3. focus_concepts 输出 4-8 个资料中最关键的概念、题型、公式、方法或易错边界。
4. 不要输出来源名单、检索器策略、长解释或重复内容。
""".strip()
    return [
        {"role": "system", "content": "你是学习目标分析器，只输出短小结构化结果。"},
        {"role": "user", "content": prompt},
    ]


__all__ = ["build_learning_intent_messages"]
