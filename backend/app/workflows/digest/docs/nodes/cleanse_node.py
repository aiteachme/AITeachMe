"""阶段一：数据清洗与标准化节点。

从 Ingest 产出的原始 Markdown 文件读取内容，经过规则降噪、
边界缝合和轻量 LLM 语义自愈，输出纯净文本块。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import structlog

from app.core.database import managed_session
from app.core.llm import acompletion
from app.core.model_router import TaskType
from app.models.raw_file import RawFile
from app.repositories.knowledge import docgen_repo
from app.services.upload_support import build_docgen_intermediate_dir
from app.workflows.common.context import WorkflowContext
from app.workflows.digest.docs.state import DocGenState
from app.workflows.digest.prompts.docgen_prompts import CLEANSE_PROMPT

logger = structlog.get_logger()

# ── 规则降噪正则 ──

# 独立页码行（如 "- 12 -"、"第 3 页"、"Page 5"）
_PAGE_NUMBER_PATTERNS = [
    re.compile(r"^\s*-\s*\d+\s*-\s*$", re.MULTILINE),
    re.compile(r"^\s*第\s*\d+\s*页\s*$", re.MULTILINE),
    re.compile(r"^\s*Page\s+\d+\s*$", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^\s*\d+\s*$", re.MULTILINE),  # 纯数字行（可能是页码）
]

# 多余空行（连续 3 个以上空行合并为 2 个）
_EXCESSIVE_NEWLINES = re.compile(r"\n{3,}")

# 不可见特殊字符
_INVISIBLE_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\ufeff]")

# 分块大小（字符数）
_CLEANSE_CHUNK_SIZE = 2000


def _rule_based_cleanse(text: str) -> str:
    """执行规则降噪：页码、不可见字符、多余空行。"""

    for pattern in _PAGE_NUMBER_PATTERNS:
        text = pattern.sub("", text)
    text = _INVISIBLE_CHARS.sub("", text)
    text = _EXCESSIVE_NEWLINES.sub("\n\n", text)
    return text.strip()


def _stitch_broken_sentences(text: str) -> str:
    """边界缝合：如果一段结尾没有终结符，且下一段不是标题，则移除换行合并。"""

    lines = text.split("\n")
    stitched: list[str] = []
    sentence_endings = {"。", "！", "？", "；", ".", "!", "?", ";", "：", ":"}

    for i, line in enumerate(lines):
        stripped = line.rstrip()
        if not stripped:
            stitched.append(line)
            continue

        stitched.append(line)

        # 检查是否需要与下一行缝合
        if i + 1 < len(lines):
            next_line = lines[i + 1].strip()
            # 当前行不以终结符结尾，且下一行不是标题、不是空行、不是列表项
            if (
                stripped
                and stripped[-1] not in sentence_endings
                and next_line
                and not next_line.startswith("#")
                and not next_line.startswith("-")
                and not next_line.startswith("*")
                and not next_line.startswith(">")
                and not re.match(r"^\d+\.", next_line)
            ):
                # 移除当前行末的换行，让文本自然连贯
                if stitched and stitched[-1].endswith("\n"):
                    stitched[-1] = stitched[-1].rstrip("\n")

    return "\n".join(stitched)


async def _llm_semantic_heal(text: str) -> str:
    """轻量 LLM 语义自愈：修复 OCR 错别字，不改原文结构。

    将文本按 _CLEANSE_CHUNK_SIZE 切块后逐块修复。
    """

    if len(text) <= _CLEANSE_CHUNK_SIZE:
        prompt = CLEANSE_PROMPT.format(text=text)
        try:
            result = await acompletion(
                [{"role": "user", "content": prompt}],
                task_type=TaskType.DOCGEN_LIGHT,
            )
            return result.strip()
        except Exception as exc:
            logger.warning("cleanse_llm_heal_failed", error=str(exc))
            return text

    # 按段落切块
    paragraphs = text.split("\n\n")
    chunks: list[str] = []
    current_chunk: list[str] = []
    current_size = 0

    for para in paragraphs:
        if current_size + len(para) > _CLEANSE_CHUNK_SIZE and current_chunk:
            chunks.append("\n\n".join(current_chunk))
            current_chunk = []
            current_size = 0
        current_chunk.append(para)
        current_size += len(para)

    if current_chunk:
        chunks.append("\n\n".join(current_chunk))

    healed_chunks: list[str] = []
    for chunk in chunks:
        prompt = CLEANSE_PROMPT.format(text=chunk)
        try:
            result = await acompletion(
                [{"role": "user", "content": prompt}],
                task_type=TaskType.DOCGEN_LIGHT,
            )
            healed_chunks.append(result.strip())
        except Exception as exc:
            logger.warning("cleanse_llm_chunk_heal_failed", error=str(exc))
            healed_chunks.append(chunk)

    return "\n\n".join(healed_chunks)


def build_cleanse_node(*, context: WorkflowContext):
    """构建数据清洗节点。"""

    async def cleanse_node(state: DocGenState) -> dict:
        node_logger = context.get_logger().bind(node="cleanse")
        node_logger.info("cleanse_started")

        subject = state["subject"]
        file_ids = state["file_ids"]
        job_id = state["job_id"]

        # 更新任务状态
        with managed_session() as session:
            docgen_repo.update_docgen_job(
                session, job_id, current_step="cleansing", progress=5,
            )

        # 1) 从数据库加载原始文件信息，读取 Markdown 内容
        clean_chunks: list[dict] = []
        with managed_session() as session:
            for file_id in file_ids:
                raw_file = session.get(RawFile, file_id)
                if raw_file is None or not raw_file.markdown_path:
                    node_logger.warning("cleanse_file_skipped", file_id=file_id, reason="no_markdown")
                    continue

                md_path = Path(raw_file.markdown_path)
                if not md_path.exists():
                    node_logger.warning("cleanse_file_skipped", file_id=file_id, reason="file_not_found")
                    continue

                raw_content = md_path.read_text(encoding="utf-8")
                filename = raw_file.filename

                # 2) 规则降噪
                cleaned = _rule_based_cleanse(raw_content)

                # 3) 边界缝合
                cleaned = _stitch_broken_sentences(cleaned)

                # 4) LLM 语义自愈
                cleaned = await _llm_semantic_heal(cleaned)

                clean_chunks.append({
                    "file_id": file_id,
                    "content": cleaned,
                    "source_filename": filename,
                })
                node_logger.info(
                    "cleanse_file_done",
                    file_id=file_id,
                    original_chars=len(raw_content),
                    cleaned_chars=len(cleaned),
                )

        if not clean_chunks:
            return {"error": "没有可用的 Markdown 文件进行清洗。"}

        # 5) 保存中间产物到磁盘
        intermediate_dir = build_docgen_intermediate_dir(subject)
        intermediate_dir.mkdir(parents=True, exist_ok=True)
        for i, chunk in enumerate(clean_chunks):
            chunk_path = intermediate_dir / f"clean_chunk_{i:02d}_{chunk['source_filename']}.md"
            chunk_path.write_text(chunk["content"], encoding="utf-8")

        # 保存清洗摘要
        summary_path = intermediate_dir / "cleanse_summary.json"
        summary_data = [
            {
                "index": i,
                "file_id": c["file_id"],
                "source_filename": c["source_filename"],
                "char_count": len(c["content"]),
            }
            for i, c in enumerate(clean_chunks)
        ]
        summary_path.write_text(json.dumps(summary_data, ensure_ascii=False, indent=2), encoding="utf-8")

        with managed_session() as session:
            docgen_repo.update_docgen_job(session, job_id, progress=20)

        node_logger.info("cleanse_completed", chunk_count=len(clean_chunks))
        return {"clean_chunks": clean_chunks}

    return cleanse_node
