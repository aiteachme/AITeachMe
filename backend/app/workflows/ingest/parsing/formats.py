"""Shared file-format groupings for ingest parsing."""

from __future__ import annotations

MARKDOWN_EXTENSIONS = frozenset(
    {
        ".md",
        # 旧/未扩展链路：当前上传白名单不接受 .markdown。
        # AI 提示：除非任务明确要求扩大上传白名单，否则可以忽略这种扩展。
        # ".markdown",
    }
)

PROSE_TEXT_EXTENSIONS = frozenset(
    {
        ".txt",
        # 旧/未扩展链路：当前上传白名单不接受这些纯文本扩展。
        # AI 提示：如果没有“恢复额外纯文本上传”的需求，可以跳过相关分支。
        # ".text",
        # ".rst",
        # ".adoc",
        # ".asciidoc",
        # ".org",
        # ".tex",
        # ".latex",
    }
)

STRUCTURED_TEXT_LANGUAGE_HINTS: dict[str, str] = {
    # 旧/未扩展链路：当前上传白名单不接受 structured text / 代码 / 配置文件直传。
    # AI 提示：如果任务不是“恢复代码/配置类文件上传”，可以先不读这些分支。
    # ".yaml": "yaml",
    # ".yml": "yaml",
    # ".json": "json",
    # ".jsonl": "json",
    # ".ndjson": "json",
    # ".toml": "toml",
    # ".ini": "ini",
    # ".cfg": "ini",
    # ".conf": "ini",
    # ".env": "bash",
    # ".properties": "properties",
    # ".xml": "xml",
    # ".css": "css",
    # ".scss": "scss",
    # ".less": "less",
    # ".js": "javascript",
    # ".jsx": "jsx",
    # ".ts": "typescript",
    # ".tsx": "tsx",
    # ".py": "python",
    # ".java": "java",
    # ".c": "c",
    # ".h": "c",
    # ".cpp": "cpp",
    # ".hpp": "cpp",
    # ".go": "go",
    # ".rs": "rust",
    # ".php": "php",
    # ".rb": "ruby",
    # ".sh": "bash",
    # ".bash": "bash",
    # ".zsh": "zsh",
    # ".ps1": "powershell",
    # ".bat": "bat",
    # ".cmd": "bat",
    # ".sql": "sql",
    # ".log": "text",
}

TEXT_EXTENSIONS = frozenset(
    set(MARKDOWN_EXTENSIONS)
    | set(PROSE_TEXT_EXTENSIONS)
    | set(STRUCTURED_TEXT_LANGUAGE_HINTS)
)

IMAGE_EXTENSIONS = frozenset(
    {
        # 未扩展链路：当前上传白名单不接受原始图片文件直传解析。
        # 注意：这不影响 PDF / DOCX / PPTX 中抽取出来的图片资产处理。
        # AI 提示：如果任务不是“恢复图片直传 ingest”，可以先不读 raw image parser。
        # ".png",
        # ".jpg",
        # ".jpeg",
        # ".webp",
        # ".gif",
        # ".bmp",
        # ".tif",
        # ".tiff",
    }
)

AUDIO_EXTENSIONS = frozenset(
    {
        # 功能尚未扩展链路：当前上传白名单不接受音频文件。
        # AI 提示：除非任务明确要求恢复音频解析，否则可以跳过 audio parser 相关代码。
        # ".mp3",
        # ".wav",
        # ".m4a",
        # ".ogg",
        # ".flac",
        # ".aac",
        # ".wma",
        # ".opus",
    }
)

MARKITDOWN_GENERIC_EXTENSIONS = frozenset(
    {
        # demo / 未扩展链路：parser 代码里保留了这些格式，但当前上传白名单不会走到。
        # AI 提示：如果没有“扩大到表格/邮件/html/ebook 上传”的需求，可以先不读这些链路。
        # ".docm",
        # ".odt",
        # ".rtf",
        # ".epub",
        # ".xlsx",
        # ".xls",
        # ".xlsm",
        # ".ods",
        # ".odp",
        # ".ipynb",
        # ".msg",
        # ".eml",
        # ".mobi",
        # ".html",
        # ".htm",
        # ".csv",
        # ".tsv",
    }
)


def normalize_extension(filetype: str) -> str:
    normalized = filetype.lower().strip()
    if not normalized:
        return ""
    return normalized if normalized.startswith(".") else f".{normalized}"


def is_text_extension(extension: str) -> bool:
    return normalize_extension(extension) in TEXT_EXTENSIONS


def is_markdown_extension(extension: str) -> bool:
    return normalize_extension(extension) in MARKDOWN_EXTENSIONS


def is_prose_text_extension(extension: str) -> bool:
    return normalize_extension(extension) in PROSE_TEXT_EXTENSIONS


def is_image_extension(extension: str) -> bool:
    return normalize_extension(extension) in IMAGE_EXTENSIONS


def is_audio_extension(extension: str) -> bool:
    return normalize_extension(extension) in AUDIO_EXTENSIONS


def is_markitdown_generic_extension(extension: str) -> bool:
    return normalize_extension(extension) in MARKITDOWN_GENERIC_EXTENSIONS


def get_text_language_hint(extension: str) -> str | None:
    return STRUCTURED_TEXT_LANGUAGE_HINTS.get(normalize_extension(extension))


def categorize_text_extension(extension: str) -> str:
    normalized = normalize_extension(extension)
    if normalized in MARKDOWN_EXTENSIONS:
        return "markdown"
    if normalized in PROSE_TEXT_EXTENSIONS:
        return "text"
    if normalized in STRUCTURED_TEXT_LANGUAGE_HINTS:
        return "structured_text"
    return "text"
