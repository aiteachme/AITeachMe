"""Prompts for planner plan sketch streaming."""

from __future__ import annotations

from app.workflows.digest.planner.prompts.examples import render_plan_sketch_examples
from app.workflows.digest.common.models import DigestMaterialContext
from app.workflows.digest.planner.prompts.context import (
    render_material_digest,
    render_material_overview,
    render_message_history,
)


def build_plan_sketch_prompt(
    *,
    subject: str,
    user_goal: str,
    digest_mode: str,
    material_context: DigestMaterialContext,
    message_history: list[str],
) -> str:
    return (
        "你是 AITeachMe 的学习规划助手。"
        "请先生成一份给用户看的极简规划判断，不要输出正式构建方案，也不要写知识文档正文。\n\n"
        f"学科/主题：{subject}\n"
        f"用户目标：{user_goal}\n"
        f"模式：{digest_mode}\n"
        f"资料画像：\n{render_material_overview(material_context)}\n\n"
        f"资料上下文：\n{render_material_digest(material_context)}\n\n"
        f"最近对话：\n{render_message_history(message_history)}\n\n"
        "输出 3-5 条短句即可，像在快速告诉用户：我读到的资料主线是什么、优先抓哪些知识对象、后续大纲会怎么分。\n\n"
        "硬约束：\n"
        "1. 不要输出固定模板，不要写“资料判断/关注重点/预计计划大纲/待确认点”这种标签。\n"
        "2. 不允许输出 #、##、代码块、JSON、网站名、来源标题、subj_ 标识。\n"
        "3. 不要写空泛表达，例如“梳理基础”“强化理解”“提升能力”；必须落到资料里的具体对象。\n"
        "4. 全文控制在 260-360 字以内，宁可概括，不要铺陈。\n\n"
        "请参考下面这些 few-shot 示例的自然表达，注意它们都是“思考过程”示例，不是最终方案：\n\n"
        f"{render_plan_sketch_examples()}"
    )


__all__ = ["build_plan_sketch_prompt"]
