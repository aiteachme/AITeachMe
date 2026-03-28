"""兼容性 shim — 实际实现已移至 app.teaching.teaching。"""
from app.teaching.teaching import (  # noqa: F401
    TeachingFunctionDef,
    list_teaching_functions,
    run_teaching_function,
    teaching_function,
)
