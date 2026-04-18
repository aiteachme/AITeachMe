"""Prompt placeholder for future LLM-assisted document backbone building."""

from __future__ import annotations

from langsmith import traceable


@traceable(name="DocGen：文档知识骨架提示词", run_type="prompt")
def build_document_backbone_messages(*, seed_payload: str, evidence_payload: str) -> list[dict[str, str]]:
    """Build messages for a future structured backbone call.

    The current MVP uses deterministic rules first, but keeping this prompt
    local to DocGen makes the next LLM-assisted step explicit and contained.
    """

    return [
        {
            "role": "system",
            "content": "你是 AITeachMe 的知识文档架构助手，负责统一术语、主张、证据和易混点。",
        },
        {
            "role": "user",
            "content": f"""
请基于章节执行 seed 和证据候选，输出整本文档的知识骨架。

章节 seed：
{seed_payload[:12000]}

证据候选：
{evidence_payload[:12000]}
""".strip(),
        },
    ]


__all__ = ["build_document_backbone_messages"]
