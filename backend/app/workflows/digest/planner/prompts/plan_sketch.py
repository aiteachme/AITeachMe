"""Prompts for planner plan sketch streaming."""

from __future__ import annotations

from typing import Any

from app.workflows.digest.common.prompt_tracing import trace_prompt_build
from app.workflows.digest.planner.prompts.examples import render_plan_sketch_examples
from app.workflows.digest.common.models import DigestMaterialContext
from app.workflows.digest.planner.prompts.context import (
    render_latest_feedback,
    render_latest_plan,
    render_material_digest,
    render_material_overview,
    render_message_history,
    render_planner_context_mode,
)
from app.workflows.digest.planner.lib.plans import planner_mode_label


def build_plan_sketch_prompt(
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
) -> str:
    # sketch 是流式展示的“正在理解中”，不是最终计划。最终卡片只使用
    # 计划合成器生成的计划说明和初步大纲。
    mode_label = planner_mode_label(digest_mode)
    is_revision = bool(latest_plan and str(latest_feedback or "").strip())
    context_mode_block = render_planner_context_mode(
        planner_context_mode=planner_context_mode,
        existing_doc_context=existing_doc_context,
    )
    output_focus = (
        "\n".join(
            [
                "输出 3-5 段自然短句，先判断本轮修改属于哪一种：",
                "1. 如果用户是在上一版里局部增删改某章、顺序或表达，就说明会定位受影响对象并把修改作为最小补丁应用到完整大纲；",
                "2. 如果用户给出新的具体专题、明确章数，或说“改成/生成 XXX 的 N 个章节”，就说明这是对上一版范围的整体重定向，旧方案只作为被替换上下文；",
                "3. 只有局部补丁场景才说明哪些章节或字段应保持不动；整体重定向时不要说保留旧章节、旧主线或未改部分；",
                "4. 下一步会如何校验新大纲是否严格围绕本轮目标范围和用户指定章数。",
            ]
        )
        if is_revision
        else "\n".join(
            [
                "输出 3-5 段自然短句，围绕四件事：",
                "1. 资料大概覆盖什么边界；",
                "2. 用户当前更像哪类学习意图；",
                "3. 哪些内容可能需要归并或拆开；",
                "4. 下一步计划会优先解决什么学习问题。",
            ]
        )
    )
    revision_constraint = (
        "\n10. 本轮是修订已有方案时，必须先判断用户是在局部补丁还是整体重定向；用户明确要求新专题、指定章数或“改成 XXX”时，应按整体重定向说明，不要继续套用保留旧章节的局部补丁逻辑。"
        if is_revision
        else ""
    )
    prompt = f"""
你是 AITeachMe 的学习规划助手。请先输出一段自然的思考过程，让用户知道你正在如何理解资料。
不要输出正式计划，不要输出初步大纲，也不要写知识文档正文。
最新用户输入/本轮修改意见优先于课程名、资料标题和模式；如果用户刚刚说的是具体知识点、方法、定理、公式、题型或章节主题，你必须先把它判断为本轮规划范围。

课程/主题：{course_name}
用户提示：{user_prompt}
模式：{mode_label}

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

{output_focus}

硬约束：
1. 不要输出固定模板，不要写“资料判断/关注重点/预计计划大纲/待确认点”这种标签。
2. 不允许输出 #、##、代码块、JSON、网站名、来源标题、内部课程 ID 标识。
3. 不要写空泛表达，例如“梳理基础”“强化理解”“提升能力”；要落到资料里的具体对象或学习动作。
4. 不要列正式章节目录；最终计划和初步大纲会在下一步单独生成。
5. 全文控制在 260-520 字以内，宁可把判断原因讲清楚，不要铺陈。
6. 如果没有上传资料，只能基于用户提示和课程常识判断，不要写“这批资料显示/资料里包含”。
7. 若当前规划模式为已有知识文档重建/调整，必须围绕已有文档摘要和用户修改意见说明调整思路。
8. 如果本轮最新输入是在修改已有方案，必须优先解释将如何响应这条最新修改，而不是重复上一版方案。
9. 如果用户最新输入是“生成 XXX 的章节/把 XXX 分几章/讲 XXX/改成 XXX 的 N 个章节”，不要扩展成整门课，也不要默认保留旧章节；要说明会把 XXX 拆成适用条件、方法步骤、典型题、易错边界、综合迁移等学习角度，并把是否补前置知识作为可调整点。
{revision_constraint}

{"请参考下面这些示例的自然表达，注意它们都是“思考过程”示例，不是最终方案：" if not is_revision else "本轮是修订已有方案，不使用普通新建示例。"}

{"" if is_revision else render_plan_sketch_examples()}
""".strip()
    return trace_prompt_build(
        "planner_plan_sketch",
        inputs={
            "course_name": course_name,
            "user_prompt_chars": len(user_prompt or ""),
            "digest_mode": digest_mode,
            "message_history_count": len(message_history),
            "latest_feedback_chars": len(latest_feedback or ""),
            "has_latest_plan": latest_plan is not None,
            "is_revision": is_revision,
            "material_digest_chars": len(material_context.material_digest or ""),
            "planner_context_mode": planner_context_mode,
            "existing_doc_context_chars": len(existing_doc_context or ""),
        },
        output=prompt,
    )


__all__ = ["build_plan_sketch_prompt"]
