"""Prompts for planner intent and query-grab generation."""

from __future__ import annotations

from app.workflows.digest.common.models import DigestMaterialContext
from app.workflows.digest.planner.prompts.context import (
    render_material_digest,
    render_material_overview,
    render_message_history,
)
from app.workflows.digest.planner.prompts.examples import DEFAULT_INTENT_EXAMPLE_LIMIT, render_plan_intent_examples

PLAN_QUERY_MIN = 3
PLAN_QUERY_MAX = 8


def build_plan_intent_messages(
    *,
    subject: str,
    user_goal: str,
    digest_mode: str,
    material_context: DigestMaterialContext,
    message_history: list[str],
) -> list[dict[str, str]]:
    # 这里只产出内部意图识别结果。它不直接展示给用户，只帮助 composer
    # 确定“用户想怎么学”和“该按什么问题去整理资料”。
    prompt = f"""
请先识别用户学习意图，再把结果整理成内部 PlanIntent。
PlanIntent 不是最终展示内容，也不是外部检索承诺；它只用于后续生成“计划说明 + 初步大纲”。

学科/主题：{subject}
用户目标：{user_goal}
请求模式：{digest_mode}

资料画像：
{render_material_overview(material_context)}

资料上下文：
{render_material_digest(material_context)}

最近对话：
{render_message_history(message_history)}

只输出合法 JSON：
{{
  "plan_intent": "一小段内部规划意图",
  "plan_queries": ["{PLAN_QUERY_MIN}-{PLAN_QUERY_MAX} 条用于后续综合大纲的整理抓手"]
}}

字段要求：
1. plan_intent 不超过 140 字，必须同时说明：
   - 用户意图：冲刺复习、系统学习、题型突破、速查复盘、入门理解等；
   - 产出用途：用来备考、复习、补弱、建立体系或快速查漏；
   - 组织主线：资料应该按知识簇、题型、概念依赖、易错点或应用场景来整理。
2. plan_queries 输出 {PLAN_QUERY_MIN}-{PLAN_QUERY_MAX} 条，是给 composer 的内部拆题抓手。
3. plan_queries 要服务意图识别结果，可以写知识簇、题型、方法、易错边界、应用场景或大纲拆分问题。
4. plan_queries 不要写成网站搜索词、来源列表或最终章节标题。
5. 如果用户意图不明确，就从资料形态和请求模式推断，但要保守表达。
6. 如果没有上传资料，就基于用户目标做通用意图识别，不要说“已上传资料显示/资料中包含”。
7. 不要输出来源名单、网站名、论文名、长解释、subject id 或重复内容。

few-shot 示例：
{render_plan_intent_examples(limit=DEFAULT_INTENT_EXAMPLE_LIMIT)}
""".strip()
    return [
        {"role": "system", "content": "你是学习规划意图分析器，只输出合法 JSON。"},
        {"role": "user", "content": prompt},
    ]


__all__ = ["build_plan_intent_messages"]
