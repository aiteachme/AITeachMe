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
    prompt = (
        "请综合用户意图、可见思考过程和资料上下文，生成一份高度概括的知识文档构建计划。\n"
        "你这一次输出两段：先给用户看的计划大纲，再给后端看的极简 JSON。\n\n"
        f"主题：{subject}\n"
        f"用户目标：{user_goal}\n"
        f"模式：{digest_mode}\n"
        f"资料画像：\n{render_material_overview(material_context)}\n\n"
        f"资料上下文：\n{render_material_digest(material_context)}\n\n"
        f"最近对话与修改意见：\n{render_message_history(message_history, limit=6)}\n\n"
        f"上一版方案：\n{render_latest_plan(latest_plan)}\n\n"
        f"可见规划判断：\n{sketch}\n\n"
        f"意图类型：{learning_intent.goal_type}\n"
        f"目标受众：{learning_intent.audience}\n"
        f"成功标准：{'；'.join(learning_intent.success_criteria)}\n"
        f"约束：{'；'.join(learning_intent.constraints)}\n"
        f"意图识别出的核心概念：{focus_concepts}\n\n"
        "Planner 阶段不会做本地/外部检索；不要编造来源、网站、论文或证据标题。\n\n"
        "你不是在描述“读了什么文档”，也不是把草稿、意图和资料逐段拼接。你需要先完成真正的综合：\n"
        "1. 判断资料到底在讲哪几个知识簇；\n"
        "2. 判断哪些知识簇应该合并成一章，哪些应该拆开；\n"
        "3. 判断每章应该更偏概念总结、题型突破、易错辨析还是速查复盘；\n"
        "4. 直接产出用户想要的知识文档主线和章节安排。\n\n"
        "输出格式必须严格分两段：\n"
        "第一段先输出给用户看的 Markdown 分点内容，必须立即开始输出，不要先铺垫自然段。\n"
        "用几条普通项目符号或编号列表，说明用户最终会得到的知识文档主线、章节安排和每章抓手。\n"
        "不要复述“我会阅读文档/检索来源/根据资料生成”，不要列来源标题。\n"
        "这一段会通过 SSE 展示给用户，所以要自然、清楚、短。\n\n"
        f"第二段必须从单独一行 {PLAN_JSON_MARKER} 开始，随后输出一个合法 JSON 对象，最后以 {PLAN_JSON_END_MARKER} 结束。\n"
        "JSON 只输出你新生成的信息，不要重复题目、目标、模式等上下文字段。\n"
        "JSON 只有两个字段：plan_text 和 chapters。\n\n"
        "JSON 形状：\n"
        "{\n"
        '  "plan_text": "一小段计划概括",\n'
        '  "chapters": [\n'
        "    {\n"
        '      "title": "具体章节标题",\n'
        '      "key_points": ["本章要覆盖的知识点"]\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        "硬约束：\n"
        "1. chapters 只写章节标题和知识点列表。\n"
        "2. 不要输出检索词、来源、媒体计划、构建约束或后端已有字段。\n"
        "3. JSON 段只能输出 JSON，不要放 Markdown 代码块、注释或尾随逗号。\n\n"
        "请参考这些 few-shot 规律：\n"
        f"{render_composer_examples()}"
    )
    return [
        {"role": "system", "content": "你是 AITeachMe 的构建计划合成器，必须同时输出可见规划摘要和可解析 JSON。"},
        {"role": "user", "content": prompt},
    ]


__all__ = [
    "PLAN_JSON_END_MARKER",
    "PLAN_JSON_MARKER",
    "build_plan_composer_messages",
]
