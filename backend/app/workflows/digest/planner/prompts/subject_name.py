"""Prompt builder for planner-created subject display names."""

from __future__ import annotations

from app.workflows.digest.common.prompt_tracing import trace_prompt_build


def build_subject_name_prompt(
    *,
    user_prompt: str,
    filenames: list[str],
    digest_mode: str,
) -> str:
    """Build the short-title prompt used when creating a new learning space."""

    prompt = "\n".join(
        [
            "请根据用户学习目标和资料线索，生成一个中文学习空间标题。",
            "要求：",
            "- 2 到 10 个汉字为佳，最多 16 个字。",
            "- 像 ChatGPT/Gemini 对话标题一样简洁自然。",
            "- 不要输出引号、编号、解释、标点。",
            "- 不要写“新学科”“未命名”“学习资料”。",
            "",
            f"用户提示：{user_prompt or '未提供'}",
            f"资料名：{'、'.join(filenames) or '暂无'}",
            f"模式：{digest_mode}",
        ]
    )
    return trace_prompt_build(
        "planner_subject_name",
        inputs={
            "user_prompt_chars": len(user_prompt or ""),
            "filename_count": len(filenames),
            "digest_mode": digest_mode,
        },
        output=prompt,
    )


__all__ = ["build_subject_name_prompt"]
