"""Prompt placeholder for future LLM-assisted document consistency review."""

from __future__ import annotations

from langsmith import traceable


@traceable(name="DocGen：整本一致性复核提示词", run_type="prompt")
def build_document_consistency_messages(*, backbone_payload: str, merged_markdown: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": "你是 AITeachMe 的整本知识文档一致性复核助手。"},
        {
            "role": "user",
            "content": f"知识骨架：\n{backbone_payload[:10000]}\n\n整本草稿：\n{merged_markdown[:16000]}",
        },
    ]


__all__ = ["build_document_consistency_messages"]
