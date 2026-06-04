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

data class KnowledgeUnitResponse(
    val id: Int = 0,
    @SerializedName("course_id")
    val courseId: String = "",
    @SerializedName("knowledge_unit_type")
    val knowledgeUnitType: String = "",
    @SerializedName("canonical_name")
    val canonicalName: String = "",
    val status: String = "",
    val confidence: Double = 0.0,
    @SerializedName("type_confidence")
    val typeConfidence: Double = 1.0,
    @SerializedName("type_source")
    val typeSource: String = "",
    @SerializedName("created_at")
    val createdAt: String = "",
    @SerializedName("updated_at")
    val updatedAt: String = "",
)

data class GraphEdgeResponse(
    val id: Int = 0,
    @SerializedName("source_node_id")
    val sourceNodeId: Int = 0,
    @SerializedName("target_node_id")
    val targetNodeId: Int = 0,
    @SerializedName("edge_type")
    val edgeType: String = "",
    val weight: Double = 0.0,
    val confidence: Double = 0.0,
)

data class FullGraphResponse(
    val nodes: List<KnowledgeUnitResponse> = emptyList(),
    val edges: List<GraphEdgeResponse> = emptyList(),
)

data class KnowledgeOverviewRequest(
    val include: List<String>? = null,
)

data class KnowledgeOverviewStats(
    @SerializedName("node_count")
    val nodeCount: Int = 0,
    @SerializedName("edge_count")
    val edgeCount: Int = 0,
    @SerializedName("document_count")
    val documentCount: Int = 0,
    @SerializedName("chunk_count")
    val chunkCount: Int = 0,
)

data class KnowledgeOverviewResponse(
    @SerializedName("course_id")
    val courseId: String = "",
    @SerializedName("generated_at")
    val generatedAt: String = "",
    val graph: FullGraphResponse? = null,
    val stats: KnowledgeOverviewStats? = null,
    @SerializedName("planner_session_id")
    val plannerSessionId: String? = null,
    @SerializedName("confirmed_plan_id")
    val confirmedPlanId: String? = null,
    @SerializedName("digest_mode")
    val digestMode: String? = null,
)

data class KnowledgeUnitsQueryRequest(
    val page: Int = 1,
    val size: Int = 50,
    val keyword: String? = null,
    @SerializedName("knowledge_unit_type")
    val knowledgeUnitType: String? = null,
)

data class KnowledgeUnitDetailRequest(
    @SerializedName("knowledge_unit_id")
    val knowledgeUnitId: Int,
)

data class KnowledgeUnitRelationsRequest(
    @SerializedName("knowledge_unit_id")
    val knowledgeUnitId: Int,
    val direction: String = "both",
)

data class KnowledgeUnitPathRequest(
    @SerializedName("source_knowledge_unit_id")
    val sourceKnowledgeUnitId: Int,
    @SerializedName("target_knowledge_unit_id")
    val targetKnowledgeUnitId: Int,
)

data class KnowledgeSubgraphRequest(
    @SerializedName("center_knowledge_unit_id")
    val centerKnowledgeUnitId: Int? = null,
    val depth: Int = 1,
    val limit: Int = 40,
)

data class KnowledgeRelationExplanationRequest(
    @SerializedName("source_knowledge_unit_id")
    val sourceKnowledgeUnitId: Int,
    @SerializedName("target_knowledge_unit_id")
    val targetKnowledgeUnitId: Int,
)

data class KnowledgeGraphSourceRefResponse(
    val id: Int = 0,
    @SerializedName("entity_type")
    val entityType: String = "",
    @SerializedName("entity_id")
    val entityId: Int = 0,
    @SerializedName("knowledge_document_id")
    val knowledgeDocumentId: Int? = null,
    @SerializedName("chapter_index")
    val chapterIndex: Int? = null,
    @SerializedName("chapter_title")
    val chapterTitle: String? = null,
    @SerializedName("source_kind")
    val sourceKind: String = "",
    val anchor: String = "",
    @SerializedName("source_file_ids")
    val sourceFileIds: List<String> = emptyList(),
    @SerializedName("quote_text")
    val quoteText: String = "",
    val confidence: Double = 0.0,
    @SerializedName("created_at")
    val createdAt: String = "",
)

data class NodeRevisionItem(
    val title: String = "",
    val summary: String = "",
    val body: String = "",
)

