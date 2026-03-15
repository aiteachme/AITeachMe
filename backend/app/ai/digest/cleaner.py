"""
Markdown 清洗节点

移除多余空行，修复 Markdown 格式错误，输出规范化 Markdown。
更新 Knowledge.pipeline_stage 为 cleaned。
"""

from __future__ import annotations

import re

import structlog

from app.repositories.models import PipelineStage

logger = structlog.get_logger()


def clean_markdown(raw_markdown: str) -> str:
    """清洗 Markdown 文本：去除多余空行、修复格式错误、规范化输出。

    Args:
        raw_markdown: 原始 Markdown 文本。

    Returns:
        规范化后的 Markdown 文本。
    """
    if not raw_markdown:
        return ""

    text = raw_markdown

    # 统一换行符为 \n
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # 修复标题格式：确保 # 后有空格
    text = re.sub(r"^(#{1,6})([^\s#])", r"\1 \2", text, flags=re.MULTILINE)

    # 修复列表格式：确保 - 或 * 后有空格
    text = re.sub(r"^(\s*[-*])([^\s])", r"\1 \2", text, flags=re.MULTILINE)

    # 修复有序列表格式：确保数字. 后有空格
    text = re.sub(r"^(\s*\d+\.)([^\s])", r"\1 \2", text, flags=re.MULTILINE)

    lines = text.splitlines()

    # 去除每行尾部空白
    lines = [line.rstrip() for line in lines]

    # 合并连续空行为最多一个空行
    result: list[str] = []
    prev_blank = False
    for line in lines:
        is_blank = line == ""
        if is_blank and prev_blank:
            continue
        result.append(line)
        prev_blank = is_blank

    # 去除首尾空行
    while result and result[0] == "":
        result.pop(0)
    while result and result[-1] == "":
        result.pop()

    # 确保标题前有空行（除非是文档开头）
    final: list[str] = []
    for i, line in enumerate(result):
        if re.match(r"^#{1,6}\s", line) and i > 0 and final and final[-1] != "":
            final.append("")
        final.append(line)

    text = "\n".join(final)
    if text and not text.endswith("\n"):
        text += "\n"
    return text
