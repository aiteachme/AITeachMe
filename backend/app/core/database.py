"""兼容性 shim — 实际实现已移至 app.infra.database。"""
from app.infra.database import (  # noqa: F401
    get_engine,
    get_session,
    get_vec_status,
    init_db,
    is_vec_ready,
    managed_session,
    require_vec_ready,
    reset_runtime_state,
)
