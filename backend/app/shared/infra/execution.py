"""Compatibility shim for the old execution helper import path.

New code should import from `app.shared.infra.traced_execution`.
"""

from app.shared.infra.traced_execution import (
    BaseTracedExecution,
    TracedExecutionContext,
    TracedExecutionResult,
)

BaseOrchestrator = BaseTracedExecution
OrchestratorContext = TracedExecutionContext
OrchestratorResult = TracedExecutionResult

__all__ = [
    "BaseTracedExecution",
    "TracedExecutionContext",
    "TracedExecutionResult",
    "BaseOrchestrator",
    "OrchestratorContext",
    "OrchestratorResult",
]
