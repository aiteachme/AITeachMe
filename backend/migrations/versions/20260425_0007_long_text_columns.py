"""Use text columns for long free-form content.

Large generated content, JSON snapshots, chat text, and parsing metadata should
not be represented as generic varchar columns in the PostgreSQL schema.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260425_0007"
down_revision = "20260425_0006"
branch_labels = None
depends_on = None


_TEXT_COLUMNS: tuple[tuple[str, str, bool], ...] = (
    ("user", "profile_json", False),
    ("course", "preferred_digest_note", True),
    ("raw_file", "markdown_path", True),
    ("raw_file", "markdown_content", False),
    ("raw_file", "asset_dir", True),
    ("raw_file", "storage_uri", True),
    ("raw_file", "markdown_uri", True),
    ("raw_file", "asset_manifest_json", False),
    ("raw_file", "user_note", True),
    ("raw_file", "error_message", True),
    ("raw_file", "classification_result", True),
    ("raw_file", "parse_metadata", True),
    ("raw_file", "material_profile_json", False),
    ("raw_file", "parse_metadata_json", False),
    ("confirmed_build_plan", "user_prompt", False),
    ("confirmed_build_plan", "plan_summary", False),
    ("knowledge_document", "summary", False),
    ("knowledge_document", "markdown_content", False),
    ("knowledge_document", "content_markdown", False),
    ("knowledge_document", "markdown_path", True),
    ("knowledge_document", "markdown_uri", True),
    ("knowledge_document", "tags", False),
    ("knowledge_document", "source_file_ids", False),
    ("knowledge_document", "mode_decision_json", False),
    ("knowledge_document", "manifest_json", False),
    ("knowledge_document", "source_scope_json", False),
    ("knowledge_unit", "summary", False),
    ("knowledge_unit", "body", False),
    ("knowledge_unit", "body_markdown", False),
    ("knowledge_unit", "aliases_json", False),
    ("knowledge_unit", "evidence_refs_json", False),
    ("retrieval_chunk", "header_path", False),
    ("retrieval_chunk", "content", False),
    ("knowledge_edge", "description", False),
    ("knowledge_edge", "evidence_refs_json", False),
    ("question_type_registry", "description", False),
    ("question_type_registry", "option_schema_json", False),
    ("question_type_registry", "rubric_json", False),
    ("question_template", "stem", False),
    ("question_template", "options_json", True),
    ("question_template", "answer", False),
    ("question_template", "explanation", False),
    ("question_template", "knowledge_unit_refs_json", False),
    ("question_template", "selection_hints_json", False),
    ("exam_paper", "selection_context_json", False),
    ("exam_paper_item", "stem_snapshot", False),
    ("exam_paper_item", "options_snapshot_json", True),
    ("exam_paper_item", "answer_snapshot", False),
    ("exam_paper_item", "explanation_snapshot", False),
    ("exam_paper_item", "knowledge_unit_refs_json", False),
    ("exam_paper_item", "answer_content", False),
    ("exam_paper_item", "feedback_text", True),
    ("user_knowledge_state", "review_reason", True),
    ("user_knowledge_state", "stats_json", False),
    ("chat_message", "selected_text", True),
    ("chat_message", "content", False),
)


def upgrade() -> None:
    for table_name, column_name, nullable in _TEXT_COLUMNS:
        op.alter_column(
            table_name,
            column_name,
            existing_type=sa.String(),
            type_=sa.Text(),
            existing_nullable=nullable,
        )


def downgrade() -> None:
    for table_name, column_name, nullable in reversed(_TEXT_COLUMNS):
        op.alter_column(
            table_name,
            column_name,
            existing_type=sa.Text(),
            type_=sa.String(),
            existing_nullable=nullable,
        )
