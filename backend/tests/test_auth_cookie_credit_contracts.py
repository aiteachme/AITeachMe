from __future__ import annotations

import asyncio
import base64
import hashlib
from contextlib import contextmanager
from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi import Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.models import (
    AuthRateLimitBucket,
    AuthSession,
    Course,
    CreditAccount,
    CreditLedger,
    CreditReservation,
    ExamPaper,
    OAuthFlow,
    User,
)
from app.schemas.credits import AdminCreditAdjustmentRequest
from app.shared.infra.exceptions import AITeachMeError
from app.utils.time import utcnow
from app.workflows.support import credits
from app.workflows.support.auth import housekeeping, session_store, sessions
from app.workflows.digest import credit_lifecycle as docgen_credit_lifecycle
from app.shared.infra.knowledge import build_store
from app.workflows.digest.docgen.lib import build_lifecycle as docgen_build_lifecycle


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
            OAuthFlow.__table__,
            AuthRateLimitBucket.__table__,
            Course.__table__,
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


def test_session_last_seen_is_throttled(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = _engine()
    with Session(engine, expire_on_commit=False) as db:
        user = _user()
        db.add(user)
        db.commit()
        auth_session, token = session_store.create_auth_session(db, user=user, device_key=None)
        baseline = utcnow() - timedelta(minutes=1)
        auth_session.last_seen_at = baseline
        db.add(auth_session)
        db.commit()

        monkeypatch.setattr(session_store, "utcnow", lambda: baseline + timedelta(minutes=4))
        session_store.resolve_auth_session(db, raw_token=token)
        assert auth_session.last_seen_at == baseline

        touched_at = baseline + timedelta(minutes=6)
        monkeypatch.setattr(session_store, "utcnow", lambda: touched_at)
        session_store.resolve_auth_session(db, raw_token=token)
        assert auth_session.last_seen_at == touched_at


def test_auth_housekeeping_deletes_only_expired_or_retention_eligible_records() -> None:
    engine = _engine()
    now = utcnow()
    with Session(engine, expire_on_commit=False) as db:
        user = _user()
        db.add(user)
        db.add_all(
            [
                AuthRateLimitBucket(
                    id="rate-expired",
                    bucket_key="login:expired",
                    window_started_at=now - timedelta(minutes=2),
                    expires_at=now - timedelta(seconds=1),
                ),
                AuthRateLimitBucket(
                    id="rate-active",
                    bucket_key="login:active",
                    window_started_at=now,
                    expires_at=now + timedelta(minutes=1),
                ),
                OAuthFlow(
                    id="oauth-expired",
                    state_hash="state-expired",
                    provider="google",
                    provider_app_id="google-app",
                    expires_at=now - timedelta(seconds=1),
                ),
                OAuthFlow(
                    id="oauth-active",
                    state_hash="state-active",
                    provider="google",
                    provider_app_id="google-app",
                    expires_at=now + timedelta(minutes=10),
                ),
                OAuthFlow(
                    id="oauth-consumed-old",
                    state_hash="state-consumed-old",
                    provider="google",
                    provider_app_id="google-app",
                    expires_at=now + timedelta(days=1),
                    consumed_at=now - timedelta(days=2),
                ),
                OAuthFlow(
                    id="oauth-consumed-recently",
                    state_hash="state-consumed-recently",
                    provider="google",
                    provider_app_id="google-app",
                    expires_at=now + timedelta(days=1),
                    consumed_at=now - timedelta(hours=1),
                ),
                AuthSession(
                    id="session-expired",
                    user_id=user.id,
                    token_hash="token-expired",
                    csrf_token="csrf-expired",
                    expires_at=now - timedelta(seconds=1),
                ),
                AuthSession(
                    id="session-recently-revoked",
                    user_id=user.id,
                    token_hash="token-recently-revoked",
                    csrf_token="csrf-recently-revoked",
                    expires_at=now + timedelta(days=1),
                    revoked_at=now - timedelta(days=1),
                ),
                AuthSession(
                    id="session-revoked-old",
                    user_id=user.id,
                    token_hash="token-revoked-old",
                    csrf_token="csrf-revoked-old",
                    expires_at=now + timedelta(days=1),
                    revoked_at=now - timedelta(days=8),
                ),
            ]
        )
        db.commit()

        assert housekeeping._cleanup_expired_auth_records(db, limit=20) == 5
        assert db.get(AuthRateLimitBucket, "rate-expired") is None
        assert db.get(OAuthFlow, "oauth-expired") is None
        assert db.get(OAuthFlow, "oauth-consumed-old") is None
        assert db.get(AuthSession, "session-expired") is None
        assert db.get(AuthSession, "session-revoked-old") is None
        assert db.get(AuthRateLimitBucket, "rate-active") is not None
        assert db.get(OAuthFlow, "oauth-active") is not None
        assert db.get(OAuthFlow, "oauth-consumed-recently") is not None
        assert db.get(AuthSession, "session-recently-revoked") is not None


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


def test_admin_adjustment_recovers_concurrent_same_idempotency_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _engine()
    with Session(engine, expire_on_commit=False) as db:
        target = _user("usr_target")
        admin = _user("usr_admin", role="admin")
        db.add_all([target, admin])
        db.commit()
        credits.ensure_credit_account(db, user=target)

        monkeypatch.setattr(
            credits,
            "ensure_credit_account",
            lambda session, *, user: session.get(CreditAccount, user.id),
        )
        collision_injected = False

        def commit_after_concurrent_winner() -> None:
            nonlocal collision_injected
            assert not collision_injected
            collision_injected = True
            db.rollback()
            with Session(engine, expire_on_commit=False) as winner:
                account = winner.get(CreditAccount, target.id)
                assert account is not None
                now = utcnow()
                before = account.balance
                account.balance += 25
                account.lifetime_granted += 25
                account.version += 1
                account.updated_at = now
                winner.add(account)
                winner.add(
                    CreditLedger(
                        id="clg_concurrent_winner",
                        user_id=target.id,
                        delta=25,
                        operation="admin_grant",
                        reason="管理员并发补发额度",
                        reference_type="admin_adjustment",
                        reference_id=target.id,
                        operator_user_id=admin.id,
                        idempotency_key="admin-concurrent-grant",
                        balance_before=before,
                        balance_after=account.balance,
                        reserved_before=account.reserved_balance,
                        reserved_after=account.reserved_balance,
                        created_at=now,
                    )
                )
                winner.commit()
            raise IntegrityError("INSERT credit_ledger", {}, Exception("duplicate idempotency key"))

        monkeypatch.setattr(db, "commit", commit_after_concurrent_winner)
        account = credits.adjust_credits(
            db,
            target_user=target,
            operator_user=admin,
            operation="grant",
            amount=25,
            reason="管理员并发补发额度",
            idempotency_key="admin-concurrent-grant",
        )

        assert account.balance == 325
        assert collision_injected is True
        assert len(db.exec(
            select(CreditLedger).where(CreditLedger.idempotency_key == "admin-concurrent-grant")
        ).all()) == 1


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


@pytest.mark.parametrize(("owns_lock", "expected_action"), [(True, "defer"), (False, "release")])
def test_docgen_reservation_recovery_requires_an_active_build_lease(
    monkeypatch: pytest.MonkeyPatch,
    owns_lock: bool,
    expected_action: str,
) -> None:
    monkeypatch.setattr(credits, "is_local_mode", lambda: False)
    monkeypatch.setattr(
        build_store,
        "read_knowledge_build_runtime",
        lambda *_args, **_kwargs: SimpleNamespace(
            docgen_runtime=SimpleNamespace(
                build_group_id="build-group",
                build_session_id="build-session",
                status="running",
            )
        ),
    )
    monkeypatch.setattr(
        build_store,
        "is_knowledge_build_lock_owner",
        lambda *_args, **_kwargs: owns_lock,
    )
    monkeypatch.setattr(
        docgen_build_lifecycle,
        "_docgen_publish_completed_for_owner",
        lambda **_kwargs: False,
    )
    engine = _engine()
    with Session(engine, expire_on_commit=False) as db:
        user = _user()
        db.add_all(
            [
                user,
                Course(id="course_docgen000001", user_id=user.id, name="DocGen Recovery"),
            ]
        )
        db.commit()
        reservation = credits.reserve_credits(
            db,
            user=user,
            feature="docgen_build",
            reference_id="build-group",
            amount=30,
            idempotency_key=f"docgen-recovery:{owns_lock}",
        )

        assert credits._reservation_recovery_action(db, reservation) == expected_action


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
