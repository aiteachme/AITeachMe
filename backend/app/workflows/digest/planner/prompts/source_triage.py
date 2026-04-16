"""Prompt placeholder for future LLM source triage."""

from __future__ import annotations


def build_source_triage_prompt(*, query: str, source_summaries: list[str]) -> str:
    return (
        "请从候选来源中选择最值得打开阅读的少量来源。\n"
        f"检索词：{query}\n"
        "候选来源：\n"
        + "\n".join(f"- {item}" for item in source_summaries)
    )


__all__ = ["build_source_triage_prompt"]
