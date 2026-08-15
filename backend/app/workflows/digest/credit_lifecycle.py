"""Credit settlement boundary for DocGen without coupling API to ledger details."""

from __future__ import annotations

from collections.abc import Coroutine

from app.shared.infra.database import managed_session
from app.shared.infra.knowledge.build_store import read_knowledge_build_runtime
from app.shared.infra.storage import build_course_storage_scope
from app.workflows.digest.docgen.lib.build_lifecycle import _docgen_publish_completed_for_owner
from app.workflows.support.credits import release_reservation, settle_reservation


async def run_reserved_docgen(
    task: Coroutine,
    *,
    reservation_id: str | None,
    course_id: str,
    user_id: str,
    build_group_id: str,
) -> None:
    if reservation_id is None:
        await task
        return
    try:
        await task
    except BaseException:
        with managed_session() as session:
            release_reservation(session, reservation_id=reservation_id)
        raise
    course_scope = build_course_storage_scope(user_id=user_id, course_id=course_id)
    runtime = read_knowledge_build_runtime(course_id, course_scope=course_scope)
    docgen_runtime = runtime.docgen_runtime if runtime is not None else None
    build_session_id = (
        docgen_runtime.build_session_id
        if docgen_runtime is not None and docgen_runtime.build_group_id == build_group_id
        else None
    )
    published = _docgen_publish_completed_for_owner(
        course_id=course_id,
        build_group_id=build_group_id,
        build_session_id=build_session_id,
        course_scope=course_scope,
    )
    with managed_session() as session:
        if published:
            settle_reservation(session, reservation_id=reservation_id)
        else:
            release_reservation(session, reservation_id=reservation_id)


__all__ = ["run_reserved_docgen"]
