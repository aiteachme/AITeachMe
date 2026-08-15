"""Transactional AI quota accounting."""

from __future__ import annotations

from datetime import timedelta
from typing import Literal
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.models import Course, CreditAccount, CreditLedger, CreditReservation, ExamPaper, User
from app.schemas.credits import CreditSummaryData
from app.shared.infra.exceptions import AITeachMeError
from app.shared.infra.runtime import is_local_mode, resolve_credits_enabled
from app.utils.time import ensure_utc_datetime, utcnow

SIGNUP_GRANT = 300
DOCGEN_BUILD_COST = 30
EXAM_GENERATION_COST = 5
EXAM_GENERATION_STALE_AFTER = timedelta(minutes=20)


def ensure_credits_enabled() -> None:
    if not resolve_credits_enabled():
        raise AITeachMeError(
            detail="AI 额度功能暂未开放。",
            status_code=404,
            error_code="CREDITS_DISABLED",
        )


def _ledger_id() -> str:
    return f"clg_{uuid4().hex}"


def _reservation_id() -> str:
    return f"crs_{uuid4().hex}"


def _locked_account(session: Session, user_id: str) -> CreditAccount | None:
    return session.exec(
        select(CreditAccount).where(CreditAccount.user_id == user_id).with_for_update()
    ).first()


def ensure_credit_account(
    session: Session,
    *,
    user: User,
    grant_signup_credit: bool = True,
) -> CreditAccount:
    account = _locked_account(session, user.id)
    if account is None:
        account = CreditAccount(user_id=user.id)
        session.add(account)
        try:
            session.flush()
        except IntegrityError:
            session.rollback()
            account = _locked_account(session, user.id)
            if account is None:
                raise

    if (
        grant_signup_credit
        and resolve_credits_enabled()
        and user.is_registered
        and account.signup_grant_at is None
    ):
        now = utcnow()
        before = account.balance
        account.balance += SIGNUP_GRANT
        account.lifetime_granted += SIGNUP_GRANT
        account.signup_grant_at = now
        account.version += 1
        account.updated_at = now
        session.add(account)
        session.add(
            CreditLedger(
                id=_ledger_id(),
                user_id=user.id,
                delta=SIGNUP_GRANT,
                operation="signup_grant",
                reason="注册账号初始 AI 额度",
                reference_type="user",
                reference_id=user.id,
                idempotency_key=f"signup-grant:{user.id}",
                balance_before=before,
                balance_after=account.balance,
                reserved_before=account.reserved_balance,
                reserved_after=account.reserved_balance,
                created_at=now,
            )
        )
    session.commit()
    session.refresh(account)
    return account


def credit_summary(account: CreditAccount) -> CreditSummaryData:
    return CreditSummaryData(
        balance=account.balance,
        reserved=account.reserved_balance,
        available=account.balance - account.reserved_balance,
        lifetime_granted=account.lifetime_granted,
        lifetime_spent=account.lifetime_spent,
    )


def _validate_existing_reservation(
    existing: CreditReservation,
    *,
    user_id: str,
    feature: str,
    reference_id: str,
    amount: int,
) -> CreditReservation:
    if (
        existing.user_id != user_id
        or existing.feature != feature
        or existing.reference_id != reference_id
        or existing.amount != amount
    ):
        raise AITeachMeError(
            detail="额度预占幂等键已用于其他业务请求。",
            status_code=409,
            error_code="CREDIT_IDEMPOTENCY_CONFLICT",
        )
    return existing


