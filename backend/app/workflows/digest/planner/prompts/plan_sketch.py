"""Prompts for planner plan sketch streaming."""

from __future__ import annotations

from app.workflows.digest.common.prompt_tracing import trace_prompt_build
from app.workflows.digest.planner.prompts.examples import render_plan_sketch_examples
from app.workflows.digest.common.models import DigestMaterialContext
from app.workflows.digest.planner.prompts.context import (
    render_material_digest,
    render_material_overview,
    render_message_history,
)
from app.workflows.digest.planner.lib.plans import planner_mode_label


def build_plan_sketch_prompt(
    *,
    course_name: str,
    user_prompt: str,
    digest_mode: str,
    material_context: DigestMaterialContext,
    message_history: list[str],
) -> str:
    # sketch 是流式展示的“正在理解中”，不是最终计划。最终卡片只使用
    # composer 生成的计划说明和初步大纲。
    mode_label = planner_mode_label(digest_mode)
    prompt = f"""
你是 AITeachMe 的学习规划助手。请先输出一段自然的思考过程，让用户知道你正在如何理解资料。
不要输出正式计划，不要输出初步大纲，也不要写知识文档正文。

课程/主题：{course_name}
用户提示：{user_prompt}
模式：{mode_label}

资料画像：
{render_material_overview(material_context)}

资料上下文：
{render_material_digest(material_context)}

最近对话：
{render_message_history(message_history)}

输出 3-5 段自然短句，围绕四件事：
1. 资料大概覆盖什么边界；
2. 用户当前更像哪类学习意图；
3. 哪些内容可能需要归并或拆开；
4. 下一步计划会优先解决什么学习问题。

硬约束：
1. 不要输出固定模板，不要写“资料判断/关注重点/预计计划大纲/待确认点”这种标签。
2. 不允许输出 #、##、代码块、JSON、网站名、来源标题、内部课程 ID 标识。
3. 不要写空泛表达，例如“梳理基础”“强化理解”“提升能力”；要落到资料里的具体对象或学习动作。
4. 不要列正式章节目录；最终计划和初步大纲会在下一步单独生成。
5. 全文控制在 260-520 字以内，宁可把判断原因讲清楚，不要铺陈。
6. 如果没有上传资料，只能基于用户提示和课程常识判断，不要写“这批资料显示/资料里包含”。

请参考下面这些示例的自然表达，注意它们都是“思考过程”示例，不是最终方案：

{render_plan_sketch_examples()}
""".strip()
    return trace_prompt_build(
        "planner_plan_sketch",
        inputs={
            "course_name": course_name,
            "user_prompt_chars": len(user_prompt or ""),
            "digest_mode": digest_mode,
            "message_history_count": len(message_history),
            "material_digest_chars": len(material_context.material_digest or ""),
        },
        output=prompt,
    )


__all__ = ["build_plan_sketch_prompt"]
