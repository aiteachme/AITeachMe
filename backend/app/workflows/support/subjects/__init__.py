"""Subject support workflows."""

from app.workflows.support.subjects.catalog import (
    create_subject_record,
    get_subject_detail,
    get_subject_record,
    list_subject_records,
    update_subject_record,
)
from app.workflows.support.subjects.deletion import (
    build_subject_delete_preview,
    collect_subject_delete_counts,
    delete_subject_artifacts_async,
    delete_subject_record,
    delete_subject_with_all_content,
    preview_subject_delete,
)
from app.workflows.support.subjects.icons import (
    choose_subject_icon_key,
    infer_subject_icon_key,
    schedule_subject_icon_refinement,
)
from app.workflows.support.subjects.learning_context import (
    build_subject_learning_context_payload,
    clear_subject_learning_context,
    load_subject_llm_context,
    render_subject_llm_context,
    update_subject_learning_context_from_docgen,
)

__all__ = [
    "build_subject_delete_preview",
    "build_subject_learning_context_payload",
    "choose_subject_icon_key",
    "clear_subject_learning_context",
    "collect_subject_delete_counts",
    "create_subject_record",
    "delete_subject_artifacts_async",
    "delete_subject_record",
    "delete_subject_with_all_content",
    "get_subject_detail",
    "get_subject_record",
    "infer_subject_icon_key",
    "load_subject_llm_context",
    "list_subject_records",
    "preview_subject_delete",
    "render_subject_llm_context",
    "schedule_subject_icon_refinement",
    "update_subject_learning_context_from_docgen",
    "update_subject_record",
]