def reserve_credits(
    session: Session,
    *,
    user: User,
    feature: str,
    reference_id: str,
    amount: int,
    idempotency_key: str,
) -> CreditReservation | None:
    if is_local_mode() or not resolve_credits_enabled():
        return None
    if not user.is_registered:
        raise AITeachMeError(
            detail="云端 AI 重任务需要先登录。",
            status_code=401,
            error_code="AUTH_REQUIRED_FOR_CREDIT_TASK",
        )
    existing = session.exec(
        select(CreditReservation).where(
            sa.or_(
                CreditReservation.idempotency_key == idempotency_key,
                sa.and_(
                    CreditReservation.user_id == user.id,
                    CreditReservation.feature == feature,
                    CreditReservation.reference_id == reference_id,
                ),
            )
        )
    ).first()
    if existing is not None:
        return _validate_existing_reservation(
            existing,
            user_id=user.id,
            feature=feature,
            reference_id=reference_id,
            amount=amount,
        )

    ensure_credit_account(session, user=user)
    result = session.exec(
        sa.update(CreditAccount)
        .where(
            CreditAccount.user_id == user.id,
            CreditAccount.balance - CreditAccount.reserved_balance >= amount,
        )
        .values(
            reserved_balance=CreditAccount.reserved_balance + amount,
            version=CreditAccount.version + 1,
            updated_at=utcnow(),
        )
    )
    if result.rowcount != 1:
        session.rollback()
        account = session.get(CreditAccount, user.id)
        available = 0 if account is None else account.balance - account.reserved_balance
        raise AITeachMeError(
            detail="AI 额度不足。",
            status_code=402,
            error_code="CREDIT_INSUFFICIENT",
            data={"required": amount, "available": available},
        )
    now = utcnow()
    reservation = CreditReservation(
        id=_reservation_id(),
        user_id=user.id,
        feature=feature,
        reference_id=reference_id,
        idempotency_key=idempotency_key,
        amount=amount,
        status="reserved",
        created_at=now,
        expires_at=now + timedelta(hours=24),
    )
    session.add(reservation)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = session.exec(
            select(CreditReservation).where(
                sa.or_(
                    CreditReservation.idempotency_key == idempotency_key,
                    sa.and_(
                        CreditReservation.user_id == user.id,
                        CreditReservation.feature == feature,
                        CreditReservation.reference_id == reference_id,
                    ),
                )
            )
        ).first()
        if existing is None:
            raise
        return _validate_existing_reservation(
            existing,
            user_id=user.id,
            feature=feature,
            reference_id=reference_id,
            amount=amount,
        )
    session.refresh(reservation)
    return reservation


def settle_reservation(session: Session, *, reservation_id: str) -> CreditReservation | None:
    reservation = session.exec(
        select(CreditReservation)
        .where(CreditReservation.id == reservation_id)
        .with_for_update()
    ).first()
    if reservation is None or reservation.status != "reserved":
        return reservation
    account = _locked_account(session, reservation.user_id)
    if account is None:
        raise RuntimeError("Credit account missing while settling reservation.")
    now = utcnow()
    before = account.balance
    reserved_before = account.reserved_balance
    account.balance -= reservation.amount
    account.reserved_balance -= reservation.amount
    account.lifetime_spent += reservation.amount
    account.version += 1
    account.updated_at = now
    reservation.status = "settled"
    reservation.settled_at = now
    session.add(account)
    session.add(reservation)
    session.add(
        CreditLedger(
            id=_ledger_id(),
            user_id=reservation.user_id,
            delta=-reservation.amount,
            operation="consume",
            reason="AI 重任务成功结算",
            reference_type=reservation.feature,
            reference_id=reservation.reference_id,
            idempotency_key=f"settle:{reservation.id}",
            balance_before=before,
            balance_after=account.balance,
            reserved_before=reserved_before,
            reserved_after=account.reserved_balance,
            created_at=now,
        )
    )
    session.commit()
    return reservation


def release_reservation(session: Session, *, reservation_id: str) -> CreditReservation | None:
    reservation = session.exec(
        select(CreditReservation)
        .where(CreditReservation.id == reservation_id)
        .with_for_update()
    ).first()
    if reservation is None or reservation.status != "reserved":
        return reservation
    account = _locked_account(session, reservation.user_id)
    if account is None:
        raise RuntimeError("Credit account missing while releasing reservation.")
    account.reserved_balance -= reservation.amount
    account.version += 1
    account.updated_at = utcnow()
    reservation.status = "released"
    reservation.released_at = utcnow()
    session.add(account)
    session.add(reservation)
    session.commit()
    return reservation


