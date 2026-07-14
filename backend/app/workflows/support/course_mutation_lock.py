"""Process-local serialization for course lifecycle mutations.

PostgreSQL row locks remain the cross-process authority. These striped locks
cover SQLite/local deployments where SELECT FOR UPDATE is ignored.
"""

from __future__ import annotations

from threading import RLock

_LOCKS = tuple(RLock() for _ in range(64))


def course_mutation_lock(course_id: str) -> RLock:
    return _LOCKS[hash(str(course_id)) % len(_LOCKS)]


__all__ = ["course_mutation_lock"]
