"""兼容性 shim — 实际实现已移至 app.infra.cache。"""
from app.infra.cache import CacheEntry, SemanticCache, get_cache  # noqa: F401
