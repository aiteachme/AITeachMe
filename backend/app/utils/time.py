"""时间工具函数。"""

from __future__ import annotations

from datetime import datetime, timezone


def utcnow() -> datetime:
    """返回当前 UTC 时间（替代已废弃的 datetime.utcnow()）。"""

    return datetime.now(timezone.utc)


def ensure_utc_datetime(value: datetime | None) -> datetime | None:
    """将 datetime 规范化为带 UTC 时区的时间。"""

    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def seconds_between(later: datetime | None, earlier: datetime | None) -> int | None:
    """计算两个时间点之间的秒数，兼容 naive/aware datetime 混用。"""

    normalized_later = ensure_utc_datetime(later)
    normalized_earlier = ensure_utc_datetime(earlier)
    if normalized_later is None or normalized_earlier is None:
        return None
    return max(0, int((normalized_later - normalized_earlier).total_seconds()))


def is_at_or_before(value: datetime | None, reference: datetime) -> bool:
    """判断时间是否早于或等于参考时间。"""

    normalized_value = ensure_utc_datetime(value)
    normalized_reference = ensure_utc_datetime(reference)
    if normalized_value is None or normalized_reference is None:
        return False
    return normalized_value <= normalized_reference


def is_at_or_after(value: datetime | None, reference: datetime) -> bool:
    """判断时间是否晚于或等于参考时间。"""

    normalized_value = ensure_utc_datetime(value)
    normalized_reference = ensure_utc_datetime(reference)
    if normalized_value is None or normalized_reference is None:
        return False
    return normalized_value >= normalized_reference
