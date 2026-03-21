"""主题相关性 + 幻觉检测护栏。"""
from __future__ import annotations
from app.core.guardrails.base import GuardrailResult, InputGuardrail, OutputGuardrail

class TopicRelevanceGuardrail(InputGuardrail):
    name = "topic_relevance"
    def __init__(self, *, off_topic_keywords: list[str] | None = None) -> None:
        self._off_topic = set(kw.lower() for kw in (off_topic_keywords or []))
    async def check(self, content: str, *, context: dict | None = None) -> GuardrailResult:
        if not self._off_topic:
            return GuardrailResult(passed=True)
        matched = [kw for kw in self._off_topic if kw in content.lower()]
        if matched:
            return GuardrailResult(passed=False, reason=f"偏离主题：{', '.join(matched)}")
        return GuardrailResult(passed=True)

class HallucinationGuardrail(OutputGuardrail):
    name = "hallucination"
    _SUSPICIOUS = ["众所周知", "研究表明", "据统计", "科学证明"]
    def __init__(self, *, strict: bool = False) -> None:
        self._strict = strict
    async def check(self, content: str, *, context: dict | None = None) -> GuardrailResult:
        if not self._strict:
            return GuardrailResult(passed=True)
        sources = (context or {}).get("retrieval_sources", [])
        if not sources and len(content) > 200:
            flagged = [p for p in self._SUSPICIOUS if p in content]
            if flagged:
                return GuardrailResult(passed=True, reason=f"可能无来源支撑：{', '.join(flagged)}")
        return GuardrailResult(passed=True)
