"""兼容性 shim — 实际实现已移至 app.platform.agent_loop。"""
from app.platform.agent_loop import (  # noqa: F401
    AgentLoopConfig,
    AgentLoopResult,
    ToolCallRecord,
    run_agent_loop,
    run_agent_loop_stream,
)
