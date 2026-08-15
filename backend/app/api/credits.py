"""User AI quota and administrator adjustment APIs."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy import func, or_
from sqlmodel import Session, select

from app.api.deps import get_db, require_admin_user, require_authenticated_user
from app.api.openapi import build_error_responses
from app.models import CreditLedger, User
from app.schemas.common import ApiResponse, ok_response
from app.schemas.credits import (
    AdminCreditAdjustmentRequest,
    AdminUserItem,
    AdminUserPage,
    CreditLedgerItem,
    CreditLedgerPage,
    CreditSummaryData,
)
from app.shared.infra.exceptions import AITeachMeError
from app.workflows.support.credits import (
    adjust_credits,
    credit_summary,
    ensure_credit_account,
    ensure_credits_enabled,
)

router = APIRouter(prefix="/api/v1/credits", tags=["credits"])
admin_router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


@router.get(
    "/summary",
    response_model=ApiResponse[CreditSummaryData],
    responses=build_error_responses([401, 403, 404, 500]),
)
def get_credit_summary(
    user: User = Depends(require_authenticated_user),
    session: Session = Depends(get_db),
) -> ApiResponse[CreditSummaryData]:
    ensure_credits_enabled()
    return ok_response(credit_summary(ensure_credit_account(session, user=user)))


@router.get(
    "/ledger",
    response_model=ApiResponse[CreditLedgerPage],
    responses=build_error_responses([401, 403, 404, 422, 500]),
)
def list_credit_ledger(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    user: User = Depends(require_authenticated_user),
    session: Session = Depends(get_db),
) -> ApiResponse[CreditLedgerPage]:
    ensure_credits_enabled()
    ensure_credit_account(session, user=user)
    total = int(session.exec(
        select(func.count()).select_from(CreditLedger).where(CreditLedger.user_id == user.id)
    ).one())
    rows = session.exec(
        select(CreditLedger)
        .where(CreditLedger.user_id == user.id)
        .order_by(CreditLedger.created_at.desc(), CreditLedger.id.desc())
        .offset((page - 1) * size)
        .limit(size)
    ).all()
    return ok_response(
        CreditLedgerPage(
            items=[CreditLedgerItem.model_validate(row, from_attributes=True) for row in rows],
            page=page,
            size=size,
            total=total,
        )
    )


@admin_router.get(
    "/users",
    response_model=ApiResponse[AdminUserPage],
    responses=build_error_responses([401, 403, 422, 500]),
)
def search_users(
    q: str = Query(default="", max_length=120),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    _: User = Depends(require_admin_user),
    session: Session = Depends(get_db),
) -> ApiResponse[AdminUserPage]:
    condition = User.is_registered.is_(True)
    normalized = q.strip()
    if normalized:
        pattern = f"%{normalized}%"
        condition = condition & or_(
            User.id.ilike(pattern),
            User.email.ilike(pattern),
            User.display_name.ilike(pattern),
        )
    total = int(session.exec(select(func.count()).select_from(User).where(condition)).one())
    users = session.exec(
        select(User).where(condition).order_by(User.created_at.desc()).offset((page - 1) * size).limit(size)
    ).all()
    items: list[AdminUserItem] = []
    for user in users:
        account = ensure_credit_account(session, user=user)
        items.append(
            AdminUserItem(
                user_id=user.id,
                email=user.email,
                display_name=user.display_name,
                role="admin" if user.role == "admin" else "user",
                balance=account.balance,
                reserved=account.reserved_balance,
                created_at=user.created_at,
            )
        )
    return ok_response(AdminUserPage(items=items, page=page, size=size, total=total))


@admin_router.get(
    "/users/{user_id}/credits",
    response_model=ApiResponse[CreditSummaryData],
    responses=build_error_responses([401, 403, 404, 500]),
)
def get_user_credit_detail(
    user_id: str,
    _: User = Depends(require_admin_user),
    session: Session = Depends(get_db),
) -> ApiResponse[CreditSummaryData]:
    target = session.get(User, user_id)
    if target is None or not target.is_registered:
        raise AITeachMeError(detail="用户不存在。", status_code=404, error_code="USER_NOT_FOUND")
    return ok_response(credit_summary(ensure_credit_account(session, user=target)))


@admin_router.post(
    "/users/{user_id}/credits/adjust",
    response_model=ApiResponse[CreditSummaryData],
    responses=build_error_responses([400, 401, 403, 404, 409, 422, 500]),
)
def adjust_user_credits(
    user_id: str,
    body: AdminCreditAdjustmentRequest = Body(...),
    admin: User = Depends(require_admin_user),
    session: Session = Depends(get_db),
) -> ApiResponse[CreditSummaryData]:
    target = session.get(User, user_id)
    if target is None or not target.is_registered:
        raise AITeachMeError(detail="用户不存在。", status_code=404, error_code="USER_NOT_FOUND")
    if body.operation in {"grant", "deduct"} and body.amount <= 0:
        raise AITeachMeError(detail="赠送或扣减额度必须大于零。", status_code=400, error_code="CREDIT_AMOUNT_INVALID")
    account = adjust_credits(
        session,
        target_user=target,
        operator_user=admin,
        operation=body.operation,
        amount=body.amount,
        reason=body.reason,
        idempotency_key=body.idempotency_key,
    )
    return ok_response(credit_summary(account))
