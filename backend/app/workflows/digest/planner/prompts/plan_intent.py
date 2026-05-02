"""Prompts for planner intent and query-grab generation."""

from __future__ import annotations

from typing import Any

from app.workflows.digest.common.prompt_tracing import trace_prompt_build
from app.workflows.digest.common.models import DigestMaterialContext
from app.workflows.digest.planner.prompts.context import (
    render_latest_feedback,
    render_latest_plan,
    render_material_digest,
    render_material_overview,
    render_message_history,
    render_planner_context_mode,
)
from app.workflows.digest.planner.prompts.examples import render_plan_intent_examples
from app.workflows.digest.planner.lib.plans import planner_mode_label

PLAN_QUERY_MIN = 3
PLAN_QUERY_MAX = 8


def build_plan_intent_messages(
    *,
    course_name: str,
    user_prompt: str,
    digest_mode: str,
    material_context: DigestMaterialContext,
    message_history: list[str],
    latest_feedback: str | None = None,
    latest_plan: dict[str, Any] | None = None,
    existing_doc_context: str | None = None,
    planner_context_mode: str = "fresh_build",
) -> list[dict[str, str]]:
    # 这里只产出内部意图识别结果。它不直接展示给用户，只帮助计划合成器
    # 确定“用户想怎么学”和“该按什么问题去整理资料”。
    mode_label = planner_mode_label(digest_mode)
    context_mode_block = render_planner_context_mode(
        planner_context_mode=planner_context_mode,
        existing_doc_context=existing_doc_context,
    )
    system_prompt = """
你是 AITeachMe 的学习规划意图分析器。
你只输出合法 JSON，不输出 Markdown、解释、注释或额外文本。
规划意图合同只服务后续计划合成，不是对用户的最终展示，也不是外部检索承诺。
""".strip()
    prompt = f"""
请先识别用户学习意图，再把结果整理成内部规划意图合同。
规划意图合同不是最终展示内容，也不是外部检索承诺；它只用于后续生成“计划说明 + 初步大纲”。

课程/主题：{course_name}
用户提示：{user_prompt}
请求模式：{mode_label}

资料画像：
{render_material_overview(material_context)}

资料上下文：
{render_material_digest(material_context)}

{context_mode_block}

本轮最新输入/修改意见：
{render_latest_feedback(latest_feedback)}

上一版方案：
{render_latest_plan(latest_plan)}

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
2. plan_queries 输出 {PLAN_QUERY_MIN}-{PLAN_QUERY_MAX} 条，是给计划合成器的内部拆题抓手。
3. plan_queries 要服务意图识别结果，可以写知识簇、题型、方法、易错边界、应用场景或大纲拆分问题。
4. plan_queries 不要写成网站搜索词、来源列表或最终章节标题。
5. 如果用户意图不明确，就从资料形态和请求模式推断，但要保守表达。
6. 如果没有上传资料，就基于用户提示做通用意图识别，不要说“已上传资料显示/资料中包含”。
7. 若当前规划模式为已有文档重建/调整，plan_intent 和 plan_queries 必须围绕已有版本如何改造。
8. 如果本轮最新输入是在修改已有方案，必须判断这是对上一版的局部编辑还是整体重建；局部编辑只围绕被点名的章节或要求思考。
9. 不要输出来源名单、网站名、论文名、长解释、内部课程标识或重复内容。

示例：
{render_plan_intent_examples()}
""".strip()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]
    return trace_prompt_build(
        "planner_plan_intent",
        inputs={
            "course_name": course_name,
            "user_prompt_chars": len(user_prompt or ""),
            "digest_mode": digest_mode,
            "message_history_count": len(message_history),
            "latest_feedback_chars": len(latest_feedback or ""),
            "has_latest_plan": latest_plan is not None,
            "material_digest_chars": len(material_context.material_digest or ""),
            "plan_query_min": PLAN_QUERY_MIN,
            "plan_query_max": PLAN_QUERY_MAX,
            "planner_context_mode": planner_context_mode,
            "existing_doc_context_chars": len(existing_doc_context or ""),
        },
        output=messages,
    )


__all__ = ["build_plan_intent_messages"]
