"""Revocable authentication, OAuth identity, and guest-merge models."""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlmodel import Field, SQLModel

from app.utils.time import utcnow


class AuthIdentity(SQLModel, table=True):
    """External login identity linked to one registered user."""

    __tablename__ = "auth_identity"
    __table_args__ = (
        sa.UniqueConstraint(
            "provider", "provider_app_id", "provider_subject",
            name="uq_auth_identity_provider_subject",
        ),
        sa.UniqueConstraint(
            "user_id", "provider", "provider_app_id",
            name="uq_auth_identity_user_provider",
        ),
        sa.Index("ix_auth_identity_user_provider", "user_id", "provider"),
    )

    id: str = Field(primary_key=True)
    user_id: str = Field(foreign_key="user.id", index=True)
    provider: str = Field(index=True)
    provider_app_id: str
    provider_subject: str
    provider_email: str | None = Field(default=None, index=True)
    provider_email_verified: bool = False
    profile_json: dict = Field(default_factory=dict, sa_column=sa.Column(sa.JSON, nullable=False))
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    last_login_at: datetime | None = None


class AuthSession(SQLModel, table=True):
    """Opaque, revocable browser session. Only token hashes are persisted."""

    __tablename__ = "auth_session"
    __table_args__ = (
        sa.UniqueConstraint("token_hash", name="uq_auth_session_token_hash"),
        sa.Index("ix_auth_session_user_active", "user_id", "revoked_at", "expires_at"),
    )

    id: str = Field(primary_key=True)
    user_id: str = Field(foreign_key="user.id", index=True)
    token_hash: str
    csrf_token: str
    device_key: str | None = Field(default=None, index=True)
    ip_hash: str | None = None
    user_agent_hash: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    last_seen_at: datetime = Field(default_factory=utcnow)
    expires_at: datetime = Field(index=True)
    revoked_at: datetime | None = Field(default=None, index=True)


class OAuthFlow(SQLModel, table=True):
    """Single-use OAuth state, PKCE and pending linking proof."""

    __tablename__ = "oauth_flow"
    __table_args__ = (
        sa.UniqueConstraint("state_hash", name="uq_oauth_flow_state_hash"),
        sa.Index("ix_oauth_flow_pending", "provider", "consumed_at", "expires_at"),
    )

    id: str = Field(primary_key=True)
    state_hash: str
    provider: str = Field(index=True)
    mode: str = Field(default="login")
    provider_app_id: str
    initiating_user_id: str | None = Field(default=None, foreign_key="user.id", index=True)
    source_guest_user_id: str | None = Field(default=None, foreign_key="user.id", index=True)
    pkce_verifier: str | None = Field(default=None, sa_column=sa.Column(sa.Text(), nullable=True))
    nonce: str | None = None
    return_to: str = "/"
    pending_identity_json: dict = Field(default_factory=dict, sa_column=sa.Column(sa.JSON, nullable=False))
    created_at: datetime = Field(default_factory=utcnow)
    expires_at: datetime = Field(index=True)
    consumed_at: datetime | None = Field(default=None, index=True)


class AuthRateLimitBucket(SQLModel, table=True):
    """Database-backed fixed-window rate-limit bucket."""

    __tablename__ = "auth_rate_limit_bucket"
    __table_args__ = (
        sa.UniqueConstraint("bucket_key", "window_started_at", name="uq_auth_rate_limit_window"),
        sa.Index("ix_auth_rate_limit_expiry", "expires_at"),
    )

    id: str = Field(primary_key=True)
    bucket_key: str = Field(index=True)
    window_started_at: datetime
    count: int = 0
    expires_at: datetime
    updated_at: datetime = Field(default_factory=utcnow)


class UserMergeJob(SQLModel, table=True):
    """Durable, retryable guest-to-account merge job."""

    __tablename__ = "user_merge_job"
    __table_args__ = (
        sa.UniqueConstraint("source_user_id", "target_user_id", name="uq_user_merge_pair"),
        sa.Index("ix_user_merge_target_status", "target_user_id", "status"),
    )

    id: str = Field(primary_key=True)
    source_user_id: str = Field(foreign_key="user.id", index=True)
    target_user_id: str = Field(foreign_key="user.id", index=True)
    status: str = Field(default="pending", index=True)
    asset_counts_json: dict = Field(default_factory=dict, sa_column=sa.Column(sa.JSON, nullable=False))
    course_mapping_json: dict = Field(default_factory=dict, sa_column=sa.Column(sa.JSON, nullable=False))
    progress_json: dict = Field(default_factory=dict, sa_column=sa.Column(sa.JSON, nullable=False))
    failure_reason: str | None = Field(default=None, sa_column=sa.Column(sa.Text(), nullable=True))
    retry_count: int = 0
    recovery_expires_at: datetime | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    completed_at: datetime | None = None
