"""服务层通用辅助函数。"""

from __future__ import annotations


def require_id(value: int | None, field_name: str) -> int:
    """确保数据库主键已经存在。"""

    if value is None:
        raise ValueError(f"{field_name} 持久化后不应为空。")
    return value


def mastery_to_text(mastery: float | None) -> str:
    """把掌握度转换为展示文本。"""

    if mastery is None:
        return "暂无数据"
    return f"{mastery:.0%}"