def defer_reservation_recovery(
    session: Session,
    *,
    reservation_id: str,
) -> CreditReservation | None:
    reservation = session.exec(
        select(CreditReservation)
        .where(CreditReservation.id == reservation_id)
        .with_for_update()
    ).first()
    if reservation is None or reservation.status != "reserved":
        return reservation
    reservation.expires_at = utcnow() + timedelta(hours=1)
    session.add(reservation)
    session.commit()
    return reservation


def _reservation_recovery_action(
    session: Session,
    reservation: CreditReservation,
) -> Literal["settle", "release", "defer"]:
    """Classify an expired reservation without releasing active work."""

    if reservation.feature == "exam_generation":
        try:
            paper_id = int(reservation.reference_id)
        except (TypeError, ValueError):
            return "release"
        paper = session.get(ExamPaper, paper_id)
        if paper is None:
            return "release"
        if paper.status in {
            "ready", "in_progress", "submitted", "grading", "grading_failed",
            "graded", "archived", "completed",
        }:
            return "settle"
        if paper.status in {"failed", "draft", "cancelled"}:
            return "release"
        if paper.status == "generating":
            updated_at = ensure_utc_datetime(paper.updated_at)
            if updated_at is not None and updated_at <= utcnow() - EXAM_GENERATION_STALE_AFTER:
                return "release"
        return "defer"

    if reservation.feature == "docgen_build":
        from app.shared.infra.knowledge.build_store import (
            is_knowledge_build_lock_owner,
            read_knowledge_build_runtime,
        )
        from app.shared.infra.storage import build_course_storage_scope
        from app.workflows.digest.docgen.lib.build_lifecycle import _docgen_publish_completed_for_owner

        courses = session.exec(select(Course).where(Course.user_id == reservation.user_id)).all()
        matched_status: str | None = None
        for course in courses:
            course_scope = build_course_storage_scope(user_id=reservation.user_id, course_id=course.id)
            runtime = read_knowledge_build_runtime(course.id, course_scope=course_scope)
            docgen_runtime = runtime.docgen_runtime if runtime is not None else None
            runtime_matches = bool(
                docgen_runtime is not None
                and docgen_runtime.build_group_id == reservation.reference_id
            )
            build_session_id = docgen_runtime.build_session_id if runtime_matches else None
            if _docgen_publish_completed_for_owner(
                course_id=course.id,
                build_group_id=reservation.reference_id,
                build_session_id=build_session_id,
                course_scope=course_scope,
            ):
                return "settle"
            if runtime_matches:
                matched_status = str(docgen_runtime.status or "").strip().lower()
                if matched_status in {"accepted", "running", "publishing"}:
                    if is_knowledge_build_lock_owner(
                        course.id,
                        build_group_id=reservation.reference_id,
                        session=session,
                        course_scope=course_scope,
                    ):
                        return "defer"
                    return "release"

        if matched_status in {"failed", "cancelled", "partial_failed", "skipped", "completed"}:
            return "release"
        return "defer" if matched_status else "release"

    return "release"


def _reservation_completed_successfully(
    session: Session,
    reservation: CreditReservation,
) -> bool:
    return _reservation_recovery_action(session, reservation) == "settle"


def recover_expired_reservations_once() -> int:
    from app.shared.infra.database import managed_session

    with managed_session() as session:
        reservation_ids = list(
            session.exec(
                select(CreditReservation.id).where(
                    CreditReservation.status == "reserved",
                    CreditReservation.expires_at <= utcnow(),
                )
            ).all()
        )
    recovered = 0
    for reservation_id in reservation_ids:
        with managed_session() as session:
            reservation = session.get(CreditReservation, reservation_id)
            if reservation is None or reservation.status != "reserved":
                continue
            action = _reservation_recovery_action(session, reservation)
            if action == "settle":
                settle_reservation(session, reservation_id=reservation_id)
            elif action == "release":
                release_reservation(session, reservation_id=reservation_id)
            else:
                defer_reservation_recovery(session, reservation_id=reservation_id)
            if action != "defer":
                recovered += 1
    return recovered


