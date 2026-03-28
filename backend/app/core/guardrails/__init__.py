"""兼容性 shim — 实际实现已移至 app.platform.guardrails。"""
from app.platform.guardrails import (  # noqa: F401
    ContentSafetyGuardrail,
    GuardrailPipeline,
    GuardrailResult,
    InputGuardrail,
    OutputGuardrail,
    PIIFilterGuardrail,
)
