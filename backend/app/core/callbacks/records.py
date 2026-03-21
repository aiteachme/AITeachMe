"""LLM 调用记录数据结构。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4


@dataclass
class LLMCallRecord:
    """单次 LLM 调用的观测记录。"""

    task_type: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_s: float = 0.0
    success: bool = True
    error: str | None = None
    call_id: str = field(default_factory=lambda: uuid4().hex[:12])
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def estimated_cost_usd(self) -> float:
        """粗略估算成本（基于通义千问定价，仅做参考）。"""
        return (self.prompt_tokens * 0.002 + self.completion_tokens * 0.006) / 1000
