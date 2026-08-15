"""Add revocable auth, OAuth identities, AI credits, and portable memory tables."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import context, op


revision = "20260815_0029"
down_revision = "20260807_0028"
branch_labels = None
depends_on = None


def _table_names() -> set[str]:
    if context.is_offline_mode():
        # PostgreSQL migrations never created the old runtime-owned memory
        # tables. Offline SQL should therefore emit their CREATE statements.
        return set()
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    op.add_column("user", sa.Column("role", sa.String(), server_default="user", nullable=False))
    op.add_column("user", sa.Column("display_name", sa.String(), nullable=True))
    op.add_column("user", sa.Column("avatar_url", sa.Text(), nullable=True))
    op.add_column("user", sa.Column("email_verified_at", sa.DateTime(), nullable=True))
    op.add_column("user", sa.Column("merged_into_user_id", sa.String(), nullable=True))
    if op.get_bind().dialect.name != "sqlite":
        op.create_foreign_key(
            "fk_user_merged_into_user_id_user",
            "user", "user", ["merged_into_user_id"], ["id"],
        )
    op.create_index(op.f("ix_user_role"), "user", ["role"], unique=False)
    op.create_index(op.f("ix_user_email_verified_at"), "user", ["email_verified_at"], unique=False)
    op.create_index(op.f("ix_user_merged_into_user_id"), "user", ["merged_into_user_id"], unique=False)

    op.create_table(
        "auth_identity",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("provider_app_id", sa.String(), nullable=False),
        sa.Column("provider_subject", sa.String(), nullable=False),
        sa.Column("provider_email", sa.String(), nullable=True),
        sa.Column("provider_email_verified", sa.Boolean(), nullable=False),
        sa.Column("profile_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "provider_app_id", "provider_subject", name="uq_auth_identity_provider_subject"),
        sa.UniqueConstraint("user_id", "provider", "provider_app_id", name="uq_auth_identity_user_provider"),
    )
    op.create_index("ix_auth_identity_user_provider", "auth_identity", ["user_id", "provider"])
    op.create_index(op.f("ix_auth_identity_user_id"), "auth_identity", ["user_id"])
    op.create_index(op.f("ix_auth_identity_provider"), "auth_identity", ["provider"])
    op.create_index(op.f("ix_auth_identity_provider_email"), "auth_identity", ["provider_email"])

    op.create_table(
        "auth_session",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("csrf_token", sa.String(), nullable=False),
        sa.Column("device_key", sa.String(), nullable=True),
        sa.Column("ip_hash", sa.String(), nullable=True),
        sa.Column("user_agent_hash", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_auth_session_token_hash"),
    )
    op.create_index("ix_auth_session_user_active", "auth_session", ["user_id", "revoked_at", "expires_at"])
    for column in ("user_id", "device_key", "expires_at", "revoked_at"):
        op.create_index(op.f(f"ix_auth_session_{column}"), "auth_session", [column])

    op.create_table(
        "oauth_flow",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("state_hash", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("mode", sa.String(), nullable=False),
        sa.Column("provider_app_id", sa.String(), nullable=False),
        sa.Column("initiating_user_id", sa.String(), nullable=True),
        sa.Column("source_guest_user_id", sa.String(), nullable=True),
        sa.Column("pkce_verifier", sa.Text(), nullable=True),
        sa.Column("nonce", sa.String(), nullable=True),
        sa.Column("return_to", sa.String(), nullable=False),
        sa.Column("pending_identity_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["initiating_user_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["source_guest_user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("state_hash", name="uq_oauth_flow_state_hash"),
    )
    op.create_index("ix_oauth_flow_pending", "oauth_flow", ["provider", "consumed_at", "expires_at"])
    for column in ("provider", "initiating_user_id", "source_guest_user_id", "expires_at", "consumed_at"):
        op.create_index(op.f(f"ix_oauth_flow_{column}"), "oauth_flow", [column])

    op.create_table(
        "auth_rate_limit_bucket",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("bucket_key", sa.String(), nullable=False),
        sa.Column("window_started_at", sa.DateTime(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("bucket_key", "window_started_at", name="uq_auth_rate_limit_window"),
    )
    op.create_index(op.f("ix_auth_rate_limit_bucket_bucket_key"), "auth_rate_limit_bucket", ["bucket_key"])
    op.create_index("ix_auth_rate_limit_expiry", "auth_rate_limit_bucket", ["expires_at"])

    op.create_table(
        "user_merge_job",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("source_user_id", sa.String(), nullable=False),
        sa.Column("target_user_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("asset_counts_json", sa.JSON(), nullable=False),
        sa.Column("course_mapping_json", sa.JSON(), nullable=False),
        sa.Column("progress_json", sa.JSON(), nullable=False),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("recovery_expires_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["source_user_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["target_user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_user_id", "target_user_id", name="uq_user_merge_pair"),
    )
    op.create_index("ix_user_merge_target_status", "user_merge_job", ["target_user_id", "status"])
    for column in ("source_user_id", "target_user_id", "status", "recovery_expires_at"):
        op.create_index(op.f(f"ix_user_merge_job_{column}"), "user_merge_job", [column])

    op.create_table(
        "credit_account",
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("balance", sa.Integer(), nullable=False),
        sa.Column("reserved_balance", sa.Integer(), nullable=False),
        sa.Column("lifetime_granted", sa.Integer(), nullable=False),
        sa.Column("lifetime_spent", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("signup_grant_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("balance >= 0", name="ck_credit_account_balance_nonnegative"),
        sa.CheckConstraint("reserved_balance >= 0", name="ck_credit_account_reserved_nonnegative"),
        sa.CheckConstraint("reserved_balance <= balance", name="ck_credit_account_reserved_lte_balance"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_index(op.f("ix_credit_account_signup_grant_at"), "credit_account", ["signup_grant_at"])

    op.create_table(
        "credit_ledger",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("delta", sa.Integer(), nullable=False),
        sa.Column("operation", sa.String(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("reference_type", sa.String(), nullable=True),
        sa.Column("reference_id", sa.String(), nullable=True),
        sa.Column("operator_user_id", sa.String(), nullable=True),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("balance_before", sa.Integer(), nullable=False),
        sa.Column("balance_after", sa.Integer(), nullable=False),
        sa.Column("reserved_before", sa.Integer(), nullable=False),
        sa.Column("reserved_after", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("delta != 0", name="ck_credit_ledger_nonzero_delta"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["operator_user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_credit_ledger_idempotency"),
    )
    op.create_index("ix_credit_ledger_user_created", "credit_ledger", ["user_id", "created_at"])
    for column in ("user_id", "operation", "reference_type", "reference_id", "operator_user_id", "created_at"):
        op.create_index(op.f(f"ix_credit_ledger_{column}"), "credit_ledger", [column])

    op.create_table(
        "credit_reservation",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("feature", sa.String(), nullable=False),
        sa.Column("reference_id", sa.String(), nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("settled_at", sa.DateTime(), nullable=True),
        sa.Column("released_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("amount > 0", name="ck_credit_reservation_positive_amount"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "feature", "reference_id", name="uq_credit_reservation_business_ref"),
        sa.UniqueConstraint("idempotency_key", name="uq_credit_reservation_idempotency"),
    )
    op.create_index("ix_credit_reservation_user_status", "credit_reservation", ["user_id", "status"])
    op.create_index("ix_credit_reservation_recovery", "credit_reservation", ["status", "expires_at"])
    for column in ("user_id", "feature", "status", "expires_at"):
        op.create_index(op.f(f"ix_credit_reservation_{column}"), "credit_reservation", [column])

    op.execute(sa.text("""
        INSERT INTO credit_account (
            user_id, balance, reserved_balance, lifetime_granted, lifetime_spent,
            version, signup_grant_at, created_at, updated_at
        )
        SELECT
            id, 300, 0, 300, 0,
            1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        FROM "user"
        WHERE is_registered
    """))
    op.execute(sa.text("""
        INSERT INTO credit_ledger (
            id, user_id, delta, operation, reason, reference_type, reference_id,
            operator_user_id, idempotency_key, balance_before, balance_after,
            reserved_before, reserved_after, created_at
        )
        SELECT
            'clg_signup_' || id, id, 300, 'signup_grant', '注册账号初始 AI 额度',
            'user', id, NULL, 'signup-grant:' || id, 0, 300, 0, 0, CURRENT_TIMESTAMP
        FROM "user"
        WHERE is_registered
    """))

    existing = _table_names()
    if "memory_entries" not in existing:
        op.create_table(
            "memory_entries",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("key", sa.String(), nullable=False),
            sa.Column("user_id", sa.String(), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("tag", sa.String(), nullable=False),
            sa.Column("importance", sa.Float(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("key", name="uq_memory_entries_key"),
        )
        op.create_index(op.f("ix_memory_entries_key"), "memory_entries", ["key"])
        op.create_index(op.f("ix_memory_entries_user_id"), "memory_entries", ["user_id"])
        op.create_index(op.f("ix_memory_entries_updated_at"), "memory_entries", ["updated_at"])
        op.create_index("ix_memory_entries_user_tag", "memory_entries", ["user_id", "tag"])
    if "learning_logs" not in existing:
        op.create_table(
            "learning_logs",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("user_id", sa.String(), nullable=False),
            sa.Column("event_type", sa.String(), nullable=False),
            sa.Column("course_id", sa.String(), nullable=False),
            sa.Column("summary", sa.Text(), nullable=False),
            sa.Column("metadata", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_learning_logs_user_id"), "learning_logs", ["user_id"])
        op.create_index(op.f("ix_learning_logs_event_type"), "learning_logs", ["event_type"])
        op.create_index(op.f("ix_learning_logs_created_at"), "learning_logs", ["created_at"])
        op.create_index("ix_learning_logs_user_created", "learning_logs", ["user_id", "created_at"])


def downgrade() -> None:
    if op.get_bind().dialect.name != "sqlite":
        # SQLite may have owned these runtime tables before this revision.
        # PostgreSQL did not, so this migration must remove what it created.
        op.drop_table("learning_logs")
        op.drop_table("memory_entries")
    for table_name in (
        "credit_reservation", "credit_ledger", "credit_account", "user_merge_job",
        "auth_rate_limit_bucket", "oauth_flow", "auth_session", "auth_identity",
    ):
        op.drop_table(table_name)
    op.drop_index(op.f("ix_user_merged_into_user_id"), table_name="user")
    op.drop_index(op.f("ix_user_email_verified_at"), table_name="user")
    op.drop_index(op.f("ix_user_role"), table_name="user")
    if op.get_bind().dialect.name != "sqlite":
        op.drop_constraint("fk_user_merged_into_user_id_user", "user", type_="foreignkey")
    for column in ("merged_into_user_id", "email_verified_at", "avatar_url", "display_name", "role"):
        op.drop_column("user", column)
