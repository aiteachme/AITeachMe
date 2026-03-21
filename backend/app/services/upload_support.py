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


# ── DocGen 知识文档路径 ──


def build_knowledge_docs_dir(subject: str) -> Path:
    """返回知识文档产出目录。"""

    return build_subject_dir(subject) / "knowledge_docs"


def build_knowledge_doc_path(subject: str, chapter_index: int, title: str) -> Path:
    """根据章节序号和标题生成知识文档 Markdown 路径。"""

    safe_title = title.replace("/", "_").replace("\\", "_").replace(" ", "_")[:50]
    filename = f"chapter_{chapter_index:02d}_{safe_title}.md"
    return build_knowledge_docs_dir(subject) / filename


def build_merged_knowledge_base_path(subject: str) -> Path:
    """返回合并后的完整知识库文件路径。"""

    return build_knowledge_docs_dir(subject) / "merged_knowledge_base.md"


def build_docgen_intermediate_dir(subject: str) -> Path:
    """返回 DocGen 中间产物目录（清洗/大纲等过程文件）。"""

    return build_subject_dir(subject) / "docgen_intermediate"
