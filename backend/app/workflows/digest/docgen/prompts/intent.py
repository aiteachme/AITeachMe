"""Prompts for DocGen writing intent inference."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from app.workflows.digest.common.prompt_tracing import trace_prompt_build
from app.workflows.digest.docgen.mode_profiles import get_docgen_mode_profile


def build_intent_core_messages(
    *,
    course_name: str,
    digest_mode: str,
    user_prompt: str,
    plan_summary: str,
    material_profile: Mapping[str, Any],
    chapters: Sequence[Mapping[str, Any]],
    docgen_history_brief: str = "",
) -> list[dict[str, str]]:
    # 文档级意图判断只需要短上下文；按章风格脚手架后移到章节 brief 阶段。
    mode_label = get_docgen_mode_profile(digest_mode).prompt_label
    chapter_titles = "、".join(
        str(chapter.get("title") or chapter.get("resolved_title") or "").strip()
        for chapter in chapters
        if str(chapter.get("title") or chapter.get("resolved_title") or "").strip()
    )
    system_prompt = """
你是 AITeachMe 的知识文档生成写作意图分析器。
你只输出合法 JSON，不输出 Markdown、解释或额外文本。
规划器已经决定大纲；你只判断文档应该怎样讲，不能修改章节数量、顺序或主题。
""".strip()
    prompt = f"""
请根据用户提示、规划摘要、材料画像和章节标题，识别本轮知识文档的文档级写作意图。
这里的任务不是判断学科模板，而是判断“这份学习文档应该如何帮助用户学会材料”。

主题：{course_name}
模式：{mode_label}
用户提示：{user_prompt or "未提供"}
计划摘要：{plan_summary or "未提供"}
规划器对话与修改摘要：{docgen_history_brief or "暂无"}
章节标题：{chapter_titles or "未提供"}
材料画像：{dict(material_profile or {})}

请输出 JSON：
{{
  "learning_goal_text": "用户真正想学会、完成或复习什么，用一两句话说明",
  "audience_profile_text": "学习者所处阶段、学习场景、时间压力、使用目的等",
  "content_strategy_text": "这份文档应该怎样组织和讲解才适合当前资料",
  "example_practice_policy": "例子、案例、练习、反例应该承担什么作用，大致比例如何",
  "source_usage_policy": "本地资料、外部补充、证据引用和不确定性应如何处理",
  "teaching_intent": "一句话概括本轮生成的教学意图",
  "example_ratio": 0.0,
  "practice_ratio": 0.0,
  "evidence_strictness": 0.0,
  "review_strictness": 0.0,
  "avoid_list": ["..."]
}}

要求：
1. 字段必须泛化适用于任何学习材料，不要写死具体学科、考试、编程或 AI 场景。
2. 有练习或公式只说明材料信号，不能直接把课程判断成试卷或数学课。
3. `example_ratio` / `practice_ratio` 表示正文中例子和练习应占的相对权重，取 0.0-1.0。
4. `evidence_strictness` / `review_strictness` 表示来源和复核要求强度，取 0.0-1.0。
5. 模式只影响节奏：冲刺更聚焦抓手和练习，系统更强调结构和推理；不要因此改变章节数量、顺序或主题。
6. 只输出文档级短字段；不要生成按章 `chapter_style_hints`。
""".strip()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]
    return trace_prompt_build(
        "docgen_intent",
        inputs={
            "course_name": course_name,
            "digest_mode": digest_mode,
            "chapter_count": len(chapters),
            "has_history": bool(docgen_history_brief),
        },
        output=messages,
    )


__all__ = ["build_intent_core_messages"]
