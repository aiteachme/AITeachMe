"""AI quota account, immutable ledger, and long-task reservations."""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlmodel import Field, SQLModel

from app.utils.time import utcnow


class CreditAccount(SQLModel, table=True):
    __tablename__ = "credit_account"
    __table_args__ = (
        sa.CheckConstraint("balance >= 0", name="ck_credit_account_balance_nonnegative"),
        sa.CheckConstraint("reserved_balance >= 0", name="ck_credit_account_reserved_nonnegative"),
        sa.CheckConstraint("reserved_balance <= balance", name="ck_credit_account_reserved_lte_balance"),
    )

    user_id: str = Field(primary_key=True, foreign_key="user.id")
    balance: int = 0
    reserved_balance: int = 0
    lifetime_granted: int = 0
    lifetime_spent: int = 0
    version: int = 0
    signup_grant_at: datetime | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class CreditLedger(SQLModel, table=True):
    __tablename__ = "credit_ledger"
    __table_args__ = (
        sa.UniqueConstraint("idempotency_key", name="uq_credit_ledger_idempotency"),
        sa.Index("ix_credit_ledger_user_created", "user_id", "created_at"),
        sa.CheckConstraint("delta != 0", name="ck_credit_ledger_nonzero_delta"),
    )

    id: str = Field(primary_key=True)
    user_id: str = Field(foreign_key="user.id", index=True)
    delta: int
    operation: str = Field(index=True)
    reason: str = Field(sa_column=sa.Column(sa.Text(), nullable=False))
    reference_type: str | None = Field(default=None, index=True)
    reference_id: str | None = Field(default=None, index=True)
    operator_user_id: str | None = Field(default=None, foreign_key="user.id", index=True)
    idempotency_key: str
    balance_before: int
    balance_after: int
    reserved_before: int
    reserved_after: int
    created_at: datetime = Field(default_factory=utcnow, index=True)


class CreditReservation(SQLModel, table=True):
    __tablename__ = "credit_reservation"
    __table_args__ = (
        sa.UniqueConstraint(
            "user_id", "feature", "reference_id",
            name="uq_credit_reservation_business_ref",
        ),
        sa.UniqueConstraint("idempotency_key", name="uq_credit_reservation_idempotency"),
        sa.Index("ix_credit_reservation_user_status", "user_id", "status"),
        sa.Index("ix_credit_reservation_recovery", "status", "expires_at"),
        sa.CheckConstraint("amount > 0", name="ck_credit_reservation_positive_amount"),
    )

    id: str = Field(primary_key=True)
    user_id: str = Field(foreign_key="user.id", index=True)
    feature: str = Field(index=True)
    reference_id: str
    idempotency_key: str
    amount: int
    status: str = Field(default="reserved", index=True)
    created_at: datetime = Field(default_factory=utcnow)
    expires_at: datetime = Field(index=True)
    settled_at: datetime | None = None
    released_at: datetime | None = None
