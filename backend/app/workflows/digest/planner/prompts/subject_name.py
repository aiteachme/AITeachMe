"""Prompt builder for planner-created subject display names."""

from __future__ import annotations

from app.workflows.digest.common.prompt_tracing import trace_prompt_build


def build_subject_name_prompt(
    *,
    user_prompt: str,
    filenames: list[str],
    digest_mode: str,
    plan_intent: str = "",
    plan_summary: str = "",
    chapter_titles: list[str] | None = None,
    planner_brief: str = "",
) -> str:
    """Build the short-title prompt used when creating a new learning space."""

    normalized_chapter_titles = [str(item).strip() for item in list(chapter_titles or []) if str(item).strip()]
    brief = " ".join(str(planner_brief or "").split())[:240]
    intent = " ".join(str(plan_intent or "").split())[:180]
    summary = " ".join(str(plan_summary or "").split())[:240]
    prompt = f"""
请根据用户学习目标、规划意图和章节骨架，生成一个中文学习空间标题。

要求：
- 2 到 10 个汉字为佳，最多 16 个字。
- 像 ChatGPT/Gemini 对话标题一样简洁自然。
- 不要输出引号、编号、解释、标点。
- 不要写“新学科”“未命名”“学习资料”。
- 优先概括“这门内容到底在学什么”，不要照抄用户原话。

用户提示：{user_prompt or '未提供'}
资料名：{'、'.join(filenames) or '暂无'}
模式：{digest_mode}
规划意图：{intent or '暂无'}
计划摘要：{summary or '暂无'}
章节标题：{'、'.join(normalized_chapter_titles[:6]) or '暂无'}
思考线索：{brief or '暂无'}
""".strip()
    return trace_prompt_build(
        "planner_subject_name",
        inputs={
            "user_prompt_chars": len(user_prompt or ""),
            "filename_count": len(filenames),
            "digest_mode": digest_mode,
            "plan_intent_chars": len(intent),
            "plan_summary_chars": len(summary),
            "chapter_count": len(normalized_chapter_titles),
            "planner_brief_chars": len(brief),
        },
        output=prompt,
    )


__all__ = ["build_subject_name_prompt"]
