from __future__ import annotations

import asyncio
import base64
import hashlib
from contextlib import contextmanager
from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi import Request
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.models import AuthSession, CreditAccount, CreditLedger, CreditReservation, ExamPaper, User
from app.schemas.credits import AdminCreditAdjustmentRequest
from app.shared.infra.exceptions import AITeachMeError
from app.utils.time import utcnow
from app.workflows.support import credits
from app.workflows.support.auth import session_store, sessions
from app.workflows.digest import credit_lifecycle as docgen_credit_lifecycle


@pytest.fixture(autouse=True)
def _enable_credits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(credits, "resolve_credits_enabled", lambda: True)


def _engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(
        engine,
        tables=[
            User.__table__,
            AuthSession.__table__,
            CreditAccount.__table__,
            CreditLedger.__table__,
            CreditReservation.__table__,
            ExamPaper.__table__,
        ],
    )
    return engine


def _user(user_id: str = "usr_test", *, role: str = "user") -> User:
    return User(
        id=user_id,
        username=user_id,
        email=f"{user_id}@example.com",
        is_registered=True,
        role=role,
    )


def _request(
    method: str = "GET",
    *,
    csrf: str | None = None,
    origin: str = "http://localhost:5180",
) -> Request:
    headers = [(b"origin", origin.encode("ascii"))]
    if csrf:
        headers.append((b"x-csrf-token", csrf.encode("ascii")))
    return Request({"type": "http", "method": method, "path": "/", "headers": headers, "client": ("127.0.0.1", 1)})


def test_revocable_cookie_session_and_csrf(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session_store, "is_cloud_mode", lambda: False)
    engine = _engine()
    with Session(engine, expire_on_commit=False) as db:
        user = _user()
        db.add(user)
        db.commit()
        auth_session, token = session_store.create_auth_session(db, user=user, device_key="device-key", request=_request())
        assert session_store.resolve_auth_session(db, raw_token=token)[0].id == user.id

        with pytest.raises(AITeachMeError) as missing:
            session_store.validate_session_request(_request("POST"), auth_session=auth_session)
        assert missing.value.error_code == "AUTH_CSRF_INVALID"
        session_store.validate_session_request(_request("POST", csrf=auth_session.csrf_token), auth_session=auth_session)
        session_store.validate_session_request(
            _request("POST", csrf=auth_session.csrf_token, origin="aiteachme://android"),
            auth_session=auth_session,
        )

        session_store.revoke_auth_session(db, session_id=auth_session.id)
        assert session_store.resolve_auth_session(db, raw_token=token) is None


def test_expired_session_is_rejected() -> None:
    engine = _engine()
    with Session(engine, expire_on_commit=False) as db:
        user = _user()
        db.add(user)
        db.commit()
        auth_session, token = session_store.create_auth_session(db, user=user, device_key=None)
        auth_session.expires_at = utcnow() - timedelta(seconds=1)
        db.add(auth_session)
        db.commit()
        assert session_store.resolve_auth_session(db, raw_token=token) is None


def test_legacy_pbkdf2_password_is_upgraded_after_login(monkeypatch: pytest.MonkeyPatch) -> None:
    salt = b"0123456789abcdef"
    digest = hashlib.pbkdf2_hmac("sha256", b"strong-password", salt, 120_000)
    encoded = "pbkdf2_sha256$120000$%s$%s" % (
        base64.urlsafe_b64encode(salt).decode().rstrip("="),
        base64.urlsafe_b64encode(digest).decode().rstrip("="),
    )
    monkeypatch.setattr(sessions, "resolve_auth_enabled", lambda: True)
    engine = _engine()
    with Session(engine, expire_on_commit=False) as db:
        user = _user()
        user.password_hash = encoded
        db.add(user)
        db.commit()
        sessions.login_user(db, email=user.email, password="strong-password", device_key=None)
        assert db.get(User, user.id).password_hash.startswith("$argon2id$")


