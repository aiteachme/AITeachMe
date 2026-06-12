"""Prompts for the first Planner fan-out: planning note and material note."""

from __future__ import annotations

from app.workflows.digest.common.models import DigestMaterialContext
from app.workflows.digest.common.prompt_tracing import trace_prompt_build
from app.workflows.digest.planner.lib.plans import planner_mode_label
from app.workflows.digest.planner.prompts.context import (
    render_material_digest,
    render_material_overview,
    render_message_history,
)


def build_stream_planning_note_prompt(
    *,
    course_name: str,
    user_prompt: str,
    digest_mode: str,
    material_context: DigestMaterialContext,
    message_history: list[str],
) -> str:
    mode_label = planner_mode_label(digest_mode)
    prompt = f"""
你是 AITeachMe 的学习方案 Planner。请先流式输出规划判断 planning_note，让用户看到你如何理解目标。

输出要求：
- 只输出自然语言正文，不输出标题、Markdown、JSON、编号或代码块。
- 控制在 180-420 字。
- 必须说清楚：用户真正想学什么、这个目标更像系统学习/冲刺复习/专题突破/作业通关中的哪一种、方案应该按什么主线拆。
- 用户已经列出的章节、模块、知识点或范围是拆分主线的优先依据；例如“按 A、B、C 划分章节”时，直接把 A/B/C 作为章节边界。
- 练习、检测、查漏、错因复盘是对应模块内的学习活动；用户提出综合卷、跨模块训练或考前模拟时，再把它作为独立模块。
- 如果没有可读取资料，明确按用户输入和通用课程常识判断，不要说已经读过资料。
- 如果有资料，只能说资料大致呈现出的学科边界，不要承诺已经生成正文或证据。
- 这段文字最终会进入 planner 输出的 planning_note 字段。

课程/主题：{course_name}
用户输入：{user_prompt or "未提供"}
模式：{mode_label}

资料画像：
{render_material_overview(material_context)}

资料上下文：
{render_material_digest(material_context)}

最近对话：
{render_message_history(message_history)}
""".strip()
    return trace_prompt_build(
        "planner_stream_planning_note",
        inputs={
            "course_name": course_name,
            "user_prompt_chars": len(user_prompt or ""),
            "digest_mode": digest_mode,
            "message_history_count": len(message_history),
            "material_digest_chars": len(material_context.material_digest or ""),
        },
        output=prompt,
    )


def build_material_note_messages(
    *,
    course_name: str,
    user_prompt: str,
    digest_mode: str,
    material_context: DigestMaterialContext,
) -> list[dict[str, str]]:
    mode_label = planner_mode_label(digest_mode)
    system_prompt = """
你是 AITeachMe 的资料边界整理器。你只输出合法 JSON，不输出 Markdown、解释或额外文本。
material_note 字段只描述本轮可用资料/主题的大致学科情况；资料不可用时必须说明只能依据用户目标和通用知识。
""".strip()
    prompt = f"""
请生成内部资料边界 material_note 字段，用于辅助后续方案生成。

字段要求：
- material_note 控制在 120-260 字。
- 概括资料或主题覆盖的对象、层级、典型学习任务和可能的难点。
- 如果资料正文为空或未解析，不要假装读过资料；说明当前只能做临时主题摘要。
- 不要输出来源列表、文件清单、章节目录或正式学习方案。

课程/主题：{course_name}
用户输入：{user_prompt or "未提供"}
模式：{mode_label}

资料画像：
{render_material_overview(material_context)}

资料上下文：
{render_material_digest(material_context)}

只输出 JSON：
{{"material_note":"一段资料/学科情况摘要"}}
""".strip()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]
    return trace_prompt_build(
        "planner_material_note",
        inputs={
            "course_name": course_name,
            "user_prompt_chars": len(user_prompt or ""),
            "digest_mode": digest_mode,
            "material_digest_chars": len(material_context.material_digest or ""),
        },
        output=messages,
    )


__all__ = ["build_material_note_messages", "build_stream_planning_note_prompt"]
