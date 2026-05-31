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

data class BuildPlannerCreateRequest(
    @SerializedName("file_ids")
    val fileIds: List<String>? = null,
    @SerializedName("user_prompt")
    val userPrompt: String,
    @SerializedName("digest_mode")
    val digestMode: String? = null,
    val title: String? = null,
    val model: String? = null,
)

data class BuildPlannerChapterPlanResponse(
    @SerializedName("chapter_index")
    val chapterIndex: Int = 0,
    val title: String = "",
    val objective: String = "",
    @SerializedName("required_elements")
    val requiredElements: List<String> = emptyList(),
    @SerializedName("writing_instructions")
    val writingInstructions: String = "",
)

data class BuildPlannerPlanResponse(
    @SerializedName("course_id")
    val courseId: String = "",
    @SerializedName("selected_file_ids")
    val selectedFileIds: List<String> = emptyList(),
    @SerializedName("user_prompt")
    val userPrompt: String = "",
    @SerializedName("digest_mode")
    val digestMode: String = "",
    @SerializedName("chapter_plan")
    val chapterPlan: List<BuildPlannerChapterPlanResponse> = emptyList(),
    @SerializedName("plan_summary")
    val planSummary: String = "",
    @SerializedName("plan_steps")
    val planSteps: List<String> = emptyList(),
    @SerializedName("adjustment_questions")
    val adjustmentQuestions: List<String> = emptyList(),
    val status: String = "",
    @SerializedName("planner_session_id")
    val plannerSessionId: String? = null,
    @SerializedName("confirmed_plan_id")
    val confirmedPlanId: String? = null,
    @SerializedName("model_override")
    val modelOverride: String? = null,
)

data class BuildPlannerTurnResponse(
    val id: Int? = null,
    val role: String = "",
    val content: String = "",
    @SerializedName("created_at")
    val createdAt: String = "",
)

data class BuildPlannerStepStatsResponse(
    val name: String = "",
    val status: String = "",
    @SerializedName("elapsed_ms")
    val elapsedMs: Int = 0,
)

data class BuildPlannerRuntimeStatsResponse(
    @SerializedName("elapsed_ms")
    val elapsedMs: Int = 0,
    val steps: List<BuildPlannerStepStatsResponse> = emptyList(),
)

data class BuildPlannerSessionResponse(
    @SerializedName("session_id")
    val sessionId: String = "",
    @SerializedName("course_id")
    val courseId: String = "",
    val title: String = "",
    val status: String = "",
    val revision: Int = 0,
    @SerializedName("latest_plan")
    val latestPlan: BuildPlannerPlanResponse? = null,
    @SerializedName("model_override")
    val modelOverride: String? = null,
    val turns: List<BuildPlannerTurnResponse> = emptyList(),
    @SerializedName("runtime_stats")
    val runtimeStats: BuildPlannerRuntimeStatsResponse? = null,
    @SerializedName("created_at")
    val createdAt: String = "",
    @SerializedName("updated_at")
    val updatedAt: String = "",
)

data class BuildPlannerStatusData(
    val stage: String? = null,
    val step: String? = null,
    val event: String? = null,
    val detail: String? = null,
    @SerializedName("elapsed_ms")
    val elapsedMs: Int? = null,
    @SerializedName("plan_preview")
    val planPreview: BuildPlannerPlanResponse? = null,
)

data class BuildPlannerDoneData(
    val session: BuildPlannerSessionResponse? = null,
)

data class BuildPlannerConfirmResponse(
    @SerializedName("planner_session_id")
    val plannerSessionId: String = "",
    @SerializedName("confirmed_plan_id")
    val confirmedPlanId: String = "",
    @SerializedName("version_no")
    val versionNo: Int = 1,
    @SerializedName("course_id")
    val courseId: String = "",
    val status: String = "",
    @SerializedName("digest_mode")
    val digestMode: String = "",
    @SerializedName("model_override")
    val modelOverride: String? = null,
    @SerializedName("selected_file_ids")
    val selectedFileIds: List<String> = emptyList(),
    @SerializedName("user_prompt")
    val userPrompt: String = "",
    @SerializedName("plan_summary")
    val planSummary: String = "",
    @SerializedName("chapter_plan")
    val chapterPlan: List<BuildPlannerChapterPlanResponse> = emptyList(),
    @SerializedName("created_at")
    val createdAt: String = "",
    @SerializedName("updated_at")
    val updatedAt: String = "",
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
