"""Course support workflows."""

from app.workflows.support.courses.catalog import (
    create_course_record,
    get_course_detail,
    get_course_record,
    list_course_records,
    update_course_record,
)
from app.workflows.support.courses.deletion import (
    build_course_delete_preview,
    collect_course_delete_counts,
    delete_course_artifacts_async,
    delete_course_record,
    delete_course_with_all_content,
    preview_course_delete,
)
from app.workflows.support.courses.icons import (
    choose_course_icon_key,
    infer_course_icon_key,
    schedule_course_icon_refinement,
)
from app.workflows.support.courses.learning_context import (
    build_course_learning_context_payload,
    clear_course_learning_context,
    load_course_llm_context,
    render_course_llm_context,
    update_course_learning_context_from_docgen,
)

__all__ = [
    "build_course_delete_preview",
    "build_course_learning_context_payload",
    "choose_course_icon_key",
    "clear_course_learning_context",
    "collect_course_delete_counts",
    "create_course_record",
    "delete_course_artifacts_async",
    "delete_course_record",
    "delete_course_with_all_content",
    "get_course_detail",
    "get_course_record",
    "infer_course_icon_key",
    "load_course_llm_context",
    "list_course_records",
    "preview_course_delete",
    "render_course_llm_context",
    "schedule_course_icon_refinement",
    "update_course_learning_context_from_docgen",
    "update_course_record",
]
