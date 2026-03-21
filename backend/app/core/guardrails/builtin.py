"""内置护栏实现。"""
from __future__ import annotations
import re
from app.core.guardrails.base import GuardrailResult, InputGuardrail


class ContentSafetyGuardrail(InputGuardrail):
    """基于关键词规则的内容安全检测。"""
    name = "content_safety"

    def __init__(self, blocked_patterns: list[str] | None = None) -> None:
        self._blocked = [re.compile(p, re.IGNORECASE) for p in (blocked_patterns or [])]

    async def check(self, content: str, *, context: dict | None = None) -> GuardrailResult:
        for p in self._blocked:
            if p.search(content):
                return GuardrailResult(passed=False, reason=f"触发安全规则：{p.pattern}")
        return GuardrailResult(passed=True)


class PIIFilterGuardrail(InputGuardrail):
    """个人信息过滤（手机号、身份证、邮箱）。"""
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
            return GuardrailResult(passed=not self._sanitize, reason=f"PII：{', '.join(detected)}",
                                   sanitized_content=sanitized if self._sanitize else None)
        return GuardrailResult(passed=True)
