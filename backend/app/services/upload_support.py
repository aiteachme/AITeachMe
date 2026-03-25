"""Filesystem path helpers for runtime data."""

from __future__ import annotations

from pathlib import Path
import re

from app.core.config import get_settings


def get_data_dir() -> Path:
    """Return the runtime data root directory."""

    return Path(get_settings().data_dir).resolve()


def build_subject_dir(subject: str) -> Path:
    """Return the subject data directory."""

    return get_data_dir() / subject


def build_raw_dir(subject: str) -> Path:
    """Return the raw file directory."""

    return build_subject_dir(subject) / "raw_files"


def build_raw_markdown_dir(subject: str) -> Path:
    """Return the parsed raw-markdown directory."""

    return build_subject_dir(subject) / "raw_markdowns"

def build_assets_dir(subject: str) -> Path:
    """Return the flattened extracted-asset directory."""

    return build_subject_dir(subject) / "assets"


def build_temp_dir(subject: str) -> Path:
    """Return the temp directory."""

    return build_subject_dir(subject) / "temp"


def build_debug_dir(subject: str) -> Path:
    """Return the subject-level debug directory."""

    return build_subject_dir(subject) / "debug"


def build_raw_file_path(subject: str, record_id: int, extension: str) -> Path:
    """Build the raw file path from a file id and extension."""

    normalized_extension = extension if extension.startswith(".") else f".{extension}"
    return build_raw_dir(subject) / f"{record_id}{normalized_extension}"


def build_raw_markdown_path(subject: str, raw_file_id: int) -> Path:
    """Build the parsed raw-markdown path for a raw file."""

    return build_raw_markdown_dir(subject) / f"{raw_file_id}.md"


def build_asset_dir(subject: str, raw_file_id: int) -> Path:
    """Return the shared flattened assets directory for a raw file."""

    del raw_file_id
    return build_assets_dir(subject)


def build_knowledge_markdown_dir(subject: str) -> Path:
    """Return the published knowledge-markdowns directory."""

    return build_subject_dir(subject) / "knowledge_markdowns"


def build_knowledge_markdown_build_dir(subject: str) -> Path:
    """Return the knowledge-markdowns build/intermediate directory."""

    return build_knowledge_markdown_dir(subject) / "_build"


def _sanitize_doc_title(title: str) -> str:
    return title.replace("/", "_").replace("\\", "_").replace(" ", "_")[:50]


def build_knowledge_doc_path(subject: str, chapter_index: int, title: str) -> Path:
    """Build the published chapter markdown path."""

    filename = f"chapter_{chapter_index:02d}_{_sanitize_doc_title(title)}.md"
    return build_knowledge_markdown_dir(subject) / filename


def build_knowledge_doc_build_path(subject: str, chapter_index: int, title: str) -> Path:
    """Build the staging chapter markdown path."""

    filename = f"chapter_{chapter_index:02d}_{_sanitize_doc_title(title)}.md"
    return build_knowledge_markdown_build_dir(subject) / filename


def build_merged_knowledge_base_path(subject: str) -> Path:
    """Return the published merged knowledge markdown path."""

    return build_knowledge_markdown_dir(subject) / "merged_knowledge_base.md"


def build_merged_knowledge_base_build_path(subject: str) -> Path:
    """Return the staging merged knowledge markdown path."""

    return build_knowledge_markdown_build_dir(subject) / "merged_knowledge_base.md"


def build_knowledge_manifest_path(subject: str) -> Path:
    """Return the knowledge docs manifest path."""

    return build_knowledge_markdown_dir(subject) / "manifest.json"


def build_knowledge_build_lock_path(subject: str) -> Path:
    """Return the subject-level knowledge docs lock path."""

    return build_knowledge_markdown_dir(subject) / ".build.lock"


def build_docgen_intermediate_dir(subject: str) -> Path:
    """Return the docgen intermediate directory."""

    return build_knowledge_markdown_build_dir(subject)


def build_docgen_intermediate_latest_dir(subject: str) -> Path:
    """Return the current build intermediate directory."""

    return build_docgen_intermediate_dir(subject)


def _sanitize_storage_token(value: str) -> str:
    cleaned = re.sub(r"[^\w\-]+", "_", value).strip("_")
    return cleaned or "file"


def build_asset_name_prefix(
    *,
    filename: str | None = None,
    file_uid: str | None = None,
    file_id: int | None = None,
) -> str:
    """Build a deterministic flattened-asset filename prefix for one raw file."""

    stem = Path(filename or "").stem or "file"
    safe_stem = _sanitize_storage_token(stem)[:24]
    identity = file_uid or (f"raw_{file_id}" if file_id is not None else safe_stem)
    safe_identity = _sanitize_storage_token(identity)[:48]
    return f"{safe_stem}__{safe_identity}__"


def list_asset_files(
    asset_dir: str | Path | None,
    *,
    asset_name_prefix: str | None = None,
) -> list[Path]:
    """List flattened asset files, optionally filtered to one raw file prefix."""

    if not asset_dir:
        return []

    path = Path(asset_dir)
    if not path.exists() or not path.is_dir():
        return []

    return [
        item
        for item in sorted(path.iterdir())
        if item.is_file() and (not asset_name_prefix or item.name.startswith(asset_name_prefix))
    ]


def delete_asset_files(
    asset_dir: str | Path | None,
    *,
    asset_name_prefix: str | None = None,
) -> int:
    """Delete flattened asset files, optionally filtered to one raw file prefix."""

    deleted = 0
    for item in list_asset_files(asset_dir, asset_name_prefix=asset_name_prefix):
        item.unlink(missing_ok=True)
        deleted += 1
    return deleted


def _sanitize_debug_segment(value: str) -> str:
    """Sanitize debug directory path segments."""

    return value.replace("/", "_").replace("\\", "_").replace(" ", "_")


def build_workflow_debug_dir(subject: str, workflow_name: str) -> Path:
    """Return the workflow debug root directory."""

    return build_debug_dir(subject) / _sanitize_debug_segment(workflow_name)


def build_workflow_run_debug_dir(subject: str, workflow_name: str, run_or_job_id: str | int) -> Path:
    """Return the debug directory for one workflow run."""

    return build_workflow_debug_dir(subject, workflow_name) / _sanitize_debug_segment(str(run_or_job_id))
