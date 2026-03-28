"""兼容性 shim — 实际实现已移至 app.platform.security。"""
from app.platform.security import (  # noqa: F401
    SafetyDecision,
    SecurityLevel,
    SecurityRule,
    register_security_rule,
    require_confirmation,
    reset_session_counts,
)
