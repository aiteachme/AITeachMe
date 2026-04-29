"""Inline confirmed build plans into planner session metadata."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260427_0011"
down_revision = "20260427_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE chat_session AS cs
            SET meta_json = (
                COALESCE(cs.meta_json::jsonb, '{}'::jsonb)
                || jsonb_build_object(
                    'confirmed_plan_id', plan.id,
                    'confirmed_plan', jsonb_build_object(
                        'id', plan.id,
                        'course', plan.course,
                        'planner_session_id', plan.planner_session_id,
                        'user_id', plan.user_id,
                        'status', plan.status,
                        'user_prompt', plan.user_prompt,
                        'digest_mode', plan.digest_mode,
                        'selected_file_ids_json', COALESCE(to_jsonb(plan.selected_file_ids_json), '[]'::jsonb),
                        'chapter_plan_json', COALESCE(to_jsonb(plan.chapter_plan_json), '[]'::jsonb),
                        'build_constraints_json', COALESCE(to_jsonb(plan.build_constraints_json), '{}'::jsonb),
                        'plan_summary', plan.plan_summary,
                        'plan_json', COALESCE(to_jsonb(plan.plan_json), '{}'::jsonb),
                        'created_at', plan.created_at,
                        'updated_at', plan.updated_at
                    )
                )
            )::json,
                updated_at = GREATEST(COALESCE(cs.updated_at, plan.updated_at), plan.updated_at),
                last_message_at = GREATEST(COALESCE(cs.last_message_at, plan.updated_at), plan.updated_at)
            FROM confirmed_build_plan AS plan
            WHERE cs.id = plan.planner_session_id
              AND cs.course = plan.course
              AND cs.user_id = plan.user_id
              AND cs.source = 'build_planner'
            """
        )
    )
    op.execute(
        sa.text(
            "DROP TABLE confirmed_build_plan "
            "/* atm-allow-destructive-ddl: copied into chat_session.meta_json.confirmed_plan */"
        )
    )


def downgrade() -> None:
    op.create_table(
        "confirmed_build_plan",
        sa.Column("id", sa.String(), primary_key=True, nullable=False),
        sa.Column("course", sa.String(), nullable=False),
        sa.Column("planner_session_id", sa.String(), nullable=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("user_prompt", sa.Text(), nullable=False),
        sa.Column("digest_mode", sa.String(), nullable=False),
        sa.Column("selected_file_ids_json", sa.JSON(), nullable=True),
        sa.Column("chapter_plan_json", sa.JSON(), nullable=True),
        sa.Column("build_constraints_json", sa.JSON(), nullable=True),
        sa.Column("plan_summary", sa.Text(), nullable=False),
        sa.Column("plan_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_confirmed_build_plan_course", "confirmed_build_plan", ["course"])
    op.create_index("ix_confirmed_build_plan_planner_session_id", "confirmed_build_plan", ["planner_session_id"])
    op.create_index("ix_confirmed_build_plan_user_id", "confirmed_build_plan", ["user_id"])
    op.create_index("ix_confirmed_build_plan_status", "confirmed_build_plan", ["status"])
    op.create_index("ix_confirmed_build_plan_digest_mode", "confirmed_build_plan", ["digest_mode"])
    op.create_index("ix_confirmed_build_plan_created_at", "confirmed_build_plan", ["created_at"])
    op.create_index("ix_confirmed_build_plan_updated_at", "confirmed_build_plan", ["updated_at"])
    op.execute(
        sa.text(
            """
            INSERT INTO confirmed_build_plan
            (id, course, planner_session_id, user_id, status, user_prompt, digest_mode,
             selected_file_ids_json, chapter_plan_json, build_constraints_json,
             plan_summary, plan_json, created_at, updated_at)
            SELECT
                plan_payload->>'id',
                cs.course,
                cs.id,
                cs.user_id,
                COALESCE(plan_payload->>'status', 'confirmed'),
                COALESCE(plan_payload->>'user_prompt', ''),
                COALESCE(plan_payload->>'digest_mode', ''),
                COALESCE(plan_payload->'selected_file_ids_json', '[]'::jsonb)::json,
                COALESCE(plan_payload->'chapter_plan_json', '[]'::jsonb)::json,
                COALESCE(plan_payload->'build_constraints_json', '{}'::jsonb)::json,
                COALESCE(plan_payload->>'plan_summary', ''),
                COALESCE(plan_payload->'plan_json', '{}'::jsonb)::json,
                COALESCE((plan_payload->>'created_at')::timestamp, cs.created_at),
                COALESCE((plan_payload->>'updated_at')::timestamp, cs.updated_at)
            FROM (
                SELECT
                    id,
                    course,
                    user_id,
                    created_at,
                    updated_at,
                    meta_json::jsonb->'confirmed_plan' AS plan_payload
                FROM chat_session
                WHERE meta_json::jsonb ? 'confirmed_plan'
            ) AS cs
            WHERE plan_payload ? 'id'
            """
        )
    )
