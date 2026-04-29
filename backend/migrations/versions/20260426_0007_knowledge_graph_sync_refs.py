"""Add knowledge graph sync provenance tables."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260426_0007"
down_revision = "20260426_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_graph_sync_run",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("course", sa.String(), nullable=False),
        sa.Column("build_session_id", sa.String(), nullable=True),
        sa.Column("doc_version_no", sa.Integer(), nullable=False),
        sa.Column("graph_revision_no", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("metrics_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("error_message", sa.Text(), nullable=False, server_default=""),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_knowledge_graph_sync_run_course", "knowledge_graph_sync_run", ["course"])
    op.create_index("ix_knowledge_graph_sync_run_build_session_id", "knowledge_graph_sync_run", ["build_session_id"])
    op.create_index("ix_knowledge_graph_sync_run_doc_version_no", "knowledge_graph_sync_run", ["doc_version_no"])
    op.create_index("ix_knowledge_graph_sync_run_graph_revision_no", "knowledge_graph_sync_run", ["graph_revision_no"])
    op.create_index("ix_knowledge_graph_sync_run_status", "knowledge_graph_sync_run", ["status"])
    op.create_index("ix_kg_sync_run_course_revision", "knowledge_graph_sync_run", ["course", "graph_revision_no"])
    op.create_index("ix_kg_sync_run_course_doc_version", "knowledge_graph_sync_run", ["course", "doc_version_no"])

    op.create_table(
        "knowledge_graph_source_ref",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("course", sa.String(), nullable=False),
        sa.Column("entity_type", sa.String(), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("sync_run_id", sa.Integer(), sa.ForeignKey("knowledge_graph_sync_run.id"), nullable=True),
        sa.Column("knowledge_document_id", sa.Integer(), sa.ForeignKey("knowledge_document.id"), nullable=True),
        sa.Column("chapter_index", sa.Integer(), nullable=False),
        sa.Column("anchor", sa.String(), nullable=False),
        sa.Column("source_kind", sa.String(), nullable=False, server_default=""),
        sa.Column("source_file_ids_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("quote_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_knowledge_graph_source_ref_course", "knowledge_graph_source_ref", ["course"])
    op.create_index("ix_knowledge_graph_source_ref_entity_type", "knowledge_graph_source_ref", ["entity_type"])
    op.create_index("ix_knowledge_graph_source_ref_entity_id", "knowledge_graph_source_ref", ["entity_id"])
    op.create_index("ix_knowledge_graph_source_ref_sync_run_id", "knowledge_graph_source_ref", ["sync_run_id"])
    op.create_index(
        "ix_knowledge_graph_source_ref_knowledge_document_id",
        "knowledge_graph_source_ref",
        ["knowledge_document_id"],
    )
    op.create_index("ix_knowledge_graph_source_ref_chapter_index", "knowledge_graph_source_ref", ["chapter_index"])
    op.create_index("ix_knowledge_graph_source_ref_anchor", "knowledge_graph_source_ref", ["anchor"])
    op.create_index("ix_knowledge_graph_source_ref_source_kind", "knowledge_graph_source_ref", ["source_kind"])
    op.create_index("ix_kg_source_ref_entity", "knowledge_graph_source_ref", ["entity_type", "entity_id"])
    op.create_index("ix_kg_source_ref_course_chapter", "knowledge_graph_source_ref", ["course", "chapter_index"])


def downgrade() -> None:
    op.drop_index("ix_kg_source_ref_course_chapter", table_name="knowledge_graph_source_ref")
    op.drop_index("ix_kg_source_ref_entity", table_name="knowledge_graph_source_ref")
    op.drop_index("ix_knowledge_graph_source_ref_source_kind", table_name="knowledge_graph_source_ref")
    op.drop_index("ix_knowledge_graph_source_ref_anchor", table_name="knowledge_graph_source_ref")
    op.drop_index("ix_knowledge_graph_source_ref_chapter_index", table_name="knowledge_graph_source_ref")
    op.drop_index("ix_knowledge_graph_source_ref_knowledge_document_id", table_name="knowledge_graph_source_ref")
    op.drop_index("ix_knowledge_graph_source_ref_sync_run_id", table_name="knowledge_graph_source_ref")
    op.drop_index("ix_knowledge_graph_source_ref_entity_id", table_name="knowledge_graph_source_ref")
    op.drop_index("ix_knowledge_graph_source_ref_entity_type", table_name="knowledge_graph_source_ref")
    op.drop_index("ix_knowledge_graph_source_ref_course", table_name="knowledge_graph_source_ref")
    op.drop_table("knowledge_graph_source_ref")

    op.drop_index("ix_kg_sync_run_course_doc_version", table_name="knowledge_graph_sync_run")
    op.drop_index("ix_kg_sync_run_course_revision", table_name="knowledge_graph_sync_run")
    op.drop_index("ix_knowledge_graph_sync_run_status", table_name="knowledge_graph_sync_run")
    op.drop_index("ix_knowledge_graph_sync_run_graph_revision_no", table_name="knowledge_graph_sync_run")
    op.drop_index("ix_knowledge_graph_sync_run_doc_version_no", table_name="knowledge_graph_sync_run")
    op.drop_index("ix_knowledge_graph_sync_run_build_session_id", table_name="knowledge_graph_sync_run")
    op.drop_index("ix_knowledge_graph_sync_run_course", table_name="knowledge_graph_sync_run")
    op.drop_table("knowledge_graph_sync_run")
