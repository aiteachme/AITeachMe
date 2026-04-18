"""Prompts for planner intent and query-grab generation."""

from __future__ import annotations

from app.workflows.digest.common.models import DigestMaterialContext
from app.workflows.digest.planner.prompts.context import (
    render_material_digest,
    render_material_overview,
    render_message_history,
)


def build_plan_intent_messages(
    *,
    subject: str,
    user_goal: str,
    digest_mode: str,
    material_context: DigestMaterialContext,
    message_history: list[str],
) -> list[dict[str, str]]:
    # 这个 prompt 只生成内部抓手，用户最终只看到综合节点生成的计划和初步大纲。
    prompt = f"""
请把用户学习目标和资料上下文整理成内部规划意图。
Planner 阶段不会真实执行外部检索；这里的 queries 是后续综合大纲时使用的“整理/搜索抓手”。

学科/主题：{subject}
用户目标：{user_goal}
请求模式：{digest_mode}

资料画像：
{render_material_overview(material_context)}

资料上下文：
{render_material_digest(material_context)}

最近对话：
{render_message_history(message_history)}

请只输出合法 JSON：
{{
  "plan_intent": "一小段内部规划意图",
  "plan_queries": ["3-8 条用于后续综合大纲的整理抓手"]
}}

字段要求：
1. plan_intent 不超过 120 字，必须说明本次计划主要按什么主线组织。
2. plan_queries 输出 3-8 条，必须具体到知识簇、题型、方法、易错边界或应用场景。
3. plan_queries 不是对用户展示的最终内容，也不是承诺真实检索；它们只是综合节点的内部抓手。
4. 不要输出来源名单、网站名、论文名、长解释或重复内容。
""".strip()
    return [
        {"role": "system", "content": "你是学习规划意图分析器，只输出合法 JSON。"},
        {"role": "user", "content": prompt},
    ]


__all__ = ["build_plan_intent_messages"]
