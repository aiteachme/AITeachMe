"""Shared file-format groupings for ingest parsing."""

from __future__ import annotations

MARKDOWN_EXTENSIONS = frozenset({".md", ".markdown"})

PROSE_TEXT_EXTENSIONS = frozenset(
    {
        ".txt",
        ".text",
        ".rst",
        ".adoc",
        ".asciidoc",
        ".org",
    }
)

STRUCTURED_TEXT_LANGUAGE_HINTS: dict[str, str] = {
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".jsonl": "json",
    ".ndjson": "json",
    ".toml": "toml",
    ".ini": "ini",
    ".cfg": "ini",
    ".conf": "ini",
    ".env": "bash",
    ".properties": "properties",
    ".csv": "csv",
    ".tsv": "tsv",
    ".xml": "xml",
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".scss": "scss",
    ".less": "less",
    ".js": "javascript",
    ".jsx": "jsx",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".py": "python",
    ".java": "java",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".go": "go",
    ".rs": "rust",
    ".php": "php",
    ".rb": "ruby",
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "zsh",
    ".ps1": "powershell",
    ".bat": "bat",
    ".cmd": "bat",
    ".sql": "sql",
    ".log": "text",
}

TEXT_EXTENSIONS = frozenset(
    set(MARKDOWN_EXTENSIONS)
    | set(PROSE_TEXT_EXTENSIONS)
    | set(STRUCTURED_TEXT_LANGUAGE_HINTS)
)

IMAGE_EXTENSIONS = frozenset(
    {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
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
