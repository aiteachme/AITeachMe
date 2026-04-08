"""Persistent models for the knowledge build planner."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlmodel import Column, Field, SQLModel

from app.utils.time import utcnow


class BuildPlannerSession(SQLModel, table=True):
    """One persistent planner conversation for a subject-level knowledge build."""

    __tablename__ = "build_planner_session"

    id: str = Field(primary_key=True)
    subject: str = Field(index=True)
    user_id: str = Field(default="local", index=True)
    title: str = Field(default="New Build Plan")
    status: str = Field(default="draft", index=True)
    user_goal: str = Field(default="")
    digest_mode: str = Field(default="sprint", index=True)
    tone: str = Field(default="casual")
    selected_file_ids_json: list[int] = Field(default_factory=list, sa_column=Column(sa.JSON))
    latest_plan_json: dict[str, Any] | None = Field(default=None, sa_column=Column(sa.JSON))
    latest_summary: str = Field(default="")
    confirmed_plan_id: str | None = Field(default=None, foreign_key="confirmed_build_plan.id", index=True)
    created_at: datetime = Field(default_factory=utcnow, index=True)
    updated_at: datetime = Field(default_factory=utcnow, index=True)


class BuildPlannerTurn(SQLModel, table=True):
    """One planner conversation turn."""

    __tablename__ = "build_planner_turn"

    id: int | None = Field(default=None, primary_key=True)
    subject: str = Field(index=True)
    user_id: str = Field(default="local", index=True)
    session_id: str = Field(foreign_key="build_planner_session.id", index=True)
    role: str = Field(index=True)
    content: str
    plan_json: dict[str, Any] | None = Field(default=None, sa_column=Column(sa.JSON))
    created_at: datetime = Field(default_factory=utcnow, index=True)


class ConfirmedBuildPlan(SQLModel, table=True):
    """A frozen planner output that can be executed by the build pipeline."""

    __tablename__ = "confirmed_build_plan"

    id: str = Field(primary_key=True)
    subject: str = Field(index=True)
    planner_session_id: str | None = Field(default=None, foreign_key="build_planner_session.id", index=True)
    user_id: str = Field(default="local", index=True)
    status: str = Field(default="confirmed", index=True)
    user_goal: str = Field(default="")
    digest_mode: str = Field(default="sprint", index=True)
    tone: str = Field(default="casual")
    selected_file_ids_json: list[int] = Field(default_factory=list, sa_column=Column(sa.JSON))
    chapter_plan_json: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(sa.JSON))
    research_queries_json: list[str] = Field(default_factory=list, sa_column=Column(sa.JSON))
    media_plan_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(sa.JSON))
    build_constraints_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(sa.JSON))
    plan_summary: str = Field(default="")
    plan_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(sa.JSON))
    created_at: datetime = Field(default_factory=utcnow, index=True)
    updated_at: datetime = Field(default_factory=utcnow, index=True)
