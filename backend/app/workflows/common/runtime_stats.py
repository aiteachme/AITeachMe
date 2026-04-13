"""Minimal runtime stats and progress helpers for workflow nodes."""

from __future__ import annotations

import inspect
from collections.abc import Mapping
from contextlib import asynccontextmanager, nullcontext
from time import perf_counter
from typing import Any, Literal

from app.shared.infra.observability import LangSmithRunType, get_llm_trace_context, langsmith_trace, normalize_langsmith_run_type

StepKind = Literal["node", "tool", "substep", "llm"]

_STEP_LIMIT = 128


def record_step_start(
    state: dict[str, Any] | Mapping[str, Any],
    *,
    name: str,
    kind: StepKind,
) -> None:
    """Record the start time for one runtime step on a mutable workflow state."""

    if not isinstance(state, dict):
        return
    starts = dict(state.get("_runtime_step_starts") or {})
    starts[_step_key(name=name, kind=kind)] = perf_counter()
    state["_runtime_step_starts"] = starts


def record_step_end(
    state: dict[str, Any] | Mapping[str, Any],
    *,
    name: str,
    kind: StepKind,
    status: str = "ok",
) -> int:
    """Close one runtime step and append a compact runtime step entry."""

    if not isinstance(state, dict):
        return 0

    key = _step_key(name=name, kind=kind)
    starts = dict(state.get("_runtime_step_starts") or {})
    started_at = starts.pop(key, None)
    state["_runtime_step_starts"] = starts

    elapsed_ms = 0
    if started_at is not None:
        elapsed_ms = int((perf_counter() - float(started_at)) * 1000)

    steps = list(state.get("runtime_steps") or [])
    steps.append(
        {
            "name": str(name),
            "kind": str(kind),
            "status": str(status or "ok"),
            "elapsed_ms": int(elapsed_ms),
        }
    )
    state["runtime_steps"] = steps[-_STEP_LIMIT:]
    return elapsed_ms


def get_runtime_steps(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return a stable copy of runtime step entries."""

    steps: list[dict[str, Any]] = []
    for item in list(state.get("runtime_steps") or []):
        if not isinstance(item, Mapping):
            continue
        steps.append(
            {
                "name": str(item.get("name") or ""),
                "kind": str(item.get("kind") or "substep"),
                "status": str(item.get("status") or "ok"),
                "elapsed_ms": int(item.get("elapsed_ms", 0) or 0),
            }
        )
    return steps


async def emit_progress(
    state: Mapping[str, Any],
    *,
    phase: str,
    step: str,
    status: str,
    message: str,
) -> None:
    """Emit one compact progress event without coupling it to tracing."""

    callback = state.get("progress_callback")
    if callback is None or not callable(callback):
        return

    payload = {
        "phase": str(phase or ""),
        "step": str(step or ""),
        "status": str(status or "running"),
        "message": str(message or ""),
    }
    try:
        maybe_awaitable = callback(payload)
        if inspect.isawaitable(maybe_awaitable):
            await maybe_awaitable
    except Exception:
        return


def _step_key(*, name: str, kind: StepKind) -> str:
    return f"{kind}:{name}"


class TrackedStep:
    """Mutable handle exposed inside ``tracked_step``."""

    def __init__(self, run: Any | None) -> None:
        self._run = run
        self._outputs: dict[str, Any] = {}
        self.status: str = "ok"
        self._ended = False

    def set_outputs(self, **outputs: Any) -> None:
        self._outputs.update(
            {
                str(key): value
                for key, value in outputs.items()
                if value not in (None, "", [], {})
            }
        )

    def set_status(self, status: str) -> None:
        normalized = str(status or "").strip()
        if normalized:
            self.status = normalized

    def end_trace(self, *, outputs: Mapping[str, Any] | None = None) -> None:
        if self._run is None or self._ended:
            return
        final_outputs = dict(self._outputs)
        if outputs:
            final_outputs.update(
                {
                    str(key): value
                    for key, value in outputs.items()
                    if value not in (None, "", [], {})
                }
            )
        self._run.end(outputs=final_outputs)
        self._ended = True


@asynccontextmanager
async def tracked_step(
    state: dict[str, Any] | Mapping[str, Any] | None = None,
    *,
    name: str,
    kind: StepKind,
    phase: str | None = None,
    progress_step: str | None = None,
    running_message: str | None = None,
    completed_message: str | None = None,
    failed_message: str | None = None,
    trace_metadata: Mapping[str, Any] | None = None,
    trace_tags: list[str] | None = None,
    trace_inputs: Mapping[str, Any] | None = None,
    trace_run_type: LangSmithRunType = "tool",
    trace_enabled: bool = True,
):
    """Unify runtime stats, optional progress, and optional LangSmith substep tracing.

    Simplified: uses ``nullcontext`` to merge the traced / untraced branches
    into a single code path, eliminating ~50 lines of duplication.
    """

    step_name = str(name)
    progress_step_name = str(progress_step or step_name)
    should_trace = trace_enabled and kind != "node"
    resolved_trace_run_type = normalize_langsmith_run_type(trace_run_type)
    started_at = perf_counter()

    # Emit "running" progress.
    if state is not None:
        record_step_start(state, name=step_name, kind=kind)
        if phase and running_message:
            await emit_progress(
                state,
                phase=phase,
                step=progress_step_name,
                status="running",
                message=running_message,
            )

    # Build trace context manager (real LangSmith span or nullcontext).
    if should_trace:
        ctx = get_llm_trace_context()
        trace_cm = langsmith_trace(
            name=step_name,
            run_type=resolved_trace_run_type,
            inputs=dict(trace_inputs or {}),
            subject=ctx.subject,
            build_session_id=ctx.build_session_id,
            workflow=ctx.workflow,
            lane=ctx.lane,
            node=ctx.node,
            extra_metadata={"substep": step_name, **dict(trace_metadata or {})},
            extra_tags=[f"substep:{step_name}", *(trace_tags or [])],
        )
    else:
        trace_cm = nullcontext()

    # Unified execution path — no more duplicated try/except.
    with trace_cm as run:
        step = TrackedStep(run)
        try:
            yield step
        except Exception as exc:
            if state is not None:
                record_step_end(state, name=step_name, kind=kind, status="failed")
                if phase and failed_message:
                    await emit_progress(
                        state,
                        phase=phase,
                        step=progress_step_name,
                        status="failed",
                        message=failed_message,
                    )
            step.end_trace(outputs={"status": "failed", "error": str(exc)})
            raise
        else:
            final_status = step.status or "ok"
            elapsed_ms = int((perf_counter() - started_at) * 1000)
            if state is not None:
                elapsed_ms = record_step_end(state, name=step_name, kind=kind, status=final_status)
                if phase and completed_message and final_status == "ok":
                    await emit_progress(
                        state,
                        phase=phase,
                        step=progress_step_name,
                        status="completed",
                        message=completed_message,
                    )
            step.end_trace(outputs={"status": final_status, "elapsed_ms": elapsed_ms})


__all__ = [
    "StepKind",
    "emit_progress",
    "get_runtime_steps",
    "record_step_end",
    "record_step_start",
    "tracked_step",
    "TrackedStep",
]
