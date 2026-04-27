"""Simplify settings tables and rename email confirmation records."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260427_0010"
down_revision = "20260426_0009"
branch_labels = None
depends_on = None


_EMAIL_INDEX_RENAMES = (
    ("ix_email_verification_code_email", "ix_email_confirmation_email"),
    ("ix_email_verification_code_purpose", "ix_email_confirmation_purpose"),
    ("ix_email_verification_code_code_hash", "ix_email_confirmation_code_hash"),
    ("ix_email_verification_code_expires_at", "ix_email_confirmation_expires_at"),
    ("ix_email_verification_code_consumed_at", "ix_email_confirmation_consumed_at"),
    ("ix_email_verification_code_created_at", "ix_email_confirmation_created_at"),
)


def _rename_indexes(pairs: tuple[tuple[str, str], ...]) -> None:
    for old_name, new_name in pairs:
        op.execute(sa.text(f"ALTER INDEX IF EXISTS {old_name} RENAME TO {new_name}"))


def upgrade() -> None:
    op.rename_table("email_verification_code", "email_confirmation")
    _rename_indexes(_EMAIL_INDEX_RENAMES)
    op.execute(
        sa.text(
            "ALTER SEQUENCE IF EXISTS email_verification_code_id_seq "
            "RENAME TO email_confirmation_id_seq"
        )
    )

    op.add_column("user", sa.Column("runtime_settings_json", sa.JSON(), nullable=True))
    op.execute(
        sa.text(
            """
            UPDATE "user" AS u
            SET runtime_settings_json = COALESCE(urs.settings_json, '{}'::json)
            FROM user_runtime_settings AS urs
            WHERE urs.user_id = u.id
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE "user"
            SET runtime_settings_json = '{}'::json
            WHERE runtime_settings_json IS NULL
            """
        )
    )
    op.alter_column("user", "runtime_settings_json", existing_type=sa.JSON(), nullable=False)

    op.add_column("system_runtime_settings", sa.Column("settings_source", sa.String(), nullable=True))
    op.add_column("system_runtime_settings", sa.Column("settings_hash", sa.String(), nullable=True))
    op.add_column("system_runtime_settings", sa.Column("effective_settings_json", sa.JSON(), nullable=True))
    op.execute(
        sa.text(
            """
            INSERT INTO system_runtime_settings
            (id, settings_json, settings_source, settings_hash, effective_settings_json, created_at, updated_at)
            VALUES ('runtime', '{}'::json, '', '', '{}'::json, now(), now())
            ON CONFLICT (id) DO NOTHING
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE system_runtime_settings AS runtime
            SET settings_source = COALESCE(snapshot.settings_source, ''),
                settings_hash = COALESCE(snapshot.settings_hash, ''),
                effective_settings_json = COALESCE(snapshot.settings_json, '{}'::json),
                updated_at = now()
            FROM system_settings_snapshot AS snapshot
            WHERE runtime.id = 'runtime'
              AND snapshot.id = 'runtime'
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE system_runtime_settings
            SET settings_json = COALESCE(settings_json, '{}'::json),
                settings_source = COALESCE(settings_source, ''),
                settings_hash = COALESCE(settings_hash, ''),
                effective_settings_json = COALESCE(effective_settings_json, '{}'::json)
            """
        )
    )
    op.alter_column("system_runtime_settings", "settings_json", existing_type=sa.JSON(), nullable=False)
    op.alter_column("system_runtime_settings", "settings_source", existing_type=sa.String(), nullable=False)
    op.alter_column("system_runtime_settings", "settings_hash", existing_type=sa.String(), nullable=False)
    op.alter_column("system_runtime_settings", "effective_settings_json", existing_type=sa.JSON(), nullable=False)
    op.create_index(
        "ix_system_runtime_settings_settings_hash",
        "system_runtime_settings",
        ["settings_hash"],
    )

    op.drop_index("ix_system_settings_snapshot_settings_hash", table_name="system_settings_snapshot")
    op.execute(
        sa.text(
            "DROP TABLE system_settings_snapshot "
            "/* atm-allow-destructive-ddl: copied into system_runtime_settings */"
        )
    )
    op.execute(
        sa.text(
            "DROP TABLE user_runtime_settings "
            "/* atm-allow-destructive-ddl: copied into user.runtime_settings_json */"
        )
    )


def downgrade() -> None:
    op.create_table(
        "user_runtime_settings",
        sa.Column("user_id", sa.String(), sa.ForeignKey("user.id"), primary_key=True, nullable=False),
        sa.Column("settings_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.execute(
        sa.text(
            """
            INSERT INTO user_runtime_settings (user_id, settings_json, created_at, updated_at)
            SELECT id, runtime_settings_json, created_at, updated_at
            FROM "user"
            WHERE runtime_settings_json IS NOT NULL
              AND runtime_settings_json::text <> '{}'
            """
        )
    )

    op.create_table(
        "system_settings_snapshot",
        sa.Column("id", sa.String(), primary_key=True, nullable=False),
        sa.Column("settings_source", sa.String(), nullable=False),
        sa.Column("settings_hash", sa.String(), nullable=False),
        sa.Column("settings_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_system_settings_snapshot_settings_hash", "system_settings_snapshot", ["settings_hash"])
    op.execute(
        sa.text(
            """
            INSERT INTO system_settings_snapshot
            (id, settings_source, settings_hash, settings_json, created_at, updated_at)
            SELECT id, settings_source, settings_hash, effective_settings_json, created_at, updated_at
            FROM system_runtime_settings
            WHERE id = 'runtime'
            """
        )
    )

    op.drop_index("ix_system_runtime_settings_settings_hash", table_name="system_runtime_settings")
    op.drop_column("system_runtime_settings", "effective_settings_json")
    op.drop_column("system_runtime_settings", "settings_hash")
    op.drop_column("system_runtime_settings", "settings_source")
    op.drop_column("user", "runtime_settings_json")

    _rename_indexes(tuple((new_name, old_name) for old_name, new_name in _EMAIL_INDEX_RENAMES))
    op.execute(
        sa.text(
            "ALTER SEQUENCE IF EXISTS email_confirmation_id_seq "
            "RENAME TO email_verification_code_id_seq"
        )
    )
    op.rename_table("email_confirmation", "email_verification_code")
