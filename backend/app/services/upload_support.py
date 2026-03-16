"""文件系统路径辅助函数。"""

from __future__ import annotations

from pathlib import Path

from app.core.config import get_settings


def get_data_dir() -> Path:
    """返回运行时数据根目录。"""

    return Path(get_settings().data_dir)


def build_subject_dir(subject: str) -> Path:
    """返回学科目录。"""

    return get_data_dir() / subject


def build_raw_dir(subject: str) -> Path:
    """返回原始文件目录。"""

    return build_subject_dir(subject) / "raw"


def build_markdown_dir(subject: str) -> Path:
    """返回 Markdown 目录。"""

    return build_subject_dir(subject) / "markdown"


def build_assets_dir(subject: str) -> Path:
    """返回资源目录。"""

    return build_subject_dir(subject) / "assets"


def build_temp_dir(subject: str) -> Path:
    """返回临时目录。"""

    return build_subject_dir(subject) / "temp"


def build_raw_file_path(subject: str, record_id: int, extension: str) -> Path:
    """根据文件 ID 生成原始文件路径。"""

    normalized_extension = extension if extension.startswith(".") else f".{extension}"
    return build_raw_dir(subject) / f"{record_id}{normalized_extension}"


def build_markdown_path(subject: str, raw_file_id: int) -> Path:
    """根据文件 ID 生成 Markdown 路径。"""

    return build_markdown_dir(subject) / f"{raw_file_id}.md"


def build_asset_dir(subject: str, raw_file_id: int) -> Path:
    """根据文件 ID 生成资源目录路径。"""

    return build_assets_dir(subject) / str(raw_file_id)
