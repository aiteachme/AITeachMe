"""兼容性 shim — 实际实现已移至 app.platform.llm。"""
from app.platform.llm import (  # noqa: F401
    acompletion,
    acompletion_stream,
    acompletion_structured,
    acompletion_with_tools,
)
