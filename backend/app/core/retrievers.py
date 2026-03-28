"""兼容性 shim — 实际实现已移至 app.platform.retrievers。"""
from app.platform.retrievers import (  # noqa: F401
    RetrievalConfig,
    RetrievalPipeline,
    RetrievedChunk,
)
