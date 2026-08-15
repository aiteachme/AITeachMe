from __future__ import annotations

from importlib import import_module
from types import SimpleNamespace


migration = import_module("migrations.versions.20260815_0029_auth_credits_memory")


def test_postgres_downgrade_removes_migration_owned_memory_tables(monkeypatch) -> None:
    dropped_tables: list[str] = []

    monkeypatch.setattr(
        migration.op,
        "get_bind",
        lambda: SimpleNamespace(dialect=SimpleNamespace(name="postgresql")),
    )
    monkeypatch.setattr(migration.op, "drop_table", dropped_tables.append)
    monkeypatch.setattr(migration.op, "f", lambda name: name)
    monkeypatch.setattr(migration.op, "drop_index", lambda *args, **kwargs: None)
    monkeypatch.setattr(migration.op, "drop_constraint", lambda *args, **kwargs: None)
    monkeypatch.setattr(migration.op, "drop_column", lambda *args, **kwargs: None)

    migration.downgrade()

    assert dropped_tables[:2] == ["learning_logs", "memory_entries"]
