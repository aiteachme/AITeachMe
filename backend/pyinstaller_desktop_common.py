"""Shared PyInstaller rules for the local desktop backend package.

The desktop bundle runs in APP_MODE=local and should not carry cloud-only,
audio, OCR, or heavyweight document-parser optional dependencies. PyInstaller
hooks can still collect those resources through transitive imports, so the spec
files use this module to filter hidden imports and collected TOC entries.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata


EXCLUDED_MODULE_PREFIXES = (
    "asyncpg",
    "awscrt",
    "boto3",
    "botocore",
    "cv2",
    "faster_whisper",
    "fitz",
    "llama_index.vector_stores.postgres",
    "magika",
    "markitdown",
    "matplotlib",
    "nltk_data",
    "numba",
    "odf",
    "onnxruntime",
    "openpyxl",
    "pandas",
    "pdfminer",
    "pdfplumber",
    "pgvector",
    "psycopg",
    "psycopg2",
    "psycopg2_binary",
    "psycopg_binary",
    "pyaudio",
    "pyarrow",
    "pydub",
    "pymupdf",
    "pymupdf4llm",
    "pocketsphinx",
    "pypdf",
    "pypdfium2",
    "pypdfium2_raw",
    "PyPDF2",
    "rapidocr_onnxruntime",
    "s3transfer",
    "scipy",
    "soundfile",
    "speech_recognition",
    "speechrecognition",
    "tables",
    "tkinter",
    "_tkinter",
    "tcl",
    "tk",
    "whisper",
    "xlrd",
    "xlwt",
)

EXCLUDED_APP_MODULE_PREFIXES = (
    # Local desktop packages always use LocalArtifactStore. Keeping the S3
    # implementation as a hidden import pulls boto3/botocore and their service
    # catalog into the bundled backend.
    "app.shared.infra.storage.s3_store",
)

EXCLUDED_RESOURCE_PREFIXES = (
    *EXCLUDED_MODULE_PREFIXES,
    "_tcl_data",
    "_tk_data",
    "grpc_tools",
    "llama_index/core/_static/nltk_cache",
    "pandas.libs",
    "psycopg2_binary.libs",
    "psycopg_binary.libs",
)

DATA_PACKAGES = (
    "alembic",
    "fastapi",
    "langgraph",
    "llama_index",
    "pydantic",
    "pydantic_settings",
    "sqlalchemy",
    "sqlite_vec",
    "sqlmodel",
    "uvicorn",
)

LITELLM_DATA_INCLUDES = (
    "anthropic_beta_headers_config.json",
    "cost.json",
    "model_prices_and_context_window_backup.json",
    "policy_templates_backup.json",
    "provider_endpoints_support_backup.json",
)

UVICORN_HIDDENIMPORT_PACKAGES = (
    "uvicorn",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
)


def _normalize_module_name(value: str) -> str:
    return value.replace("\\", ".").replace("/", ".").strip(".").lower()


def _normalize_resource_name(value: str) -> str:
    return value.replace("\\", "/").lstrip("./").lower()


def _matches_prefix(name: str, prefix: str) -> bool:
    normalized_name = name.lower()
    normalized_prefix = prefix.lower()
    return (
        normalized_name == normalized_prefix
        or normalized_name.startswith(f"{normalized_prefix}.")
        or normalized_name.startswith(f"{normalized_prefix}/")
    )


def is_excluded_module(module_name: str) -> bool:
    normalized = _normalize_module_name(module_name)
    return any(_matches_prefix(normalized, prefix) for prefix in EXCLUDED_MODULE_PREFIXES)


def include_app_submodule(module_name: str) -> bool:
    normalized = _normalize_module_name(module_name)
    if is_excluded_module(normalized):
        return False
    return not any(_matches_prefix(normalized, prefix) for prefix in EXCLUDED_APP_MODULE_PREFIXES)


def include_runtime_submodule(module_name: str) -> bool:
    return not is_excluded_module(module_name)


def collect_app_hiddenimports() -> list[str]:
    return collect_submodules("app", filter=include_app_submodule)


def collect_runtime_hiddenimports() -> list[str]:
    hiddenimports: list[str] = []
    for package_name in (
        "litellm.litellm_core_utils.tokenizers",
        "tiktoken_ext",
        *UVICORN_HIDDENIMPORT_PACKAGES,
    ):
        hiddenimports += collect_submodules(package_name, filter=include_runtime_submodule)
    return filter_hiddenimports(hiddenimports)


def collect_runtime_datas() -> list[tuple[str, str]]:
    datas: list[tuple[str, str]] = [
        ("alembic.ini", "."),
        ("migrations", "migrations"),
        ("pyproject.toml", "."),
    ]
    datas += copy_metadata("aiteachme-backend")

    bundled_env_path = Path("../packaging/desktop/artifacts/generated-configs/aiteachme_bundled_env.enc.json")
    if bundled_env_path.exists():
        datas.append((str(bundled_env_path), "configs"))

    for package_name in DATA_PACKAGES:
        datas += collect_data_files(package_name)

    datas += collect_data_files("litellm", includes=list(LITELLM_DATA_INCLUDES))
    datas += collect_data_files("litellm.containers", includes=["endpoints.json"])
    datas += collect_data_files("litellm.litellm_core_utils.tokenizers")
    return filter_toc_entries(datas)


def filter_hiddenimports(hiddenimports: Iterable[str]) -> list[str]:
    return [name for name in hiddenimports if not is_excluded_module(name)]


def is_excluded_resource(resource_name: str) -> bool:
    normalized = _normalize_resource_name(resource_name)
    dotted = _normalize_module_name(normalized)
    for prefix in EXCLUDED_RESOURCE_PREFIXES:
        normalized_prefix = _normalize_resource_name(prefix)
        dotted_prefix = _normalize_module_name(prefix)
        if _matches_prefix(normalized, normalized_prefix) or _matches_prefix(dotted, dotted_prefix):
            return True
    return False


def filter_toc_entries(entries):
    """Remove excluded files from PyInstaller TOC/list-like collections."""

    return [entry for entry in entries if entry and not is_excluded_resource(str(entry[0]))]


__all__ = [
    "EXCLUDED_MODULE_PREFIXES",
    "collect_app_hiddenimports",
    "collect_runtime_datas",
    "collect_runtime_hiddenimports",
    "filter_hiddenimports",
    "filter_toc_entries",
]
