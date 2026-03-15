"""
上传编排服务

流程：校验 → 临时落盘 → 创建 RawFile → 移动到最终位置 → 解析 → 创建 Knowledge → 触发 Digest。
Digest 引擎通过 FastAPI BackgroundTasks 异步执行，不阻塞上传接口。
"""

from __future__ import annotations

import shutil
from pathlib import Path

import structlog
from fastapi import UploadFile
from sqlmodel import Session

from app.core.config import get_settings
from app.core.exceptions import FileTooLargeError, FileParseError
from app.agents.ingest.orchestrator import parse_file, SUPPORTED_EXTENSIONS
from app.repositories.ingest_repo import (
    create_raw_file,
    update_parse_status,
    delete_raw_file,
)
from app.repositories.knowledge_repo import create_knowledge
from app.repositories.models import RawFile, Knowledge, ParseStatus, PipelineStage
from app.services.presenters import require_id
from app.services.upload_support import (
    build_markdown_path,
    build_raw_file_path,
    get_data_dir,
)
from app.utils.subject import validate_subject

logger = structlog.get_logger()


async def handle_upload(
    session: Session,
    file: UploadFile,
    subject: str,
) -> RawFile:
    """处理文件上传：校验 → 临时落盘 → 创建记录 → 移动到最终位置。

    Returns:
        创建的 RawFile 记录（含 task_id = raw_file.id）。
    """
    settings = get_settings()
    subject = validate_subject(subject)

    # 校验文件大小（读取全部内容检查）
    content = await file.read()
    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise FileTooLargeError(settings.max_upload_size_mb)

    filename = file.filename or "unknown"
    ext = Path(filename).suffix.lower()

    # 1. 保存到 data/temp/
    data_dir = get_data_dir()
    temp_dir = data_dir / "temp"
    temp_dir.mkdir(parents=True, exist_ok=True)

    import uuid
    temp_name = f"{uuid.uuid4().hex}{ext}"
    temp_path = temp_dir / temp_name
    temp_path.write_bytes(content)

    # 2. 创建 RawFile 记录（pending）
    raw_file = RawFile(
        subject=subject,
        filename=filename,
        filetype=ext.lstrip("."),
        file_path=str(temp_path),  # 临时路径，后续更新
        parse_status=ParseStatus.PENDING,
    )
    raw_file = create_raw_file(session, raw_file)
    record_id = require_id(raw_file.id, "RawFile.id")

    # 3. 移动到 data/raw/<prefix>/<id>.<ext>
    final_path = build_raw_file_path(record_id, ext)
    final_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        shutil.move(str(temp_path), str(final_path))
    except Exception as exc:
        logger.error("upload_move_failed", record_id=record_id, error=str(exc))
        # 回滚数据库记录
        delete_raw_file(session, record_id)
        # 清理临时文件
        temp_path.unlink(missing_ok=True)
        raise FileParseError(filename, reason=f"文件移动失败：{exc}") from exc

    # 更新 file_path 为最终位置
    raw_file.file_path = str(final_path)
    session.add(raw_file)
    session.commit()
    session.refresh(raw_file)

    logger.info("upload_complete", record_id=record_id, subject=subject, filename=filename)
    return raw_file


async def process_and_parse(session: Session, raw_file_id: int) -> Knowledge | None:
    """解析文件并创建 Knowledge 记录。

    流程：更新 parse_status=parsing → 调用解析器 → 保存 Markdown → 更新 parsed → 创建 Knowledge。
    失败时更新 parse_status=parse_failed。

    Returns:
        创建的 Knowledge 记录，解析失败时返回 None。
    """
    from app.repositories.ingest_repo import get_raw_file_by_id

    raw_file = get_raw_file_by_id(session, raw_file_id)
    if raw_file is None:
        logger.error("parse_raw_file_not_found", raw_file_id=raw_file_id)
        return None

    # 更新为 parsing
    update_parse_status(session, raw_file_id, ParseStatus.PARSING)

    file_path = Path(raw_file.file_path)
    try:
        markdown_text = await parse_file(file_path)
    except Exception as exc:
        logger.error("parse_failed", raw_file_id=raw_file_id, error=str(exc))
        update_parse_status(session, raw_file_id, ParseStatus.PARSE_FAILED)
        return None

    # 保存 Markdown 到 data/markdown/<prefix>/<id>.md
    md_path = build_markdown_path(raw_file_id)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(markdown_text, encoding="utf-8")

    # 更新 parse_status 为 parsed
    update_parse_status(session, raw_file_id, ParseStatus.PARSED)

    # 创建 Knowledge 记录（pipeline_stage=pending）
    title = raw_file.filename
    knowledge = Knowledge(
        subject=raw_file.subject,
        raw_file_id=raw_file_id,
        title=title,
        markdown_content="",  # Digest 引擎的 store_knowledge 节点会填充
        pipeline_stage=PipelineStage.PENDING,
    )
    knowledge = create_knowledge(session, knowledge)
    knowledge_id = require_id(knowledge.id, "Knowledge.id")

    logger.info(
        "parse_complete",
        raw_file_id=raw_file_id,
        knowledge_id=knowledge_id,
        md_path=str(md_path),
    )
    return knowledge
