"""Prompts for composing final planner build plans."""

from __future__ import annotations

from typing import Any

from app.workflows.digest.common.models import DigestMaterialContext
from app.workflows.digest.planner.lib.models import (
    PlanIntent,
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
    plan_intent: PlanIntent,
    message_history: list[str] | None = None,
    latest_plan: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    sketch = planner_brief.markdown.strip() or "暂无可见规划判断"
    plan_queries = "\n".join(f"- {item}" for item in plan_intent.plan_queries if item.strip()) or "- 暂无明确规划抓手"
    # 第一段会被 SSE 展示给用户；第二段是后端解析合同，两个协议不能混在一起写。
    prompt = f"""
请综合用户意图、资料上下文、思考过程和内部规划抓手，生成“计划说明 + 初步大纲”。
这份大纲是初稿，后续用户可以继续调整。

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

内部规划意图：
{plan_intent.plan_intent or "围绕用户目标和资料主线生成一份可调整的初步计划。"}

内部规划抓手：
{plan_queries}

Planner 阶段不会做本地/外部检索；不要编造来源、网站、论文或证据标题。

综合任务：
1. 用一段自然语言说明本计划要怎么组织资料和学习路线。
2. 生成一个可调整的初步大纲，不要暗示它已经最终确定。
3. 大纲章节要具体，key_points 要落到知识点、题型、方法或易错边界。

第一段：给用户看的计划说明
- 必须立即输出一段自然语言，不要使用标题、项目符号或编号。
- 风格类似：“本计划以三年级数学核心考点为主线，分四章推进：……”
- 必须说明组织主线和推进顺序，但不要列来源标题、网站名或检索词。
- 这一段会通过 SSE 展示给用户，所以要短、具体、有方向感。

第二段：给后端解析的 JSON 合同
- 必须从单独一行 {PLAN_JSON_MARKER} 开始。
- 随后输出一个合法 JSON 对象。
- 最后以 {PLAN_JSON_END_MARKER} 结束。
- JSON 只输出你新生成的信息，不要重复题目、目标、模式等上下文字段。
- JSON 只有两个字段：plan_text 和 chapters。
- plan_text 必须与第一段计划说明语义一致。

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
4. 不要把初步大纲写成不可更改的最终目录。

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
