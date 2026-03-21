"""Guardrail 管线：组合执行多个安全检查。"""
from __future__ import annotations
import structlog
from app.core.guardrails.base import GuardrailResult, InputGuardrail, OutputGuardrail

logger = structlog.get_logger()

class GuardrailPipeline:
    def __init__(self) -> None:
        self._input: list[InputGuardrail] = []
        self._output: list[OutputGuardrail] = []

    def add_input_guardrail(self, g: InputGuardrail) -> "GuardrailPipeline":
        self._input.append(g); return self

    def add_output_guardrail(self, g: OutputGuardrail) -> "GuardrailPipeline":
        self._output.append(g); return self

    async def check_input(self, content: str, *, context: dict | None = None) -> GuardrailResult:
        for g in self._input:
            r = await g.check(content, context=context)
            if not r.passed:
                logger.warning("input_guardrail_blocked", guardrail=g.name, reason=r.reason)
                return r
            if r.sanitized_content is not None:
                content = r.sanitized_content
        return GuardrailResult(passed=True, sanitized_content=content)

    async def check_output(self, content: str, *, context: dict | None = None) -> GuardrailResult:
        for g in self._output:
            r = await g.check(content, context=context)
            if not r.passed:
                logger.warning("output_guardrail_blocked", guardrail=g.name, reason=r.reason)
                return r
        return GuardrailResult(passed=True)
