"""Subject support workflows."""

from app.workflows.support.subjects.commands import (
    create_subject_record,
    delete_subject_record,
    get_subject_detail,
    get_subject_record,
    list_subject_records,
    preview_subject_delete,
    update_subject_record,
)
from app.workflows.support.subjects.lib.deletion import (
    build_subject_delete_preview,
    collect_subject_delete_counts,
    delete_subject_artifacts_async,
    delete_subject_with_all_content,
)

__all__ = [
    "build_subject_delete_preview",
    "collect_subject_delete_counts",
    "create_subject_record",
    "delete_subject_artifacts_async",
    "delete_subject_record",
    "delete_subject_with_all_content",
    "get_subject_detail",
    "get_subject_record",
    "list_subject_records",
    "preview_subject_delete",
    "update_subject_record",
]
