"""Pure helpers for lightweight docs input cleaning."""

from __future__ import annotations

import asyncio
import re

import structlog

from app.core.llm import acompletion
from app.core.model_router import TaskType
from app.workflows.digest.prompts.docgen_prompts import CLEANSE_PROMPT

logger = structlog.get_logger()

_PAGE_NUMBER_PATTERNS = [
    re.compile(r"^\s*-\s*\d+\s*-\s*$", re.MULTILINE),
    re.compile(r"^\s*第\s*\d+\s*页\s*$", re.MULTILINE),
    re.compile(r"^\s*Page\s+\d+\s*$", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^\s*\d+\s*$", re.MULTILINE),
]
_EXCESSIVE_NEWLINES = re.compile(r"\n{3,}")
_INVISIBLE_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\ufeff]")
_MARKDOWN_HEADER_PATTERN = re.compile(r"^\s{0,3}#{1,6}\s+\S+", re.MULTILINE)
_TABLE_LINE_PATTERN = re.compile(r"^\|.+\|$", re.MULTILINE)
_HEAL_CHUNK_SIZE = 2400
_MOJIBAKE_HINTS = ("锟", "鈥", "鈩", "銆", "�")


def rule_based_cleanse(text: str) -> str:
    """Remove obvious page markers and invisible characters."""

    cleaned = text
    for pattern in _PAGE_NUMBER_PATTERNS:
        cleaned = pattern.sub("", cleaned)
    cleaned = _INVISIBLE_CHARS.sub("", cleaned)
    cleaned = _EXCESSIVE_NEWLINES.sub("\n\n", cleaned)
    return cleaned.strip()


def stitch_sentences(text: str) -> str:
    """Merge hard-wrapped lines when they are likely one sentence."""

    lines = text.split("\n")
    stitched: list[str] = []
    endings = {"。", "！", "？", ".", "!", "?", ";", "；", ":"}
    for index, line in enumerate(lines):
        current = line.rstrip()
        if not current:
            stitched.append("")
            continue

        append_space = False
        if index + 1 < len(lines):
            next_line = lines[index + 1].strip()
            append_space = (
                current[-1] not in endings
                and bool(next_line)
                and not next_line.startswith(("#", "-", "*", ">", "|"))
                and not re.match(r"^\d+[.)、]", next_line)
            )
        stitched.append(current + (" " if append_space else ""))
    return "\n".join(stitched).strip()


async def llm_heal_chunk(text: str) -> str:
    """Repair one chunk with the light doc model."""

    prompt = CLEANSE_PROMPT.format(text=text[:_HEAL_CHUNK_SIZE])
    try:
        result = await acompletion(
            [{"role": "user", "content": prompt}],
            task_type=TaskType.DOCGEN_LIGHT,
        )
        return result.strip()
    except Exception as exc:
        logger.warning("llm_heal_chunk_failed", error=str(exc))
        return text


def analyze_cleanliness(*, source_filename: str, content: str) -> dict[str, object]:
    """Estimate whether the content needs LLM cleanup."""

    lowered = source_filename.lower()
    extension = lowered.rsplit(".", 1)[-1] if "." in lowered else ""
    header_count = len(_MARKDOWN_HEADER_PATTERN.findall(content))
    table_lines = len(_TABLE_LINE_PATTERN.findall(content))
    invisible_count = len(_INVISIBLE_CHARS.findall(content))
    mojibake_count = sum(content.count(marker) for marker in _MOJIBAKE_HINTS)
    content_len = max(len(content), 1)
    noise_ratio = (invisible_count + mojibake_count) / content_len
    severe_noise = mojibake_count >= 6 or noise_ratio >= 0.006
    moderate_noise = mojibake_count >= 3 or noise_ratio >= 0.003
    clean_markdown = (
        extension in {"md", "markdown", "txt"}
        and header_count >= 2
        and noise_ratio < 0.002
        and table_lines < 50
    )
    well_structured_text = header_count >= 3 and noise_ratio < 0.003 and table_lines < 80

    if clean_markdown or well_structured_text:
        return {
            "force_llm": False,
            "clean_markdown": True,
            "reason": "well_structured_markdown",
            "noise_ratio": noise_ratio,
            "header_count": header_count,
        }
    if severe_noise:
        return {
            "force_llm": True,
            "clean_markdown": False,
            "reason": "severe_ocr_noise",
            "noise_ratio": noise_ratio,
            "header_count": header_count,
        }
    if extension in {"pdf", "doc", "docx", "ppt", "pptx"} and moderate_noise and header_count == 0:
        return {
            "force_llm": True,
            "clean_markdown": False,
            "reason": f"noisy_{extension or 'document'}",
            "noise_ratio": noise_ratio,
            "header_count": header_count,
        }
    return {
        "force_llm": False,
        "clean_markdown": False,
        "reason": "weak_structure" if header_count == 0 else "light_cleanup_only",
        "noise_ratio": noise_ratio,
        "header_count": header_count,
    }


async def llm_heal_full(text: str) -> tuple[str, int]:
    """Heal long text by paragraph batches."""

    if len(text) <= _HEAL_CHUNK_SIZE:
        return await llm_heal_chunk(text), 1

    paragraphs = text.split("\n\n")
    chunks: list[str] = []
    current: list[str] = []
    current_size = 0
    for paragraph in paragraphs:
        if current_size + len(paragraph) > _HEAL_CHUNK_SIZE and current:
            chunks.append("\n\n".join(current))
            current = []
            current_size = 0
        current.append(paragraph)
        current_size += len(paragraph)
    if current:
        chunks.append("\n\n".join(current))

    healed = await asyncio.gather(*(llm_heal_chunk(chunk) for chunk in chunks))
    return "\n\n".join(healed), len(chunks)
