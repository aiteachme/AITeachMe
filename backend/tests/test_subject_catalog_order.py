from __future__ import annotations

from datetime import datetime, timedelta

from sqlmodel import Session, SQLModel, create_engine, select

from app.models import Subject, User
from app.repositories.subject_repo import list_subjects
from app.workflows.support.export_import import exports


def test_subject_list_orders_by_created_at_desc() -> None:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine, tables=[User.__table__, Subject.__table__])

    base = datetime(2026, 4, 26, 12, 0)
    with Session(engine) as session:
        session.add(User(id="user_a", username="user_a"))
        session.add_all(
            [
                Subject(user_id="user_a", slug="older", name="Older", created_at=base),
                Subject(user_id="user_a", slug="newer", name="Newer", created_at=base + timedelta(minutes=2)),
                Subject(user_id="user_a", slug="middle", name="Middle", created_at=base + timedelta(minutes=1)),
            ]
        )
        session.commit()

        items, total = list_subjects(session, owner_user_id="user_a", limit=10, offset=0)

    assert total == 3
    assert [item.slug for item in items] == ["newer", "middle", "older"]


def test_imported_subject_uses_import_time_as_created_at(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine, tables=[User.__table__, Subject.__table__])

    exported_at = datetime(2024, 1, 1, 8, 0)
    imported_at = datetime(2026, 4, 26, 12, 30)
    monkeypatch.setattr(exports, "utcnow", lambda: imported_at)

    with Session(engine) as session:
        session.add(User(id="user_a", username="user_a"))
        count = exports._import_table(
            session,
            exports.TABLE_REGISTRY[0],
            [
                {
                    "id": 1,
                    "user_id": "author",
                    "slug": "exported",
                    "name": "Exported",
                    "created_at": exported_at,
                    "updated_at": exported_at,
                }
            ],
            id_map={},
            new_slug="imported",
            new_name="Imported",
            user_id="user_a",
            warnings=[],
        )
        session.commit()

        subject = session.exec(select(Subject).where(Subject.slug == "imported")).one()

    assert count == 1
    assert subject.created_at == imported_at
    assert subject.updated_at == imported_at
