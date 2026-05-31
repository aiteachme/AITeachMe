package com.aiteachme.android.core.network.dto

import com.google.gson.annotations.SerializedName

data class DocGenBuildRequest(
    @SerializedName("file_ids")
    val fileIds: List<String>? = null,
    val prompt: String? = null,
    @SerializedName("build_type")
    val buildType: String = "docs",
    @SerializedName("confirmed_plan_id")
    val confirmedPlanId: String? = null,
)

data class DocGenBuildData(
    @SerializedName("accepted_file_ids")
    val acceptedFileIds: List<String> = emptyList(),
    val prompt: String? = null,
    @SerializedName("ready_file_count")
    val readyFileCount: Int = 0,
    @SerializedName("requested_at")
    val requestedAt: String = "",
    @SerializedName("planner_session_id")
    val plannerSessionId: String? = null,
    @SerializedName("confirmed_plan_id")
    val confirmedPlanId: String? = null,
    @SerializedName("digest_mode")
    val digestMode: String? = null,
)

data class KnowledgeBuildStatusResponse(
    val status: String = "",
    @SerializedName("requested_at")
    val requestedAt: String = "",
    val stage: String = "",
    @SerializedName("error_message")
    val errorMessage: String? = null,
    @SerializedName("draft_available")
    val draftAvailable: Boolean = false,
    @SerializedName("progress_pct")
    val progressPct: Int? = null,
    @SerializedName("planner_session_id")
    val plannerSessionId: String? = null,
    @SerializedName("confirmed_plan_id")
    val confirmedPlanId: String? = null,
    @SerializedName("digest_mode")
    val digestMode: String? = null,
    @SerializedName("mode_reason")
    val modeReason: String? = null,
    @SerializedName("current_stage_description")
    val currentStageDescription: String? = null,
)

data class KnowledgeBuildPreviewResponse(
    @SerializedName("stage_description")
    val stageDescription: String? = null,
    @SerializedName("progress_pct")
    val progressPct: Int? = null,
    @SerializedName("plan_summary")
    val planSummary: String? = null,
)

data class DocGenGetResponse(
    val exists: Boolean = false,
    val markdown: String = "",
    @SerializedName("updated_at")
    val updatedAt: String? = null,
    @SerializedName("source_file_ids")
    val sourceFileIds: List<String> = emptyList(),
    val prompt: String? = null,
    @SerializedName("draft_markdown")
    val draftMarkdown: String = "",
    @SerializedName("draft_updated_at")
    val draftUpdatedAt: String? = null,
    val build: KnowledgeBuildStatusResponse? = null,
    @SerializedName("build_preview")
    val buildPreview: KnowledgeBuildPreviewResponse? = null,
    @SerializedName("planner_session_id")
    val plannerSessionId: String? = null,
    @SerializedName("confirmed_plan_id")
    val confirmedPlanId: String? = null,
    @SerializedName("digest_mode")
    val digestMode: String? = null,
)
