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
from app.workflows.digest.planner.prompts.examples import DEFAULT_COMPOSER_EXAMPLE_LIMIT, render_composer_examples

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
    # 第一段是用户会看到的 plan_text；JSON 是机器合同。这里允许写
    # “拟查询/对照/搜集”的研究动作，但不能写成已经完成检索。
    prompt = f"""
你要生成一份构建前研究计划，分成三层：
1. 计划说明：用一段话说明接下来会如何查找、对照、整理和判断，不要提前展开章节内容。
2. 计划步骤：拆出 4-7 条可检查动作，可以包含“查询、对照、搜集、调研、归并、筛选、整理”等动作。
3. 初步大纲：只给粗颗粒章节骨架，后续还会继续调整，不要写得像最终目录。

重要边界：
- Planner 现在只制定研究/整理计划，不代表已经执行检索。
- 可以写“后续会查询/对照/搜集哪些方向”，不要写“已经查到/来源显示/某网站或某论文指出”。

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
- 计划说明控制在 140-320 字，重点写“我会先查什么/对照什么，再怎么整理和判断”。
- 计划说明不要列章节标题，不要提前写大纲内容；只表达研究路线和判断方法。

隐藏 JSON 要求：
- 计划说明结束后，从单独一行 {PLAN_JSON_MARKER} 开始。
- 输出合法 JSON 对象，最后以 {PLAN_JSON_END_MARKER} 结束。
- JSON 只有 plan_text、plan_steps、chapters 三个字段。
- plan_text 与可见计划说明语义一致。
- plan_steps 是 4-7 条动作步骤，用来解释本计划会查询什么、整理什么、判断什么、如何形成大纲。
- chapters 是很初步的粗颗粒骨架，不追求完整和细节。

JSON 形状：
{{
  "plan_text": "一小段计划概括",
  "plan_steps": ["查询或对照什么", "归并或筛选什么", "整理什么", "形成什么"],
  "chapters": [
    {{
      "title": "高度概括的章节方向",
      "key_points": ["本章后续要继续细化的方向"]
    }}
  ]
}}

格式约束：
- JSON 段只能输出 JSON，不要放 Markdown 代码块、注释或尾随逗号。
- chapters 只写高度概括的章节方向和 key_points，不要放来源、媒体计划、构建约束或后端字段。

内容边界：
- plan_steps 可以写“查询/对照/搜集/调研”的计划动作，但不能说已经完成检索。
- plan_text 和 plan_steps 是重点，不能被 chapters 反客为主。
- 没有上传资料时，基于用户目标生成通用初步计划，不要声称读过具体文件。
- 初步大纲保持概括，key_points 控制为 2-4 个方向，不要塞满细碎知识点。

few-shot 规律：
{render_composer_examples(limit=DEFAULT_COMPOSER_EXAMPLE_LIMIT)}
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
