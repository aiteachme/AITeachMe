"""Add raw file parse request signatures."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import context, op


revision = "20260428_0015"
down_revision = "20260428_0014"
branch_labels = None
depends_on = None

_ACTIVE_SIGNATURE_WHERE = "status != 'failed' AND content_hash IS NOT NULL AND file_size_bytes IS NOT NULL"


def _backfill_duplicate_default_signatures() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "UPDATE raw_file SET parse_request_signature = 'default' "
            "WHERE parse_request_signature IS NULL OR parse_request_signature = ''"
        )
    )

    if op.get_context().dialect.name == "sqlite":
        connection.execute(
            sa.text(
                """
                WITH duplicate_defaults AS (
                    SELECT id,
                           row_number() OVER (
                               PARTITION BY user_id, content_hash, file_size_bytes, filetype
                               ORDER BY created_at ASC, id ASC
                           ) AS row_rank
                    FROM raw_file
                    WHERE status != 'failed'
                      AND content_hash IS NOT NULL
                      AND file_size_bytes IS NOT NULL
                      AND parse_request_signature = 'default'
                )
                UPDATE raw_file
                SET parse_request_signature = 'legacy:' || id
                WHERE id IN (
                    SELECT id
                    FROM duplicate_defaults
                    WHERE row_rank > 1
                )
                """
            )
        )
        return

    connection.execute(
        sa.text(
            """
            WITH duplicate_defaults AS (
                SELECT id,
                       row_number() OVER (
                           PARTITION BY user_id, content_hash, file_size_bytes, filetype
                           ORDER BY created_at ASC, id ASC
                       ) AS row_rank
                FROM raw_file
                WHERE status != 'failed'
                  AND content_hash IS NOT NULL
                  AND file_size_bytes IS NOT NULL
                  AND parse_request_signature = 'default'
            )
            UPDATE raw_file AS target
            SET parse_request_signature = 'legacy:' || target.id::text
            FROM duplicate_defaults AS duplicate
            WHERE target.id = duplicate.id
              AND duplicate.row_rank > 1
            """
        )
    )


def upgrade() -> None:
    op.add_column(
        "raw_file",
        sa.Column("parse_request_signature", sa.String(length=80), nullable=False, server_default="default"),
    )
    if context.is_offline_mode():
        op.execute(
            "UPDATE raw_file SET parse_request_signature = 'default' "
            "WHERE parse_request_signature IS NULL OR parse_request_signature = ''"
        )
    else:
        _backfill_duplicate_default_signatures()
    op.create_index(
        "uq_raw_file_user_hash_size_type_signature_active",
        "raw_file",
        ["user_id", "content_hash", "file_size_bytes", "filetype", "parse_request_signature"],
        unique=True,
        postgresql_where=sa.text(_ACTIVE_SIGNATURE_WHERE),
        sqlite_where=sa.text(_ACTIVE_SIGNATURE_WHERE),
    )


def downgrade() -> None:
    op.drop_index("uq_raw_file_user_hash_size_type_signature_active", table_name="raw_file")
    op.drop_column("raw_file", "parse_request_signature")
