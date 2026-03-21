"""内容安全 + PII 过滤护栏。"""
from __future__ import annotations
import re
from app.core.guardrails.base import GuardrailResult, InputGuardrail

class ContentSafetyGuardrail(InputGuardrail):
    name = "content_safety"
    def __init__(self, blocked_patterns: list[str] | None = None) -> None:
        self._blocked = [re.compile(p, re.IGNORECASE) for p in (blocked_patterns or [])]
    async def check(self, content: str, *, context: dict | None = None) -> GuardrailResult:
        for p in self._blocked:
            if p.search(content):
                return GuardrailResult(passed=False, reason=f"触发安全规则：{p.pattern}")
        return GuardrailResult(passed=True)

class PIIFilterGuardrail(InputGuardrail):
    name = "pii_filter"
    _PATTERNS = {
        "phone": re.compile(r"1[3-9]\d{9}"),
        "id_card": re.compile(r"\d{17}[\dXx]"),
        "email": re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"),
    }
    def __init__(self, *, sanitize: bool = False) -> None:
        self._sanitize = sanitize
    async def check(self, content: str, *, context: dict | None = None) -> GuardrailResult:
        detected, sanitized = [], content
        for pii_type, pattern in self._PATTERNS.items():
            if pattern.search(content):
                detected.append(pii_type)
                if self._sanitize:
                    sanitized = pattern.sub(f"[{pii_type.upper()}_REDACTED]", sanitized)
        if detected:
            return GuardrailResult(passed=not self._sanitize, reason=f"检测到PII：{', '.join(detected)}",
                                   sanitized_content=sanitized if self._sanitize else None)
        return GuardrailResult(passed=True)
