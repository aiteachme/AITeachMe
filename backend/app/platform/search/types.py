"""搜索类型定义。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class WebSearchResult:
    """Web 搜索结果。"""

    title: str
    url: str
    snippet: str
    score: float = 0.0

    def to_text(self) -> str:
        """格式化为可读文本（适合注入 LLM 上下文）。"""
        return f"[{self.title}]({self.url})\n{self.snippet}"
