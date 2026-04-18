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
DEFAULT_PLAN_INTENT = "围绕用户目标和资料主线，先整理资料边界，再生成可调整的初步大纲。"


def _render_plan_queries(plan_intent: PlanIntent) -> str:
    queries = [item.strip() for item in plan_intent.plan_queries if item.strip()]
    if not queries:
        return "- 暂无明确规划抓手"
    return "\n".join(f"- {item}" for item in queries)


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
    plan_queries = _render_plan_queries(plan_intent)
    plan_intent_text = plan_intent.plan_intent.strip() or DEFAULT_PLAN_INTENT
    # 第一段是用户会看到的 plan_text；JSON 是机器合同。这里把协议写清楚，
    # 避免模型把 hidden JSON 当成 Markdown 继续流给前端。
    prompt = f"""
你要生成一份构建前计划，分成两层：
1. 计划说明：像深度研究开始前的行动计划，说明接下来会如何整理资料、拆分问题、形成初步大纲。
2. 计划步骤和初步大纲：计划步骤拆出可检查动作；初步大纲给出可以继续调整的章节草案。

注意：Planner 阶段不会真实执行外部检索，不要编造来源、网站、论文或证据标题。

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
{plan_intent_text}

内部规划抓手：
{plan_queries}

可见输出要求：
- 先立即输出一段计划说明，不要标题、编号、项目符号。
- 计划说明控制在 140-320 字，重点写“我会先……再……最后……”，不要把所有章节和知识点挤进去。
- 计划说明要表达这是初步方案，后续可以调整。

隐藏 JSON 要求：
- 计划说明结束后，从单独一行 {PLAN_JSON_MARKER} 开始。
- 输出合法 JSON 对象，最后以 {PLAN_JSON_END_MARKER} 结束。
- JSON 只有 plan_text、plan_steps、chapters 三个字段。
- plan_text 与可见计划说明语义一致。
- plan_steps 是 3-5 条动作步骤，用来解释本计划会如何整理资料、判断优先级和形成大纲。

JSON 形状：
{{
  "plan_text": "一小段计划概括",
  "plan_steps": ["先做什么", "再做什么", "最后产出什么"],
  "chapters": [
    {{
      "title": "具体章节标题",
      "key_points": ["本章要覆盖的知识点"]
    }}
  ]
}}

硬约束：
1. plan_steps 只写动作，不写章节名堆叠，也不要写“搜索网站/查论文”等外部检索承诺。
2. chapters 只写章节标题和知识点列表。
3. chapters 要具体，key_points 落到知识点、题型、方法或易错边界。
4. 不要输出检索词、来源、媒体计划、构建约束或后端已有字段。
5. JSON 段只能输出 JSON，不要放 Markdown 代码块、注释或尾随逗号。
6. 不要把初步大纲写成不可更改的最终目录。
7. 不要在输出中提到 Deep Research、OpenAI、Gemini 等产品名。
8. 如果某个知识点只是在内部抓手里出现，但资料上下文不支持，降低确定性表达。

few-shot 规律：
{render_composer_examples()}
""".strip()
    return [
        {"role": "system", "content": "你是 AITeachMe 的构建计划合成器，必须同时输出可见计划说明和可解析 JSON。"},
        {"role": "user", "content": prompt},
    ]


__all__ = [
    "PLAN_JSON_END_MARKER",
    "PLAN_JSON_MARKER",
    "build_plan_composer_messages",
]
