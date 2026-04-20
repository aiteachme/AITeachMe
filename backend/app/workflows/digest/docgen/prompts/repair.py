"""Prompt builders for DocGen repair patches."""

from __future__ import annotations

from app.workflows.digest.common.prompt_tracing import trace_prompt_build

PATCH_MARKDOWN_BUDGET = 12000


def _clip(value: object, *, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n...[已截断]"


def build_chapter_patch_messages(
    *,
    chapter_title: str,
    action: dict,
    markdown: str,
) -> list[dict[str, str]]:
    system_prompt = """
你是 AITeachMe 的章节修补器。
你只能根据给定 ReviewAction 对当前章节做局部修补。
禁止新增、删除或重排章节；禁止引入没有证据支撑的新事实；禁止输出解释。
你必须返回完整的修补后 Markdown，保留原一级标题、已有 Mermaid、图片、自检题和来源口径。
""".strip()
    user_prompt = f"""
章节标题：{chapter_title}

ReviewAction：
{_clip(action, limit=3000)}

当前章节 Markdown：
{_clip(markdown, limit=PATCH_MARKDOWN_BUDGET)}

输出要求：
1. 只输出修补后的完整 Markdown。
2. 不要包裹 ```markdown 代码块。
3. 只改 ReviewAction 指向的问题，不做风格大改。
4. 如果无法安全修补，原样返回 Markdown。
""".strip()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    return trace_prompt_build(
        "chapter_patch",
        inputs={
            "chapter_title": chapter_title,
            "action_type": str(action.get("action_type") or ""),
            "chapter_index": action.get("chapter_index"),
            "markdown_chars": len(markdown),
        },
        output=messages,
    )


__all__ = ["build_chapter_patch_messages"]
