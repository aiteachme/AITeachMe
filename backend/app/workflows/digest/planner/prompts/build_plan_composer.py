"""Prompts for composing final planner build plans."""

from __future__ import annotations

from typing import Any

from app.workflows.digest.common.models import DigestMaterialContext
from app.workflows.digest.planner.lib.models import (
    LearningIntent,
    PlannerBrief,
)
from app.workflows.digest.planner.prompts.context import (
    render_latest_plan,
    render_material_digest,
    render_material_overview,
    render_message_history,
)
from app.workflows.digest.planner.prompts.examples import render_composer_examples

PLAN_JSON_MARKER = "<PLAN_JSON>"
PLAN_JSON_END_MARKER = "</PLAN_JSON>"
COMPOSER_MESSAGE_HISTORY_BUDGET = 6


def build_plan_composer_messages(
    *,
    subject: str,
    user_goal: str,
    digest_mode: str,
    material_context: DigestMaterialContext,
    planner_brief: PlannerBrief,
    learning_intent: LearningIntent,
    message_history: list[str] | None = None,
    latest_plan: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    sketch = planner_brief.markdown.strip() or "暂无可见规划判断"
    focus_concepts = "、".join(learning_intent.focus_concepts) or "暂无明确概念清单"
    # 第一段会被 SSE 展示给用户；第二段是后端解析合同，两个协议不能混在一起写。
    prompt = f"""
请综合用户意图、可见思考过程和资料上下文，生成一份高度概括的知识文档构建计划。
你这一次输出两段：先给用户看的计划大纲，再给后端看的极简 JSON。

主题：{subject}
用户目标：{user_goal}
模式：{digest_mode}

资料画像：
{render_material_overview(material_context)}

资料上下文：
{render_material_digest(material_context)}

最近对话与修改意见：
{render_message_history(message_history, limit=COMPOSER_MESSAGE_HISTORY_BUDGET)}

上一版方案：
{render_latest_plan(latest_plan)}

可见规划判断：
{sketch}

意图类型：{learning_intent.goal_type}
目标受众：{learning_intent.audience}
成功标准：{'；'.join(learning_intent.success_criteria)}
约束：{'；'.join(learning_intent.constraints)}
意图识别出的核心概念：{focus_concepts}

Planner 阶段不会做本地/外部检索；不要编造来源、网站、论文或证据标题。

综合任务：
1. 判断资料到底在讲哪几个知识簇；
2. 判断哪些知识簇应该合并成一章，哪些应该拆开；
3. 判断每章应该更偏概念总结、题型突破、易错辨析还是速查复盘；
4. 直接产出用户想要的知识文档主线和章节安排。

第一段：给用户看的 Markdown 摘要
- 必须立即开始输出，不要先铺垫自然段。
- 用几条普通项目符号或编号列表说明知识文档主线、章节安排和每章抓手。
- 不要复述“我会阅读文档/检索来源/根据资料生成”，不要列来源标题。
- 这一段会通过 SSE 展示给用户，所以要自然、清楚、短。

第二段：给后端解析的 JSON 合同
- 必须从单独一行 {PLAN_JSON_MARKER} 开始。
- 随后输出一个合法 JSON 对象。
- 最后以 {PLAN_JSON_END_MARKER} 结束。
- JSON 只输出你新生成的信息，不要重复题目、目标、模式等上下文字段。
- JSON 只有两个字段：plan_text 和 chapters。

JSON 形状：
{{
  "plan_text": "一小段计划概括",
  "chapters": [
    {{
      "title": "具体章节标题",
      "key_points": ["本章要覆盖的知识点"]
    }}
  ]
}}

硬约束：
1. chapters 只写章节标题和知识点列表。
2. 不要输出检索词、来源、媒体计划、构建约束或后端已有字段。
3. JSON 段只能输出 JSON，不要放 Markdown 代码块、注释或尾随逗号。

请参考这些 few-shot 规律：
{render_composer_examples()}
""".strip()
    return [
        {"role": "system", "content": "你是 AITeachMe 的构建计划合成器，必须同时输出可见规划摘要和可解析 JSON。"},
        {"role": "user", "content": prompt},
    ]


__all__ = [
    "PLAN_JSON_END_MARKER",
    "PLAN_JSON_MARKER",
    "build_plan_composer_messages",
]
