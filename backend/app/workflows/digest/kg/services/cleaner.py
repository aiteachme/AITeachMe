"""Markdown 清洗器。"""

from __future__ import annotations

import re


def clean_markdown(raw_markdown: str) -> str:
    """清洗 Markdown 文本。"""

    if not raw_markdown:
        return ""

    text = raw_markdown.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"^(#{1,6})([^\s#])", r"\1 \2", text, flags=re.MULTILINE)
    text = re.sub(r"^(\s*[-*])([^\s])", r"\1 \2", text, flags=re.MULTILINE)
    text = re.sub(r"^(\s*\d+\.)([^\s])", r"\1 \2", text, flags=re.MULTILINE)

    lines = [line.rstrip() for line in text.splitlines()]
    cleaned: list[str] = []
    previous_blank = False
    for line in lines:
        is_blank = line == ""
        if is_blank and previous_blank:
            continue
        cleaned.append(line)
        previous_blank = is_blank

    while cleaned and cleaned[0] == "":
        cleaned.pop(0)
    while cleaned and cleaned[-1] == "":
        cleaned.pop()

    result = "\n".join(cleaned)
    if result and not result.endswith("\n"):
        result += "\n"
    return result
