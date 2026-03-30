"""Artifact management for cross-lane coordination."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, TypeVar

import structlog
from pydantic import BaseModel

from app.utils.path_helpers import build_subject_dir

logger = structlog.get_logger()

T = TypeVar("T", bound=BaseModel)


def get_build_artifacts_dir(subject: str, session_id: str | None = None) -> Path:
    """获取构建工件目录

    Args:
        subject: 科目标识
        session_id: 会话 ID（可选，默认使用 "latest"）

    Returns:
        Path: 工件目录路径
    """

    subject_dir = build_subject_dir(subject)
    session_id = session_id or "latest"
    artifacts_dir = subject_dir / "digest_builds" / session_id / "shared"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    return artifacts_dir


async def publish_artifact(
    artifact_name: str,
    artifact_data: BaseModel,
    subject: str | None = None,
    session_id: str | None = None,
) -> None:
    """发布工件（跨 lane 协作）

    Args:
        artifact_name: 工件名称
        artifact_data: 工件数据
        subject: 科目标识（可选）
        session_id: 会话 ID（可选）
    """

    if not subject:
        logger.warning("publish_artifact_no_subject", artifact_name=artifact_name)
        return

    artifacts_dir = get_build_artifacts_dir(subject, session_id)
    artifact_path = artifacts_dir / f"{artifact_name}.json"

    # 异步写入
    await asyncio.to_thread(
        artifact_path.write_text,
        artifact_data.model_dump_json(indent=2),
        encoding="utf-8",
    )

    logger.info("artifact_published", artifact_name=artifact_name, path=str(artifact_path))


async def try_read_artifact(
    artifact_name: str,
    model_class: type[T],
    subject: str | None = None,
    session_id: str | None = None,
    timeout_ms: int = 500,
) -> T | None:
    """尝试读取工件（软读取，有超时）

    Args:
        artifact_name: 工件名称
        model_class: 模型类
        subject: 科目标识（可选）
        session_id: 会话 ID（可选）
        timeout_ms: 超时时间（毫秒）

    Returns:
        T | None: 工件数据，超时或不存在返回 None
    """

    if not subject:
        return None

    artifacts_dir = get_build_artifacts_dir(subject, session_id)
    artifact_path = artifacts_dir / f"{artifact_name}.json"

    try:
        # 带超时的读取
        content = await asyncio.wait_for(
            asyncio.to_thread(artifact_path.read_text, encoding="utf-8"),
            timeout=timeout_ms / 1000.0,
        )

        data = model_class.model_validate_json(content)
        logger.info("artifact_read", artifact_name=artifact_name)
        return data

    except asyncio.TimeoutError:
        logger.debug("artifact_read_timeout", artifact_name=artifact_name, timeout_ms=timeout_ms)
        return None

    except FileNotFoundError:
        logger.debug("artifact_not_found", artifact_name=artifact_name)
        return None

    except Exception as exc:
        logger.warning("artifact_read_failed", artifact_name=artifact_name, error=str(exc))
        return None


def read_artifact_sync(
    artifact_name: str,
    model_class: type[T],
    subject: str,
    session_id: str | None = None,
) -> T | None:
    """同步读取工件

    Args:
        artifact_name: 工件名称
        model_class: 模型类
        subject: 科目标识
        session_id: 会话 ID（可选）

    Returns:
        T | None: 工件数据，不存在返回 None
    """

    artifacts_dir = get_build_artifacts_dir(subject, session_id)
    artifact_path = artifacts_dir / f"{artifact_name}.json"

    try:
        content = artifact_path.read_text(encoding="utf-8")
        return model_class.model_validate_json(content)
    except FileNotFoundError:
        return None
    except Exception as exc:
        logger.warning("artifact_read_sync_failed", artifact_name=artifact_name, error=str(exc))
        return None
