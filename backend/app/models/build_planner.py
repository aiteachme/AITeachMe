"""Persistent confirmed build plan model."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlmodel import Column, Field, SQLModel

from app.utils.time import utcnow


class ConfirmedBuildPlan(SQLModel, table=True):
    """用户确认后冻结的构建合同，可被 DocGen 执行。"""

    __tablename__ = "confirmed_build_plan"

    id: str = Field(primary_key=True)
    subject: str = Field(index=True)
    planner_session_id: str | None = Field(default=None, index=True)
    user_id: str = Field(default="local", index=True)
    status: str = Field(default="confirmed", index=True)
    user_goal: str = Field(default="")
    digest_mode: str = Field(default="sprint", index=True)
    selected_file_ids_json: list[int] = Field(default_factory=list, sa_column=Column(sa.JSON))
    chapter_plan_json: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(sa.JSON))
    research_queries_json: list[str] = Field(default_factory=list, sa_column=Column(sa.JSON))
    media_plan_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(sa.JSON))
    build_constraints_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(sa.JSON))
    plan_summary: str = Field(default="")
    plan_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(sa.JSON))
    created_at: datetime = Field(default_factory=utcnow, index=True)
    updated_at: datetime = Field(default_factory=utcnow, index=True)
