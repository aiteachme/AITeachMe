"""Credit settlement boundary for user-requested exam generation."""

from __future__ import annotations

from collections.abc import Coroutine

from app.repositories import exams_repo
from app.shared.infra.database import managed_session
from app.workflows.support.credits import release_reservation, settle_reservation


async def run_reserved_exam_generation(
    task: Coroutine,
    *,
    reservation_id: str | None,
    paper_id: int,
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
    with managed_session() as session:
        paper = exams_repo.get_exam_paper_by_id(session, paper_id)
        if paper is not None and paper.status in {"ready", "completed"}:
            settle_reservation(session, reservation_id=reservation_id)
        else:
            release_reservation(session, reservation_id=reservation_id)


__all__ = ["run_reserved_exam_generation"]
