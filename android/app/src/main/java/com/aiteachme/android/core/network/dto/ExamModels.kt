package com.aiteachme.android.core.network.dto

import com.google.gson.annotations.SerializedName

data class ExamGenerateRequest(
    @SerializedName("exam_mode")
    val examMode: String,
    @SerializedName("user_prompt")
    val userPrompt: String? = null,
    @SerializedName("sample_file_ids")
    val sampleFileIds: List<String>? = null,
    @SerializedName("num_questions")
    val numQuestions: Int? = null,
    @SerializedName("paper_layout_mode")
    val paperLayoutMode: String? = null,
)

data class ExamGenerateResponse(
    val id: Int = 0,
    val status: String = "",
    @SerializedName("error_message")
    val errorMessage: String? = null,
    @SerializedName("created_at")
    val createdAt: String = "",
    @SerializedName("updated_at")
    val updatedAt: String = "",
    @SerializedName("course_id")
    val courseId: String = "",
    @SerializedName("user_id")
    val userId: String = "",
    @SerializedName("exam_mode")
    val examMode: String = "",
    @SerializedName("num_questions")
    val numQuestions: Int = 0,
    @SerializedName("exam_paper_id")
    val examPaperId: Int? = null,
    @SerializedName("sample_file_ids")
    val sampleFileIds: List<String> = emptyList(),
)

data class ExamSubmitAnswerItem(
    @SerializedName("exam_paper_item_id")
    val examPaperItemId: Int? = null,
    @SerializedName("item_order")
    val itemOrder: Int? = null,
    val answer: String,
)

data class ExamSubmitRequest(
    val answers: List<ExamSubmitAnswerItem> = emptyList(),
)

data class ExamGradeResponse(
    val id: Int = 0,
    val status: String = "",
    @SerializedName("error_message")
    val errorMessage: String? = null,
    @SerializedName("created_at")
    val createdAt: String = "",
    @SerializedName("updated_at")
    val updatedAt: String = "",
    @SerializedName("exam_paper_id")
    val examPaperId: Int = 0,
    val score: Double? = null,
    @SerializedName("states_updated")
    val statesUpdated: Int = 0,
    @SerializedName("tasks_created")
    val tasksCreated: Int = 0,
    @SerializedName("mastery_consumed")
    val masteryConsumed: Boolean = false,
)

data class PaperPreviewRow(
    val order: Int = 0,
    val type: String = "",
    val shape: String = "",
    val difficulty: String = "",
    val density: Int = 2,
    @SerializedName("result_status")
    val resultStatus: String = "ungraded",
    @SerializedName("generation_status")
    val generationStatus: String = "generated",
)

data class PaperPreview(
    val keywords: List<String> = emptyList(),
    @SerializedName("question_types")
    val questionTypes: List<String> = emptyList(),
    val rows: List<PaperPreviewRow> = emptyList(),
    @SerializedName("overflow_count")
    val overflowCount: Int = 0,
)

data class ExamHistoryItem(
    val id: Int = 0,
    @SerializedName("course_id")
    val courseId: String = "",
    @SerializedName("user_id")
    val userId: String = "",
    @SerializedName("exam_mode")
    val examMode: String = "",
    val status: String = "",
    @SerializedName("total_items")
    val totalItems: Int = 0,
    @SerializedName("score_obtained")
    val scoreObtained: Double? = null,
    @SerializedName("total_score")
    val totalScore: Double? = null,
    @SerializedName("created_at")
    val createdAt: String = "",
    @SerializedName("submitted_at")
    val submittedAt: String? = null,
    @SerializedName("graded_at")
    val gradedAt: String? = null,
    @SerializedName("paper_preview")
    val paperPreview: PaperPreview = PaperPreview(),
)

data class ExamNodeLinkResponse(
    @SerializedName("knowledge_unit_id")
    val knowledgeUnitId: Int = 0,
    @SerializedName("knowledge_unit_name")
    val knowledgeUnitName: String = "",
    @SerializedName("coverage_weight")
    val coverageWeight: Double = 0.0,
    @SerializedName("mastery_score")
    val masteryScore: Double? = null,
)

data class ExamPaperItemResponse(
    val id: Int = 0,
    @SerializedName("item_order")
    val itemOrder: Int = 0,
    @SerializedName("question_template_id")
    val questionTemplateId: Int = 0,
    @SerializedName("question_type")
    val questionType: String = "",
    val difficulty: String = "",
    val stem: String = "",
    val options: List<String>? = null,
    @SerializedName("correct_answer")
    val correctAnswer: String? = null,
    val explanation: String = "",
    @SerializedName("knowledge_unit_links")
    val knowledgeUnitLinks: List<ExamNodeLinkResponse> = emptyList(),
    @SerializedName("selection_context")
    val selectionContext: Map<String, Any?> = emptyMap(),
    @SerializedName("user_answer")
    val userAnswer: String? = null,
    @SerializedName("is_correct")
    val isCorrect: Boolean? = null,
    @SerializedName("score_obtained")
    val scoreObtained: Double? = null,
    @SerializedName("score_max")
    val scoreMax: Double? = null,
    @SerializedName("error_cause_label")
    val errorCauseLabel: String? = null,
    @SerializedName("is_marked")
    val isMarked: Boolean = false,
)

data class ExamPaperDetailResponse(
    val id: Int = 0,
    @SerializedName("course_id")
    val courseId: String = "",
    @SerializedName("user_id")
    val userId: String = "",
    @SerializedName("exam_mode")
    val examMode: String = "",
    val status: String = "",
    @SerializedName("total_items")
    val totalItems: Int = 0,
    @SerializedName("score_obtained")
    val scoreObtained: Double? = null,
    @SerializedName("total_score")
    val totalScore: Double? = null,
    @SerializedName("submitted_at")
    val submittedAt: String? = null,
    @SerializedName("graded_at")
    val gradedAt: String? = null,
    @SerializedName("created_at")
    val createdAt: String = "",
    @SerializedName("selection_context")
    val selectionContext: Map<String, Any?> = emptyMap(),
    @SerializedName("paper_preview")
    val paperPreview: PaperPreview = PaperPreview(),
    val items: List<ExamPaperItemResponse> = emptyList(),
)
