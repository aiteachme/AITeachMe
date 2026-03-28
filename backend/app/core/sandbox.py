"""兼容性 shim — 实际实现已移至 app.platform.sandbox。"""
from app.platform.sandbox import (  # noqa: F401
    BaseSandbox,
    CommandRecord,
    Exercise,
    ExerciseSandbox,
    ExerciseStep,
    ExecutionResult,
    GradeResult,
    LocalCodeSandbox,
    LocalTerminalSandbox,
    SandboxType,
    SimulatedTerminalSandbox,
    create_exercise_sandbox,
    create_sandbox,
    get_builtin_exercises,
    get_exercise,
)
