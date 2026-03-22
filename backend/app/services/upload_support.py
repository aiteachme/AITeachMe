"""Filesystem path helpers for runtime data."""

from __future__ import annotations

from pathlib import Path

from app.core.config import get_settings


def get_data_dir() -> Path:
    """Return the runtime data root directory."""

    return Path(get_settings().data_dir)


def build_subject_dir(subject: str) -> Path:
    """Return the subject data directory."""

    return get_data_dir() / subject


def build_raw_dir(subject: str) -> Path:
    """Return the raw file directory."""

    return build_subject_dir(subject) / "raw"


def build_markdown_dir(subject: str) -> Path:
    """Return the parsed markdown directory."""

    return build_subject_dir(subject) / "markdown"


def build_assets_dir(subject: str) -> Path:
    """Return the extracted asset directory."""

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


def build_markdown_path(subject: str, raw_file_id: int) -> Path:
    """Build the parsed markdown path for a raw file."""

    return build_markdown_dir(subject) / f"{raw_file_id}.md"


def build_asset_dir(subject: str, raw_file_id: int) -> Path:
    """Build the asset directory for a raw file."""

    return build_assets_dir(subject) / str(raw_file_id)


def build_knowledge_docs_dir(subject: str) -> Path:
    """Return the published knowledge docs directory."""

    return build_subject_dir(subject) / "knowledge_docs"


def build_knowledge_docs_build_dir(subject: str) -> Path:
    """Return the staging knowledge docs directory."""

    return build_knowledge_docs_dir(subject) / "_building"


def _sanitize_doc_title(title: str) -> str:
    return title.replace("/", "_").replace("\\", "_").replace(" ", "_")[:50]


def build_knowledge_doc_path(subject: str, chapter_index: int, title: str) -> Path:
    """Build the published chapter markdown path."""

    filename = f"chapter_{chapter_index:02d}_{_sanitize_doc_title(title)}.md"
    return build_knowledge_docs_dir(subject) / filename


def build_knowledge_doc_build_path(subject: str, chapter_index: int, title: str) -> Path:
    """Build the staging chapter markdown path."""

    filename = f"chapter_{chapter_index:02d}_{_sanitize_doc_title(title)}.md"
    return build_knowledge_docs_build_dir(subject) / filename


def build_merged_knowledge_base_path(subject: str) -> Path:
    """Return the published merged knowledge markdown path."""

    return build_knowledge_docs_dir(subject) / "merged_knowledge_base.md"


def build_merged_knowledge_base_build_path(subject: str) -> Path:
    """Return the staging merged knowledge markdown path."""

    return build_knowledge_docs_build_dir(subject) / "merged_knowledge_base.md"


def build_knowledge_manifest_path(subject: str) -> Path:
    """Return the knowledge docs manifest path."""

    return build_knowledge_docs_dir(subject) / "manifest.json"


def build_knowledge_build_lock_path(subject: str) -> Path:
    """Return the subject-level knowledge docs lock path."""

    return build_knowledge_docs_dir(subject) / ".build.lock"


def build_docgen_intermediate_dir(subject: str) -> Path:
    """Return the docgen intermediate directory."""

    return build_subject_dir(subject) / "docgen_intermediate"


def build_docgen_intermediate_latest_dir(subject: str) -> Path:
    """Return the current build intermediate directory."""

    return build_docgen_intermediate_dir(subject) / "latest"


def _sanitize_debug_segment(value: str) -> str:
    """Sanitize debug directory path segments."""

    return value.replace("/", "_").replace("\\", "_").replace(" ", "_")


def build_workflow_debug_dir(subject: str, workflow_name: str) -> Path:
    """Return the workflow debug root directory."""

    return build_debug_dir(subject) / _sanitize_debug_segment(workflow_name)


def build_workflow_run_debug_dir(subject: str, workflow_name: str, run_or_job_id: str | int) -> Path:
    """Return the debug directory for one workflow run."""

    return build_workflow_debug_dir(subject, workflow_name) / _sanitize_debug_segment(str(run_or_job_id))
