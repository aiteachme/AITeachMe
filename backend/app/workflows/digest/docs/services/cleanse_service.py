"""清洗阶段纯函数服务。"""

from __future__ import annotations

import re

import structlog

from app.core.llm import acompletion
from app.core.model_router import TaskType
from app.workflows.digest.prompts.docgen_prompts import CLEANSE_PROMPT

logger = structlog.get_logger()

# ── 正则 ──

_PAGE_NUMBER_PATTERNS = [
    re.compile(r"^\s*-\s*\d+\s*-\s*$", re.MULTILINE),
    re.compile(r"^\s*第\s*\d+\s*页\s*$", re.MULTILINE),
    re.compile(r"^\s*Page\s+\d+\s*$", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^\s*\d+\s*$", re.MULTILINE),
]
_EXCESSIVE_NEWLINES = re.compile(r"\n{3,}")
_INVISIBLE_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\ufeff]")

_HEAL_CHUNK_SIZE = 2000


def rule_based_cleanse(text: str) -> str:
    """规则降噪：页码、不可见字符、多余空行。"""
    for pat in _PAGE_NUMBER_PATTERNS:
        text = pat.sub("", text)
    text = _INVISIBLE_CHARS.sub("", text)
    text = _EXCESSIVE_NEWLINES.sub("\n\n", text)
    return text.strip()


def stitch_sentences(text: str) -> str:
    """边界缝合：断句检测，跨行合并。"""
    lines = text.split("\n")
    stitched: list[str] = []
    endings = {"。", "！", "？", "；", ".", "!", "?", ";", "：", ":"}

    for i, line in enumerate(lines):
        stripped = line.rstrip()
        stitched.append(line)
        if not stripped:
            continue
        if i + 1 < len(lines):
            nxt = lines[i + 1].strip()
            if (
                stripped[-1] not in endings
                and nxt
                and not nxt.startswith("#")
                and not nxt.startswith("-")
                and not nxt.startswith("*")
                and not nxt.startswith(">")
                and not re.match(r"^\d+\.", nxt)
            ):
                if stitched[-1].endswith("\n"):
                    stitched[-1] = stitched[-1].rstrip("\n")

    return "\n".join(stitched)


async def llm_heal_chunk(text: str) -> str:
    """对单个文本块执行 LLM 语义自愈。"""
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


async def llm_heal_full(text: str) -> str:
    """将长文本按段落切块后逐块 LLM 自愈（用于单文件内部）。"""
    if len(text) <= _HEAL_CHUNK_SIZE:
        return await llm_heal_chunk(text)

    paragraphs = text.split("\n\n")
    chunks: list[str] = []
    cur: list[str] = []
    cur_size = 0
    for para in paragraphs:
        if cur_size + len(para) > _HEAL_CHUNK_SIZE and cur:
            chunks.append("\n\n".join(cur))
            cur, cur_size = [], 0
        cur.append(para)
        cur_size += len(para)
    if cur:
        chunks.append("\n\n".join(cur))

    import asyncio
    healed = await asyncio.gather(*(llm_heal_chunk(c) for c in chunks))
    return "\n\n".join(healed)