def test_credit_reservation_is_idempotent_and_cannot_overdraw(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(credits, "is_local_mode", lambda: False)
    engine = _engine()
    with Session(engine, expire_on_commit=False) as db:
        user = _user()
        db.add(user)
        db.commit()
        account = credits.ensure_credit_account(db, user=user)
        assert account.balance == 300
        first = credits.reserve_credits(
            db, user=user, feature="docgen_build", reference_id="build-1", amount=30, idempotency_key="docgen:build-1",
        )
        duplicate = credits.reserve_credits(
            db, user=user, feature="docgen_build", reference_id="build-1", amount=30, idempotency_key="docgen:build-1",
        )
        assert duplicate.id == first.id
        assert db.get(CreditAccount, user.id).reserved_balance == 30

        with pytest.raises(AITeachMeError) as insufficient:
            credits.reserve_credits(
                db, user=user, feature="docgen_build", reference_id="build-2", amount=271, idempotency_key="docgen:build-2",
            )
        assert insufficient.value.status_code == 402
        assert insufficient.value.error_code == "CREDIT_INSUFFICIENT"

        credits.settle_reservation(db, reservation_id=first.id)
        account = db.get(CreditAccount, user.id)
        assert (account.balance, account.reserved_balance) == (270, 0)
        assert len(db.exec(select(CreditLedger).where(CreditLedger.user_id == user.id)).all()) == 2


def test_disabled_credits_skip_grants_and_billing_but_keep_admin_adjustments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(credits, "is_local_mode", lambda: False)
    monkeypatch.setattr(credits, "resolve_credits_enabled", lambda: False)
    engine = _engine()
    with Session(engine, expire_on_commit=False) as db:
        target = _user("usr_target")
        admin = _user("usr_admin", role="admin")
        db.add_all([target, admin])
        db.commit()

        account = credits.ensure_credit_account(db, user=target)
        assert account.balance == 0
        assert credits.reserve_credits(
            db,
            user=target,
            feature="docgen_build",
            reference_id="build-disabled",
            amount=30,
            idempotency_key="docgen:build-disabled",
        ) is None

        adjusted = credits.adjust_credits(
            db,
            target_user=target,
            operator_user=admin,
            operation="set",
            amount=80,
            reason="管理员设置测试额度",
            idempotency_key="admin-disabled-set-80",
        )
        assert adjusted.balance == 80
        assert db.exec(select(CreditReservation)).all() == []


def test_credit_idempotency_key_cannot_cross_users(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(credits, "is_local_mode", lambda: False)
    engine = _engine()
    with Session(engine, expire_on_commit=False) as db:
        first_user = _user("usr_first")
        second_user = _user("usr_second")
        db.add_all([first_user, second_user])
        db.commit()
        credits.reserve_credits(
            db,
            user=first_user,
            feature="exam_generation",
            reference_id="paper-first",
            amount=5,
            idempotency_key="shared-idempotency-key",
        )
        with pytest.raises(AITeachMeError) as conflict:
            credits.reserve_credits(
                db,
                user=second_user,
                feature="exam_generation",
                reference_id="paper-second",
                amount=5,
                idempotency_key="shared-idempotency-key",
            )
        assert conflict.value.error_code == "CREDIT_IDEMPOTENCY_CONFLICT"


def test_admin_set_uses_delta_ledger_and_respects_reserved(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(credits, "is_local_mode", lambda: False)
    engine = _engine()
    with Session(engine, expire_on_commit=False) as db:
        target = _user("usr_target")
        admin = _user("usr_admin", role="admin")
        db.add_all([target, admin])
        db.commit()
        credits.ensure_credit_account(db, user=target)
        reservation = credits.reserve_credits(
            db, user=target, feature="exam_generation", reference_id="1", amount=5, idempotency_key="exam:1",
        )
        with pytest.raises(AITeachMeError):
            credits.adjust_credits(
                db, target_user=target, operator_user=admin, operation="set", amount=4,
                reason="管理员核对余额", idempotency_key="admin-set-too-low",
            )
        account = credits.adjust_credits(
            db, target_user=target, operator_user=admin, operation="set", amount=100,
            reason="管理员核对余额", idempotency_key="admin-set-100",
        )
        assert account.balance == 100
        ledger = db.exec(select(CreditLedger).where(CreditLedger.idempotency_key == "admin-set-100")).one()
        assert ledger.delta == -200
        with pytest.raises(AITeachMeError) as no_change:
            credits.adjust_credits(
                db, target_user=target, operator_user=admin, operation="set", amount=100,
                reason="管理员再次核对余额", idempotency_key="admin-set-100-again",
            )
        assert no_change.value.error_code == "CREDIT_ADJUSTMENT_NOOP"
        assert db.exec(
            select(CreditLedger).where(CreditLedger.idempotency_key == "admin-set-100-again")
        ).first() is None
        credits.release_reservation(db, reservation_id=reservation.id)


def test_admin_credit_adjustment_requires_a_chinese_reason() -> None:
    with pytest.raises(ValueError):
        AdminCreditAdjustmentRequest(
            operation="grant",
            amount=10,
            reason="manual correction",
            idempotency_key="admin-adjustment-1",
        )
    request = AdminCreditAdjustmentRequest(
        operation="grant",
        amount=10,
        reason="  管理员补发额度  ",
        idempotency_key="admin-adjustment-2",
    )
    assert request.reason == "管理员补发额度"


def test_successful_exam_reservation_is_settled_during_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(credits, "is_local_mode", lambda: False)
    engine = _engine()
    with Session(engine, expire_on_commit=False) as db:
        user = _user()
        db.add(user)
        db.commit()
        reservation = credits.reserve_credits(
            db,
            user=user,
            feature="exam_generation",
            reference_id="77",
            amount=5,
            idempotency_key="exam:77",
        )
        db.add(
            ExamPaper(
                id=77,
                course_id="course-1",
                user_id=user.id,
                exam_mode="paper_exam",
                status="ready",
            )
        )
        db.commit()

        assert credits._reservation_completed_successfully(db, reservation) is True
        credits.settle_reservation(db, reservation_id=reservation.id)
        assert db.get(CreditAccount, user.id).balance == 295


def test_active_exam_reservation_is_deferred_during_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(credits, "is_local_mode", lambda: False)
    engine = _engine()
    with Session(engine, expire_on_commit=False) as db:
        user = _user()
        db.add(user)
        db.commit()
        reservation = credits.reserve_credits(
            db,
            user=user,
            feature="exam_generation",
            reference_id="88",
            amount=5,
            idempotency_key="exam:88",
        )
        reservation.expires_at = utcnow() - timedelta(seconds=1)
        db.add_all(
            [
                reservation,
                ExamPaper(
                    id=88,
                    course_id="course-1",
                    user_id=user.id,
                    exam_mode="paper_exam",
                    status="generating",
                ),
            ]
        )
        db.commit()

        assert credits._reservation_recovery_action(db, reservation) == "defer"
        credits.defer_reservation_recovery(db, reservation_id=reservation.id)
        refreshed = db.get(CreditReservation, reservation.id)
        assert refreshed.status == "reserved"
        assert refreshed.expires_at > utcnow()


def test_stale_exam_reservation_is_released_during_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(credits, "is_local_mode", lambda: False)
    engine = _engine()
    with Session(engine, expire_on_commit=False) as db:
        user = _user()
        db.add(user)
        db.commit()
        reservation = credits.reserve_credits(
            db,
            user=user,
            feature="exam_generation",
            reference_id="89",
            amount=5,
            idempotency_key="exam:89",
        )
        reservation.expires_at = utcnow() - timedelta(seconds=1)
        db.add_all(
            [
                reservation,
                ExamPaper(
                    id=89,
                    course_id="course-1",
                    user_id=user.id,
                    exam_mode="paper_exam",
                    status="generating",
                    updated_at=utcnow() - timedelta(minutes=30),
                ),
            ]
        )
        db.commit()

        assert credits._reservation_recovery_action(db, reservation) == "release"
        credits.release_reservation(db, reservation_id=reservation.id)
        assert db.get(CreditAccount, user.id).reserved_balance == 0


def test_docgen_credit_lifecycle_uses_persisted_build_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settled: list[str] = []
    captured: dict[str, str | None] = {}

    @contextmanager
    def fake_session():
        yield object()

    async def completed_task() -> None:
        return None

    monkeypatch.setattr(docgen_credit_lifecycle, "managed_session", fake_session)
    monkeypatch.setattr(
        docgen_credit_lifecycle,
        "read_knowledge_build_runtime",
        lambda *_args, **_kwargs: SimpleNamespace(
            docgen_runtime=SimpleNamespace(
                build_group_id="build-group",
                build_session_id="build-session",
            )
        ),
    )

    def published(**kwargs) -> bool:
        captured["build_session_id"] = kwargs["build_session_id"]
        return True

    monkeypatch.setattr(docgen_credit_lifecycle, "_docgen_publish_completed_for_owner", published)
    monkeypatch.setattr(
        docgen_credit_lifecycle,
        "settle_reservation",
        lambda _session, *, reservation_id: settled.append(reservation_id),
    )

    asyncio.run(
        docgen_credit_lifecycle.run_reserved_docgen(
            completed_task(),
            reservation_id="reservation-1",
            course_id="course_123456789012",
            user_id="user-1",
            build_group_id="build-group",
        )
    )

    assert captured["build_session_id"] == "build-session"
    assert settled == ["reservation-1"]
