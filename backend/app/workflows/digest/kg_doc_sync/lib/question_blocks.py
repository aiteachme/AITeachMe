"""Question-block parsing used by KG content-shape checks."""

from __future__ import annotations

import re
from dataclasses import dataclass

_QUESTION_START_RE = re.compile(
    r"^\s*(?:[-*+]\s*)?(?:(\d{1,4})\s*(?:[\u3001\.\uff0e\)])|\u7b2c\s*(\d{1,4})\s*\u9898)"
)
_ANSWER_SHEET_RE = re.compile(r"^\s*\d+\s*[-~\u2014]\s*\d+")


@dataclass
class QuestionBlock:
    """A question-like block detected from flat markdown."""

    number: int | None
    stem: str
    content: str


def _extract_question_number(line: str) -> int | None:
    match = _QUESTION_START_RE.match(line)
    if match is None:
        return None

    raw_number = match.group(1) or match.group(2)
    if raw_number is None:
        return None

    try:
        return int(raw_number)
    except ValueError:
        return None


def _clean_question_stem(line: str) -> str:
    text = _QUESTION_START_RE.sub("", line, count=1)
    text = re.sub(r"\s*(?:[\(\uff08][A-Da-d]\s*[\)\uff09])\s*$", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" -*+")


def parse_question_blocks(markdown: str) -> list[QuestionBlock]:
    """Parse flat question-bank markdown into question blocks."""

    if not markdown.strip():
        return []

    blocks: list[QuestionBlock] = []
    current_lines: list[str] = []
    current_number: int | None = None

    def flush_block() -> None:
        nonlocal current_lines, current_number
        if not current_lines:
            return

        first_line = current_lines[0].strip()
        stem = _clean_question_stem(first_line)
        content = "\n".join(line.rstrip() for line in current_lines).strip()
        if not stem or not content or _ANSWER_SHEET_RE.match(first_line):
            current_lines = []
            current_number = None
            return

        blocks.append(QuestionBlock(number=current_number, stem=stem, content=content))
        current_lines = []
        current_number = None

    for line in markdown.splitlines():
        number = _extract_question_number(line)
        if number is not None:
            flush_block()
            current_lines = [line]
            current_number = number
            continue

        if current_lines:
            current_lines.append(line)

    flush_block()
    return blocks


__all__ = ["QuestionBlock", "parse_question_blocks"]