data class AliasItem(
    val id: Int = 0,
    val alias: String = "",
    val language: String = "",
    val source: String = "",
    val confidence: Double = 0.0,
    @SerializedName("is_primary")
    val isPrimary: Boolean = false,
)

data class EvidenceSummary(
    val id: Int = 0,
    @SerializedName("file_id")
    val fileId: String = "",
    @SerializedName("chunk_id")
    val chunkId: Int = 0,
    @SerializedName("quote_text")
    val quoteText: String = "",
    @SerializedName("evidence_role")
    val evidenceRole: String = "",
    @SerializedName("field_scope")
    val fieldScope: String = "",
    val confidence: Double = 0.0,
)

data class IncidentEdgeItem(
    val id: Int = 0,
    @SerializedName("edge_type")
    val edgeType: String = "",
    val direction: String = "",
    @SerializedName("other_node_id")
    val otherNodeId: Int = 0,
    @SerializedName("other_node_name")
    val otherNodeName: String = "",
    @SerializedName("other_node_type")
    val otherNodeType: String = "",
    val confidence: Double = 0.0,
)

data class KnowledgeUnitDetailResponse(
    val id: Int = 0,
    @SerializedName("course_id")
    val courseId: String = "",
    @SerializedName("knowledge_unit_type")
    val knowledgeUnitType: String = "",
    @SerializedName("canonical_name")
    val canonicalName: String = "",
    @SerializedName("normalized_name")
    val normalizedName: String = "",
    val status: String = "",
    val confidence: Double = 0.0,
    @SerializedName("type_confidence")
    val typeConfidence: Double = 1.0,
    @SerializedName("type_source")
    val typeSource: String = "",
    @SerializedName("current_revision")
    val currentRevision: NodeRevisionItem? = null,
    val aliases: List<AliasItem> = emptyList(),
    val evidence: List<EvidenceSummary> = emptyList(),
    @SerializedName("source_refs")
    val sourceRefs: List<KnowledgeGraphSourceRefResponse> = emptyList(),
    @SerializedName("incident_edges")
    val incidentEdges: List<IncidentEdgeItem> = emptyList(),
    @SerializedName("created_at")
    val createdAt: String = "",
    @SerializedName("updated_at")
    val updatedAt: String = "",
)

data class KnowledgeRelationResponse(
    val id: Int = 0,
    @SerializedName("course_id")
    val courseId: String = "",
    @SerializedName("source_node_id")
    val sourceNodeId: Int = 0,
    @SerializedName("source_node_name")
    val sourceNodeName: String = "",
    @SerializedName("source_node_type")
    val sourceNodeType: String = "",
    @SerializedName("target_node_id")
    val targetNodeId: Int = 0,
    @SerializedName("target_node_name")
    val targetNodeName: String = "",
    @SerializedName("target_node_type")
    val targetNodeType: String = "",
    @SerializedName("edge_type")
    val edgeType: String = "",
    val description: String = "",
    val weight: Double = 0.0,
    val confidence: Double = 0.0,
)

data class KnowledgeSubgraphResponse(
    val nodes: List<KnowledgeUnitResponse> = emptyList(),
    val edges: List<KnowledgeRelationResponse> = emptyList(),
    @SerializedName("center_knowledge_unit_id")
    val centerKnowledgeUnitId: Int? = null,
)

data class KnowledgePathResponse(
    val nodes: List<KnowledgeUnitResponse> = emptyList(),
    val edges: List<KnowledgeRelationResponse> = emptyList(),
)

data class KnowledgeRelationEvidenceItem(
    val title: String = "",
    @SerializedName("quote_text")
    val quoteText: String = "",
    val confidence: Double = 0.0,
)

data class KnowledgeRelationExplanationResponse(
    val path: KnowledgePathResponse = KnowledgePathResponse(),
    val evidence: List<KnowledgeRelationEvidenceItem> = emptyList(),
    val explanation: String = "",
)

data class ClearKnowledgeResponse(
    @SerializedName("deleted_counts")
    val deletedCounts: Map<String, Int> = emptyMap(),
)

data class KnowledgeGraphBuildData(
    @SerializedName("course_id")
    val courseId: String = "",
    val status: String = "",
    @SerializedName("requested_at")
    val requestedAt: String = "",
)