async def run_credit_reservation_recovery_loop() -> None:
    import asyncio
    import structlog

    logger = structlog.get_logger(__name__)
    while True:
        try:
            recover_expired_reservations_once()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("credit_reservation_recovery_failed", error=str(exc))
        await asyncio.sleep(60)


def adjust_credits(
    session: Session,
    *,
    target_user: User,
    operator_user: User,
    operation: str,
    amount: int,
    reason: str,
    idempotency_key: str,
) -> CreditAccount:
    def resolve_existing(existing: CreditLedger) -> CreditAccount:
        normalized_reason = reason.strip()
        expected_operation = f"admin_{operation}"
        amount_matches = (
            existing.balance_after == amount
            if operation == "set"
            else existing.delta == (amount if operation == "grant" else -amount)
        )
        if (
            existing.user_id != target_user.id
            or existing.operator_user_id != operator_user.id
            or existing.operation != expected_operation
            or existing.reason != normalized_reason
            or not amount_matches
        ):
            raise AITeachMeError(
                detail="管理员额度调整幂等键已用于其他操作。",
                status_code=409,
                error_code="CREDIT_IDEMPOTENCY_CONFLICT",
            )
        account = session.get(CreditAccount, target_user.id)
        if account is None:
            raise RuntimeError("Credit ledger exists without account.")
        return account

    existing = session.exec(
        select(CreditLedger).where(CreditLedger.idempotency_key == idempotency_key)
    ).first()
    if existing is not None:
        return resolve_existing(existing)
    ensure_credit_account(session, user=target_user)
    account = _locked_account(session, target_user.id)
    if account is None:
        raise RuntimeError("Credit account disappeared before adjustment.")
    if operation == "grant":
        delta = amount
    elif operation == "deduct":
        delta = -amount
    elif operation == "set":
        delta = amount - account.balance
    else:
        raise AITeachMeError(detail="不支持的额度操作。", status_code=400, error_code="CREDIT_OPERATION_INVALID")
    after = account.balance + delta
    if after < account.reserved_balance or after < 0:
        raise AITeachMeError(
            detail="调整后的余额不能低于已冻结额度或零。",
            status_code=409,
            error_code="CREDIT_ADJUSTMENT_CONFLICT",
            data={"reserved": account.reserved_balance, "requested_balance": after},
        )
    if delta == 0:
        raise AITeachMeError(
            detail="调整后的额度与当前余额相同，无需重复操作。",
            status_code=409,
            error_code="CREDIT_ADJUSTMENT_NOOP",
        )
    now = utcnow()
    before = account.balance
    account.balance = after
    account.lifetime_granted += max(delta, 0)
    account.lifetime_spent += max(-delta, 0)
    account.version += 1
    account.updated_at = now
    session.add(account)
    session.add(
        CreditLedger(
            id=_ledger_id(),
            user_id=target_user.id,
            delta=delta,
            operation=f"admin_{operation}",
            reason=reason.strip(),
            reference_type="admin_adjustment",
            reference_id=target_user.id,
            operator_user_id=operator_user.id,
            idempotency_key=idempotency_key,
            balance_before=before,
            balance_after=after,
            reserved_before=account.reserved_balance,
            reserved_after=account.reserved_balance,
            created_at=now,
        )
    )
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = session.exec(
            select(CreditLedger).where(CreditLedger.idempotency_key == idempotency_key)
        ).first()
        if existing is None:
            raise
        return resolve_existing(existing)
    session.refresh(account)
    return account
