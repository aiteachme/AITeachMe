"""时间工具函数。"""

from __future__ import annotations

from datetime import datetime, timezone


def utcnow() -> datetime:
    """返回当前 UTC 时间（替代已废弃的 datetime.utcnow()）。"""

    return datetime.now(timezone.utc)
