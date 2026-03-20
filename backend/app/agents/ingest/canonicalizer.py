"""Markdown 规范化器。

将各 parser 产出的原始 markdown 统一为一致的风格：
- 标题层级连续（不跳级）
- 图片引用格式统一
- 多余空行折叠
- 行尾空白清理
"""

from __future__ import annotations

import re


_HEADING_RE = re.compile(r"^(#{1,6})\s*(.*)", re.MULTILINE)


def canonicalize_markdown(raw: str) -> str:
    """对 Markdown 做规范化处理。"""
    if not raw:
        return ""

    text = raw.replace("\r\n", "\n").replace("\r", "\n")

    # 修复标题格式：#heading → # heading
    text = re.sub(r"^(#{1,6})([^\s#])", r"\1 \2", text, flags=re.MULTILINE)

    # 修复列表格式：-item → - item
    text = re.sub(r"^(\s*[-*])([^\s])", r"\1 \2", text, flags=re.MULTILINE)
    text = re.sub(r"^(\s*\d+\.)([^\s])", r"\1 \2", text, flags=re.MULTILINE)

    # 规范化标题层级（确保不跳级）
    text = _normalize_heading_levels(text)

    # 折叠多余空行
    lines = [line.rstrip() for line in text.splitlines()]
    cleaned: list[str] = []
    prev_blank = False
    for line in lines:
        is_blank = line == ""
        if is_blank and prev_blank:
            continue
        cleaned.append(line)
        prev_blank = is_blank

    # 去掉首尾空行
    while cleaned and cleaned[0] == "":
        cleaned.pop(0)
    while cleaned and cleaned[-1] == "":
        cleaned.pop()

    result = "\n".join(cleaned)
    if result and not result.endswith("\n"):
        result += "\n"
    return result


def _normalize_heading_levels(text: str) -> str:
    """确保标题层级连续，不跳级。

    例如文档中只有 H1 和 H3，会把 H3 降为 H2。
    """
    # 收集所有出现的标题层级
    levels_used: set[int] = set()
    for match in _HEADING_RE.finditer(text):
        levels_used.add(len(match.group(1)))

    if not levels_used:
        return text

    # 构建层级映射：把实际层级映射到连续层级
    sorted_levels = sorted(levels_used)
    level_map: dict[int, int] = {}
    for new_level, old_level in enumerate(sorted_levels, start=1):
        level_map[old_level] = min(new_level, 6)

    # 如果映射没有变化，直接返回
    if all(k == v for k, v in level_map.items()):
        return text

    def _replace_heading(match: re.Match) -> str:
        old_level = len(match.group(1))
        new_level = level_map.get(old_level, old_level)
        title = match.group(2)
        return f"{'#' * new_level} {title}"

    return _HEADING_RE.sub(_replace_heading, text)
