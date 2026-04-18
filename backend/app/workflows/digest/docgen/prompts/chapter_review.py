"""Prompt placeholder for future LLM-assisted chapter review."""

from __future__ import annotations

from langsmith import traceable


@traceable(name="DocGen：章节复核提示词", run_type="prompt")
def build_chapter_review_messages(*, chapter_markdown: str, contract_payload: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": "你是 AITeachMe 的章节内容复核助手。"},
        {
            "role": "user",
            "content": f"章节合同：\n{contract_payload[:8000]}\n\n章节正文：\n{chapter_markdown[:12000]}",
        },
    ]


__all__ = ["build_chapter_review_messages"]
