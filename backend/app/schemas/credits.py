"""AI quota and administrator adjustment contracts."""

from __future__ import annotations

from datetime import datetime
import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class CreditSummaryData(BaseModel):
    balance: int
    reserved: int
    available: int
    lifetime_granted: int
    lifetime_spent: int


class CreditLedgerItem(BaseModel):
    id: str
    delta: int
    operation: str
    reason: str
    reference_type: str | None = None
    reference_id: str | None = None
    operator_user_id: str | None = None
    balance_after: int
    created_at: datetime


class CreditLedgerPage(BaseModel):
    items: list[CreditLedgerItem] = Field(default_factory=list)
    page: int
    size: int
    total: int


class AdminUserItem(BaseModel):
    user_id: str
    email: str | None = None
    display_name: str | None = None
    role: Literal["user", "admin"]
    balance: int
    reserved: int
    created_at: datetime


class AdminUserPage(BaseModel):
    items: list[AdminUserItem] = Field(default_factory=list)
    page: int
    size: int
    total: int


class AdminCreditAdjustmentRequest(BaseModel):
    operation: Literal["grant", "deduct", "set"]
    amount: int = Field(ge=0)
    reason: str = Field(min_length=2, max_length=300)
    idempotency_key: str = Field(min_length=8, max_length=160)

    @field_validator("reason")
    @classmethod
    def validate_chinese_reason(cls, value: str) -> str:
        normalized = value.strip()
        if not re.search(r"[\u3400-\u9fff]", normalized):
            raise ValueError("额度调整原因必须包含中文说明。")
        return normalized
