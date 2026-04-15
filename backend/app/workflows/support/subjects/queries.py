"""Read-oriented subject support entrypoints."""

from app.workflows.support.subjects.commands import (
    get_subject_detail,
    get_subject_record,
    list_subject_records,
    preview_subject_delete,
)

__all__ = [
    "get_subject_detail",
    "get_subject_record",
    "list_subject_records",
    "preview_subject_delete",
]
