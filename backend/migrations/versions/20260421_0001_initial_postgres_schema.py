"""Initial PostgreSQL schema.

This migration is intentionally handwritten from the current SQLModel schema.
Alembic autogenerate is useful for drafts, but production revisions must be
reviewed and kept deterministic.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260421_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "user",
        sa.Column("id", sa.String(), primary_key=True, nullable=False),
        sa.Column("username", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column("device_key", sa.String(), nullable=True),
        sa.Column("password_hash", sa.String(), nullable=True),
        sa.Column("is_registered", sa.Boolean(), nullable=False),
        sa.Column("last_seen_ip", sa.String(), nullable=True),
        sa.Column("profile_json", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_user_username", "user", ["username"], unique=True)
    op.create_index("ix_user_email", "user", ["email"], unique=True)
    op.create_index("ix_user_device_key", "user", ["device_key"], unique=True)
    op.create_index("ix_user_is_registered", "user", ["is_registered"])

    op.create_table(
        "email_verification_code",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("purpose", sa.String(), nullable=False),
        sa.Column("code_hash", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_email_verification_code_email", "email_verification_code", ["email"])
    op.create_index("ix_email_verification_code_purpose", "email_verification_code", ["purpose"])
    op.create_index("ix_email_verification_code_code_hash", "email_verification_code", ["code_hash"])
    op.create_index("ix_email_verification_code_expires_at", "email_verification_code", ["expires_at"])
    op.create_index("ix_email_verification_code_consumed_at", "email_verification_code", ["consumed_at"])
    op.create_index("ix_email_verification_code_created_at", "email_verification_code", ["created_at"])

    op.create_table(
        "subject",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("user_id", sa.String(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("normalized_name", sa.String(), nullable=True),
        sa.Column("preferred_digest_mode", sa.String(), nullable=True),
        sa.Column("preferred_digest_note", sa.String(), nullable=True),
        sa.Column("detected_discipline", sa.String(), nullable=True),
        sa.Column("detected_sub_discipline", sa.String(), nullable=True),
        sa.Column("profile_json", sa.String(), nullable=False),
        sa.Column("settings_json", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("build_lock_holder", sa.String(), nullable=True),
        sa.Column("build_lock_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_subject_user_id", "subject", ["user_id"])
    op.create_index("ix_subject_slug", "subject", ["slug"], unique=True)
    op.create_index("ix_subject_normalized_name", "subject", ["normalized_name"])
    op.create_index("ix_subject_status", "subject", ["status"])

    op.create_table(
        "raw_file",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("uid", sa.String(), nullable=False),
        sa.Column("subject", sa.String(), nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("filetype", sa.String(), nullable=False),
        sa.Column("file_path", sa.String(), nullable=False),
        sa.Column("mime_type", sa.String(), nullable=True),
        sa.Column("storage_backend", sa.String(), nullable=False),
        sa.Column("markdown_path", sa.String(), nullable=True),
        sa.Column("markdown_content", sa.String(), nullable=False),
        sa.Column("asset_dir", sa.String(), nullable=True),
        sa.Column("storage_uri", sa.String(), nullable=True),
        sa.Column("markdown_uri", sa.String(), nullable=True),
        sa.Column("asset_manifest_json", sa.String(), nullable=False),
        sa.Column("user_note", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=True),
        sa.Column("file_size_bytes", sa.Integer(), nullable=True),
        sa.Column("estimated_pages", sa.Integer(), nullable=True),
        sa.Column("detected_language", sa.String(), nullable=True),
        sa.Column("detected_discipline", sa.String(), nullable=True),
        sa.Column("detected_sub_discipline", sa.String(), nullable=True),
        sa.Column("detected_content_type", sa.String(), nullable=True),
        sa.Column("classification_result", sa.String(), nullable=True),
        sa.Column("quality_score", sa.Float(), nullable=True),
        sa.Column("parse_metadata", sa.String(), nullable=True),
        sa.Column("material_profile_json", sa.String(), nullable=False),
        sa.Column("parse_metadata_json", sa.String(), nullable=False),
        sa.Column("image_count", sa.Integer(), nullable=True),
        sa.Column("ingest_status", sa.String(), nullable=False),
        sa.Column("current_step", sa.String(), nullable=True),
    )
    op.create_index("ix_raw_file_uid", "raw_file", ["uid"], unique=True)
    op.create_index("ix_raw_file_subject", "raw_file", ["subject"])
    op.create_index("ix_raw_file_status", "raw_file", ["status"])
    op.create_index("ix_raw_file_detected_discipline", "raw_file", ["detected_discipline"])
    op.create_index("ix_raw_file_ingest_status", "raw_file", ["ingest_status"])
    op.create_index("ix_raw_file_current_step", "raw_file", ["current_step"])

    op.create_table(
        "confirmed_build_plan",
        sa.Column("id", sa.String(), primary_key=True, nullable=False),
        sa.Column("subject", sa.String(), nullable=False),
        sa.Column("planner_session_id", sa.String(), nullable=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("user_prompt", sa.String(), nullable=False),
        sa.Column("digest_mode", sa.String(), nullable=False),
        sa.Column("selected_file_ids_json", sa.JSON(), nullable=True),
        sa.Column("chapter_plan_json", sa.JSON(), nullable=True),
        sa.Column("build_constraints_json", sa.JSON(), nullable=True),
        sa.Column("plan_summary", sa.String(), nullable=False),
        sa.Column("plan_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_confirmed_build_plan_subject", "confirmed_build_plan", ["subject"])
    op.create_index("ix_confirmed_build_plan_planner_session_id", "confirmed_build_plan", ["planner_session_id"])
    op.create_index("ix_confirmed_build_plan_user_id", "confirmed_build_plan", ["user_id"])
    op.create_index("ix_confirmed_build_plan_status", "confirmed_build_plan", ["status"])
    op.create_index("ix_confirmed_build_plan_digest_mode", "confirmed_build_plan", ["digest_mode"])
    op.create_index("ix_confirmed_build_plan_created_at", "confirmed_build_plan", ["created_at"])
    op.create_index("ix_confirmed_build_plan_updated_at", "confirmed_build_plan", ["updated_at"])

    op.create_table(
        "knowledge_document",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("subject", sa.String(), nullable=False),
        sa.Column("root_document_id", sa.Integer(), sa.ForeignKey("knowledge_document.id"), nullable=True),
        sa.Column("parent_document_id", sa.Integer(), sa.ForeignKey("knowledge_document.id"), nullable=True),
        sa.Column("package_key", sa.String(), nullable=True),
        sa.Column("build_session_id", sa.String(), nullable=True),
        sa.Column("chapter_index", sa.Integer(), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("summary", sa.String(), nullable=False),
        sa.Column("markdown_content", sa.String(), nullable=False),
        sa.Column("content_markdown", sa.String(), nullable=False),
        sa.Column("markdown_path", sa.String(), nullable=True),
        sa.Column("markdown_uri", sa.String(), nullable=True),
        sa.Column("tags", sa.String(), nullable=False),
        sa.Column("source_file_ids", sa.String(), nullable=False),
        sa.Column("word_count", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("document_role", sa.String(), nullable=False),
        sa.Column("digest_mode", sa.String(), nullable=True),
        sa.Column("mode_confidence", sa.Float(), nullable=True),
        sa.Column("mode_decision_json", sa.String(), nullable=False),
        sa.Column("manifest_json", sa.String(), nullable=False),
        sa.Column("source_scope_json", sa.String(), nullable=False),
        sa.Column("build_kind", sa.String(), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("superseded_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_knowledge_document_subject", "knowledge_document", ["subject"])
    op.create_index("ix_knowledge_document_root_document_id", "knowledge_document", ["root_document_id"])
    op.create_index("ix_knowledge_document_parent_document_id", "knowledge_document", ["parent_document_id"])
    op.create_index("ix_knowledge_document_package_key", "knowledge_document", ["package_key"])
    op.create_index("ix_knowledge_document_build_session_id", "knowledge_document", ["build_session_id"])
    op.create_index("ix_knowledge_document_document_role", "knowledge_document", ["document_role"])
    op.create_index("ix_knowledge_document_digest_mode", "knowledge_document", ["digest_mode"])
    op.create_index("ix_knowledge_document_is_current", "knowledge_document", ["is_current"])
    op.create_index("ix_knowledge_document_status", "knowledge_document", ["status"])

    op.create_table(
        "knowledge_unit",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("subject", sa.String(), nullable=False),
        sa.Column("knowledge_unit_type", sa.String(), nullable=False),
        sa.Column("canonical_name", sa.String(), nullable=False),
        sa.Column("normalized_name", sa.String(), nullable=False),
        sa.Column("summary", sa.String(), nullable=False),
        sa.Column("body", sa.String(), nullable=False),
        sa.Column("body_markdown", sa.String(), nullable=False),
        sa.Column("aliases_json", sa.String(), nullable=False),
        sa.Column("evidence_refs_json", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("type_confidence", sa.Float(), nullable=False),
        sa.Column("type_source", sa.String(), nullable=False),
        sa.Column("build_revision_no", sa.Integer(), nullable=False),
        sa.Column("current_revision_id", sa.Integer(), nullable=True),
        sa.Column("merged_into_knowledge_unit_id", sa.Integer(), sa.ForeignKey("knowledge_unit.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("subject", "knowledge_unit_type", "normalized_name", name="uq_unit_subject_type_name"),
    )
    op.create_index("ix_knowledge_unit_subject", "knowledge_unit", ["subject"])
    op.create_index("ix_knowledge_unit_knowledge_unit_type", "knowledge_unit", ["knowledge_unit_type"])
    op.create_index("ix_knowledge_unit_normalized_name", "knowledge_unit", ["normalized_name"])
    op.create_index("ix_knowledge_unit_type_source", "knowledge_unit", ["type_source"])
    op.create_index("ix_knowledge_unit_build_revision_no", "knowledge_unit", ["build_revision_no"])
    op.create_index("ix_unit_subject_status", "knowledge_unit", ["subject", "status"])

    op.create_table(
        "retrieval_chunk",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("subject", sa.String(), sa.ForeignKey("subject.slug"), nullable=False),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("raw_file.id"), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("header_path", sa.String(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("digest_chunk_uid", sa.String(), nullable=False),
        sa.Column("build_session_id", sa.String(), nullable=False),
        sa.Column("content", sa.String(), nullable=False),
        sa.Column("embedding_model", sa.String(), nullable=True),
        sa.Column("vector_ref", sa.String(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("document_id", "chunk_index", name="uq_retrieval_chunk_document_id_chunk_index"),
        sa.UniqueConstraint("subject", "digest_chunk_uid", name="uq_retrieval_chunk_subject_digest_chunk_uid"),
    )
    op.create_index("ix_retrieval_chunk_subject", "retrieval_chunk", ["subject"])
    op.create_index("ix_retrieval_chunk_document_id", "retrieval_chunk", ["document_id"])
    op.create_index("ix_retrieval_chunk_digest_chunk_uid", "retrieval_chunk", ["digest_chunk_uid"])
    op.create_index("ix_retrieval_chunk_build_session_id", "retrieval_chunk", ["build_session_id"])
    op.create_index("ix_retrieval_chunk_is_active", "retrieval_chunk", ["is_active"])

    op.create_table(
        "knowledge_edge",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("subject", sa.String(), nullable=False),
        sa.Column("source_node_id", sa.Integer(), sa.ForeignKey("knowledge_unit.id"), nullable=False),
        sa.Column("target_node_id", sa.Integer(), sa.ForeignKey("knowledge_unit.id"), nullable=False),
        sa.Column("edge_type", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("evidence_refs_json", sa.String(), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("build_revision_no", sa.Integer(), nullable=False),
        sa.Column("current_revision_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("subject", "source_node_id", "target_node_id", "edge_type", name="uq_edge_subject_src_tgt_type"),
    )
    op.create_index("ix_knowledge_edge_subject", "knowledge_edge", ["subject"])
    op.create_index("ix_knowledge_edge_source_node_id", "knowledge_edge", ["source_node_id"])
    op.create_index("ix_knowledge_edge_target_node_id", "knowledge_edge", ["target_node_id"])
    op.create_index("ix_knowledge_edge_edge_type", "knowledge_edge", ["edge_type"])
    op.create_index("ix_knowledge_edge_build_revision_no", "knowledge_edge", ["build_revision_no"])
    op.create_index("ix_edge_subject_status", "knowledge_edge", ["subject", "status"])

    op.create_table(
        "question_template",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("subject", sa.String(), nullable=False),
        sa.Column("knowledge_unit_id", sa.Integer(), sa.ForeignKey("knowledge_unit.id"), nullable=True),
        sa.Column("question_type", sa.String(), nullable=False),
        sa.Column("difficulty", sa.String(), nullable=False),
        sa.Column("stem", sa.String(), nullable=False),
        sa.Column("stem_hash", sa.String(), nullable=False),
        sa.Column("options_json", sa.String(), nullable=True),
        sa.Column("answer", sa.String(), nullable=False),
        sa.Column("explanation", sa.String(), nullable=False),
        sa.Column("knowledge_unit_refs_json", sa.String(), nullable=False),
        sa.Column("selection_hints_json", sa.String(), nullable=False),
        sa.Column("template_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("subject", "knowledge_unit_id", "stem_hash", name="uq_template_subject_node_stem"),
    )
    op.create_index("ix_question_template_subject", "question_template", ["subject"])
    op.create_index("ix_question_template_knowledge_unit_id", "question_template", ["knowledge_unit_id"])
    op.create_index("ix_question_template_stem_hash", "question_template", ["stem_hash"])

    op.create_table(
        "exam_paper",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("subject", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("exam_mode", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("total_items", sa.Integer(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(), nullable=True),
        sa.Column("graded_at", sa.DateTime(), nullable=True),
        sa.Column("total_score", sa.Float(), nullable=True),
        sa.Column("score_obtained", sa.Float(), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("selection_context_json", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_exam_paper_subject", "exam_paper", ["subject"])
    op.create_index("ix_exam_paper_user_id", "exam_paper", ["user_id"])
    op.create_index("ix_exam_paper_status", "exam_paper", ["status"])

    op.create_table(
        "exam_paper_item",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("exam_paper_id", sa.Integer(), sa.ForeignKey("exam_paper.id"), nullable=False),
        sa.Column("question_template_id", sa.Integer(), sa.ForeignKey("question_template.id"), nullable=False),
        sa.Column("item_order", sa.Integer(), nullable=False),
        sa.Column("stem_snapshot", sa.String(), nullable=False),
        sa.Column("options_snapshot_json", sa.String(), nullable=True),
        sa.Column("answer_snapshot", sa.String(), nullable=False),
        sa.Column("explanation_snapshot", sa.String(), nullable=False),
        sa.Column("knowledge_unit_id", sa.Integer(), sa.ForeignKey("knowledge_unit.id"), nullable=True),
        sa.Column("knowledge_unit_refs_json", sa.String(), nullable=False),
        sa.Column("difficulty", sa.String(), nullable=False),
        sa.Column("question_type", sa.String(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("answer_content", sa.String(), nullable=False),
        sa.Column("is_correct", sa.Boolean(), nullable=True),
        sa.Column("score_obtained", sa.Float(), nullable=True),
        sa.Column("score_max", sa.Float(), nullable=True),
        sa.Column("time_spent_seconds", sa.Integer(), nullable=True),
        sa.Column("hint_used", sa.Boolean(), nullable=False),
        sa.Column("confidence_self_report", sa.Integer(), nullable=True),
        sa.Column("error_cause_label", sa.String(), nullable=True),
        sa.Column("feedback_text", sa.String(), nullable=True),
        sa.Column("answered_at", sa.DateTime(), nullable=True),
        sa.Column("graded_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("exam_paper_id", "item_order", name="uq_paper_item_order"),
    )
    op.create_index("ix_exam_paper_item_exam_paper_id", "exam_paper_item", ["exam_paper_id"])
    op.create_index("ix_exam_paper_item_question_template_id", "exam_paper_item", ["question_template_id"])
    op.create_index("ix_exam_paper_item_knowledge_unit_id", "exam_paper_item", ["knowledge_unit_id"])

    op.create_table(
        "user_knowledge_state",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("subject", sa.String(), nullable=False),
        sa.Column("knowledge_unit_id", sa.Integer(), sa.ForeignKey("knowledge_unit.id"), nullable=True),
        sa.Column("mastery_score", sa.Float(), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=False),
        sa.Column("stability_score", sa.Float(), nullable=False),
        sa.Column("forgetting_due_at", sa.DateTime(), nullable=True),
        sa.Column("review_priority", sa.Float(), nullable=False),
        sa.Column("total_attempts", sa.Integer(), nullable=False),
        sa.Column("correct_attempts", sa.Integer(), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("review_status", sa.String(), nullable=False),
        sa.Column("scheduled_review_at", sa.DateTime(), nullable=True),
        sa.Column("review_interval_days", sa.Integer(), nullable=False),
        sa.Column("review_ease_factor", sa.Float(), nullable=False),
        sa.Column("review_repetition_count", sa.Integer(), nullable=False),
        sa.Column("review_reason", sa.String(), nullable=True),
        sa.Column("source_exam_paper_id", sa.Integer(), sa.ForeignKey("exam_paper.id"), nullable=True),
        sa.Column("state_version", sa.Integer(), nullable=False),
        sa.Column("last_recomputed_at", sa.DateTime(), nullable=True),
        sa.Column("stats_json", sa.String(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_user_knowledge_state_user_id", "user_knowledge_state", ["user_id"])
    op.create_index("ix_user_knowledge_state_subject", "user_knowledge_state", ["subject"])
    op.create_index("ix_user_knowledge_state_knowledge_unit_id", "user_knowledge_state", ["knowledge_unit_id"])
    op.create_index("ix_user_knowledge_state_review_status", "user_knowledge_state", ["review_status"])
    op.create_index("ix_user_knowledge_state_scheduled_review_at", "user_knowledge_state", ["scheduled_review_at"])
    op.create_index("ix_user_knowledge_state_source_exam_paper_id", "user_knowledge_state", ["source_exam_paper_id"])
    op.create_index(
        "uq_user_knowledge_state_node",
        "user_knowledge_state",
        ["user_id", "subject", "knowledge_unit_id"],
        unique=True,
        postgresql_where=sa.text("knowledge_unit_id IS NOT NULL"),
    )

    op.create_table(
        "chat_session",
        sa.Column("id", sa.String(), primary_key=True, nullable=False),
        sa.Column("subject", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column("meta_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("last_message_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_chat_session_subject", "chat_session", ["subject"])
    op.create_index("ix_chat_session_user_id", "chat_session", ["user_id"])
    op.create_index("ix_chat_session_source", "chat_session", ["source"])
    op.create_index("ix_chat_session_created_at", "chat_session", ["created_at"])
    op.create_index("ix_chat_session_updated_at", "chat_session", ["updated_at"])
    op.create_index("ix_chat_session_last_message_at", "chat_session", ["last_message_at"])

    op.create_table(
        "chat_message",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("subject", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("session_id", sa.String(), sa.ForeignKey("chat_session.id"), nullable=False),
        sa.Column("turn_id", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column("anchor_id", sa.String(), nullable=True),
        sa.Column("selected_text", sa.String(), nullable=True),
        sa.Column("source_chunk_id", sa.Integer(), sa.ForeignKey("retrieval_chunk.id"), nullable=True),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("content", sa.String(), nullable=False),
        sa.Column("contexts_json", sa.JSON(), nullable=True),
        sa.Column("meta_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_chat_message_subject", "chat_message", ["subject"])
    op.create_index("ix_chat_message_user_id", "chat_message", ["user_id"])
    op.create_index("ix_chat_message_session_id", "chat_message", ["session_id"])
    op.create_index("ix_chat_message_turn_id", "chat_message", ["turn_id"])
    op.create_index("ix_chat_message_source", "chat_message", ["source"])
    op.create_index("ix_chat_message_anchor_id", "chat_message", ["anchor_id"])
    op.create_index("ix_chat_message_source_chunk_id", "chat_message", ["source_chunk_id"])
    op.create_index("ix_chat_message_created_at", "chat_message", ["created_at"])

    op.create_table(
        "system_runtime_settings",
        sa.Column("id", sa.String(), primary_key=True, nullable=False),
        sa.Column("settings_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "system_settings_snapshot",
        sa.Column("id", sa.String(), primary_key=True, nullable=False),
        sa.Column("settings_path", sa.String(), nullable=False),
        sa.Column("settings_hash", sa.String(), nullable=False),
        sa.Column("settings_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_system_settings_snapshot_settings_hash", "system_settings_snapshot", ["settings_hash"])

    op.create_table(
        "user_runtime_settings",
        sa.Column("user_id", sa.String(), sa.ForeignKey("user.id"), primary_key=True, nullable=False),
        sa.Column("settings_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("user_runtime_settings")
    op.drop_table("system_runtime_settings")
    op.drop_index("ix_system_settings_snapshot_settings_hash", table_name="system_settings_snapshot")
    op.drop_table("system_settings_snapshot")
    op.drop_index("ix_chat_message_created_at", table_name="chat_message")
    op.drop_index("ix_chat_message_source_chunk_id", table_name="chat_message")
    op.drop_index("ix_chat_message_anchor_id", table_name="chat_message")
    op.drop_index("ix_chat_message_source", table_name="chat_message")
    op.drop_index("ix_chat_message_turn_id", table_name="chat_message")
    op.drop_index("ix_chat_message_session_id", table_name="chat_message")
    op.drop_index("ix_chat_message_user_id", table_name="chat_message")
    op.drop_index("ix_chat_message_subject", table_name="chat_message")
    op.drop_table("chat_message")
    op.drop_index("ix_chat_session_last_message_at", table_name="chat_session")
    op.drop_index("ix_chat_session_updated_at", table_name="chat_session")
    op.drop_index("ix_chat_session_created_at", table_name="chat_session")
    op.drop_index("ix_chat_session_source", table_name="chat_session")
    op.drop_index("ix_chat_session_user_id", table_name="chat_session")
    op.drop_index("ix_chat_session_subject", table_name="chat_session")
    op.drop_table("chat_session")
    op.drop_index("uq_user_knowledge_state_node", table_name="user_knowledge_state")
    op.drop_index("ix_user_knowledge_state_source_exam_paper_id", table_name="user_knowledge_state")
    op.drop_index("ix_user_knowledge_state_scheduled_review_at", table_name="user_knowledge_state")
    op.drop_index("ix_user_knowledge_state_review_status", table_name="user_knowledge_state")
    op.drop_index("ix_user_knowledge_state_knowledge_unit_id", table_name="user_knowledge_state")
    op.drop_index("ix_user_knowledge_state_subject", table_name="user_knowledge_state")
    op.drop_index("ix_user_knowledge_state_user_id", table_name="user_knowledge_state")
    op.drop_table("user_knowledge_state")
    op.drop_index("ix_exam_paper_item_knowledge_unit_id", table_name="exam_paper_item")
    op.drop_index("ix_exam_paper_item_question_template_id", table_name="exam_paper_item")
    op.drop_index("ix_exam_paper_item_exam_paper_id", table_name="exam_paper_item")
    op.drop_table("exam_paper_item")
    op.drop_index("ix_exam_paper_status", table_name="exam_paper")
    op.drop_index("ix_exam_paper_user_id", table_name="exam_paper")
    op.drop_index("ix_exam_paper_subject", table_name="exam_paper")
    op.drop_table("exam_paper")
    op.drop_index("ix_question_template_stem_hash", table_name="question_template")
    op.drop_index("ix_question_template_knowledge_unit_id", table_name="question_template")
    op.drop_index("ix_question_template_subject", table_name="question_template")
    op.drop_table("question_template")
    op.drop_index("ix_edge_subject_status", table_name="knowledge_edge")
    op.drop_index("ix_knowledge_edge_build_revision_no", table_name="knowledge_edge")
    op.drop_index("ix_knowledge_edge_edge_type", table_name="knowledge_edge")
    op.drop_index("ix_knowledge_edge_target_node_id", table_name="knowledge_edge")
    op.drop_index("ix_knowledge_edge_source_node_id", table_name="knowledge_edge")
    op.drop_index("ix_knowledge_edge_subject", table_name="knowledge_edge")
    op.drop_table("knowledge_edge")
    op.drop_index("ix_retrieval_chunk_is_active", table_name="retrieval_chunk")
    op.drop_index("ix_retrieval_chunk_build_session_id", table_name="retrieval_chunk")
    op.drop_index("ix_retrieval_chunk_digest_chunk_uid", table_name="retrieval_chunk")
    op.drop_index("ix_retrieval_chunk_document_id", table_name="retrieval_chunk")
    op.drop_index("ix_retrieval_chunk_subject", table_name="retrieval_chunk")
    op.drop_table("retrieval_chunk")
    op.drop_index("ix_unit_subject_status", table_name="knowledge_unit")
    op.drop_index("ix_knowledge_unit_build_revision_no", table_name="knowledge_unit")
    op.drop_index("ix_knowledge_unit_type_source", table_name="knowledge_unit")
    op.drop_index("ix_knowledge_unit_normalized_name", table_name="knowledge_unit")
    op.drop_index("ix_knowledge_unit_knowledge_unit_type", table_name="knowledge_unit")
    op.drop_index("ix_knowledge_unit_subject", table_name="knowledge_unit")
    op.drop_table("knowledge_unit")
    op.drop_index("ix_knowledge_document_status", table_name="knowledge_document")
    op.drop_index("ix_knowledge_document_is_current", table_name="knowledge_document")
    op.drop_index("ix_knowledge_document_digest_mode", table_name="knowledge_document")
    op.drop_index("ix_knowledge_document_document_role", table_name="knowledge_document")
    op.drop_index("ix_knowledge_document_build_session_id", table_name="knowledge_document")
    op.drop_index("ix_knowledge_document_package_key", table_name="knowledge_document")
    op.drop_index("ix_knowledge_document_parent_document_id", table_name="knowledge_document")
    op.drop_index("ix_knowledge_document_root_document_id", table_name="knowledge_document")
    op.drop_index("ix_knowledge_document_subject", table_name="knowledge_document")
    op.drop_table("knowledge_document")
    op.drop_index("ix_confirmed_build_plan_updated_at", table_name="confirmed_build_plan")
    op.drop_index("ix_confirmed_build_plan_created_at", table_name="confirmed_build_plan")
    op.drop_index("ix_confirmed_build_plan_digest_mode", table_name="confirmed_build_plan")
    op.drop_index("ix_confirmed_build_plan_status", table_name="confirmed_build_plan")
    op.drop_index("ix_confirmed_build_plan_user_id", table_name="confirmed_build_plan")
    op.drop_index("ix_confirmed_build_plan_planner_session_id", table_name="confirmed_build_plan")
    op.drop_index("ix_confirmed_build_plan_subject", table_name="confirmed_build_plan")
    op.drop_table("confirmed_build_plan")
    op.drop_index("ix_raw_file_current_step", table_name="raw_file")
    op.drop_index("ix_raw_file_ingest_status", table_name="raw_file")
    op.drop_index("ix_raw_file_detected_discipline", table_name="raw_file")
    op.drop_index("ix_raw_file_status", table_name="raw_file")
    op.drop_index("ix_raw_file_subject", table_name="raw_file")
    op.drop_index("ix_raw_file_uid", table_name="raw_file")
    op.drop_table("raw_file")
    op.drop_index("ix_subject_status", table_name="subject")
    op.drop_index("ix_subject_normalized_name", table_name="subject")
    op.drop_index("ix_subject_slug", table_name="subject")
    op.drop_index("ix_subject_user_id", table_name="subject")
    op.drop_table("subject")
    op.drop_index("ix_email_verification_code_created_at", table_name="email_verification_code")
    op.drop_index("ix_email_verification_code_consumed_at", table_name="email_verification_code")
    op.drop_index("ix_email_verification_code_expires_at", table_name="email_verification_code")
    op.drop_index("ix_email_verification_code_code_hash", table_name="email_verification_code")
    op.drop_index("ix_email_verification_code_purpose", table_name="email_verification_code")
    op.drop_index("ix_email_verification_code_email", table_name="email_verification_code")
    op.drop_table("email_verification_code")
    op.drop_index("ix_user_is_registered", table_name="user")
    op.drop_index("ix_user_device_key", table_name="user")
    op.drop_index("ix_user_email", table_name="user")
    op.drop_index("ix_user_username", table_name="user")
    op.drop_table("user")
