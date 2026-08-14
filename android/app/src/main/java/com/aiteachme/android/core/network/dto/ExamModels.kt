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
    @SerializedName("submission_key")
    val submissionKey: String? = null,
)

data class ExamProfileSyncResponse(
    @SerializedName("exam_paper_id")
    val examPaperId: Int = 0,
    val status: String = "not_tracked",
    @SerializedName("attempt_count")
    val attemptCount: Int = 0,
    @SerializedName("manual_retry_count")
    val manualRetryCount: Int = 0,
    @SerializedName("next_attempt_at")
    val nextAttemptAt: String? = null,
    @SerializedName("last_error_code")
    val lastErrorCode: String? = null,
    @SerializedName("states_updated")
    val statesUpdated: Int = 0,
    @SerializedName("review_task_count")
    val reviewTaskCount: Int = 0,
    @SerializedName("can_retry")
    val canRetry: Boolean = false,
    @SerializedName("updated_at")
    val updatedAt: String? = null,
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
    @SerializedName("profile_sync")
    val profileSync: ExamProfileSyncResponse? = null,
)

data class ExamStudyGuideFocusUnit(
    @SerializedName("knowledge_unit_id")
    val knowledgeUnitId: Int? = null,
    @SerializedName("knowledge_unit_name")
    val knowledgeUnitName: String = "",
    @SerializedName("mastery_score")
    val masteryScore: Double? = null,
    val reason: String = "",
)

data class ExamStudyGuideResponse(
    @SerializedName("exam_paper_id")
    val examPaperId: Int = 0,
    @SerializedName("course_name")
    val courseName: String = "",
    @SerializedName("generated_at")
    val generatedAt: String = "",
    @SerializedName("overall_summary")
    val overallSummary: String = "",
    val strengths: List<String> = emptyList(),
    @SerializedName("priority_gaps")
    val priorityGaps: List<String> = emptyList(),
    @SerializedName("action_steps")
    val actionSteps: List<String> = emptyList(),
    @SerializedName("review_tasks")
    val reviewTasks: List<String> = emptyList(),
    @SerializedName("focus_units")
    val focusUnits: List<ExamStudyGuideFocusUnit> = emptyList(),
)

data class QuestionTemplateItemResponse(
    val id: Int = 0,
    @SerializedName("course_id")
    val courseId: String = "",
    @SerializedName("question_type")
    val questionType: String = "",
    val difficulty: String = "",
    val stem: String = "",
    val options: List<String>? = null,
    val answer: String = "",
    val explanation: String = "",
    @SerializedName("knowledge_unit_refs")
    val knowledgeUnitRefs: List<Map<String, Any?>> = emptyList(),
    @SerializedName("selection_hints")
    val selectionHints: Map<String, Any?> = emptyMap(),
    @SerializedName("template_version")
    val templateVersion: Int = 0,
    val status: String = "",
    @SerializedName("is_marked")
    val isMarked: Boolean = false,
    @SerializedName("has_wrong_attempt")
    val hasWrongAttempt: Boolean = false,
    @SerializedName("created_at")
    val createdAt: String = "",
    @SerializedName("updated_at")
    val updatedAt: String = "",
)

data class QuestionTemplateAnswerHistoryItem(
    @SerializedName("exam_paper_id")
    val examPaperId: Int = 0,
    @SerializedName("exam_paper_item_id")
    val examPaperItemId: Int = 0,
    @SerializedName("item_order")
    val itemOrder: Int = 0,
    @SerializedName("exam_mode")
    val examMode: String = "",
    @SerializedName("exam_status")
    val examStatus: String = "",
    @SerializedName("submitted_at")
    val submittedAt: String? = null,
    @SerializedName("graded_at")
    val gradedAt: String? = null,
    @SerializedName("answered_at")
    val answeredAt: String? = null,
    @SerializedName("user_answer")
    val userAnswer: String = "",
    @SerializedName("correct_answer")
    val correctAnswer: String = "",
    @SerializedName("is_correct")
    val isCorrect: Boolean? = null,
    @SerializedName("score_obtained")
    val scoreObtained: Double? = null,
    @SerializedName("score_max")
    val scoreMax: Double? = null,
    @SerializedName("error_cause_label")
    val errorCauseLabel: String? = null,
    @SerializedName("feedback_text")
    val feedbackText: String? = null,
    @SerializedName("created_at")
    val createdAt: String = "",
)

data class QuestionTemplateMarkRequest(
    @SerializedName("is_marked")
    val isMarked: Boolean,
)

data class QuestionTemplateMarkResponse(
    @SerializedName("question_template_id")
    val questionTemplateId: Int = 0,
    @SerializedName("is_marked")
    val isMarked: Boolean = false,
)

data class QuestionTemplateGradeRequest(
    val answer: String,
)

data class QuestionTemplateGradeResponse(
    @SerializedName("question_template_id")
    val questionTemplateId: Int = 0,
    @SerializedName("question_type")
    val questionType: String = "",
    @SerializedName("is_correct")
    val isCorrect: Boolean = false,
    @SerializedName("score_obtained")
    val scoreObtained: Double = 0.0,
    @SerializedName("score_max")
    val scoreMax: Double = 1.0,
    @SerializedName("feedback_text")
    val feedbackText: String = "",
    @SerializedName("error_cause_label")
    val errorCauseLabel: String? = null,
    @SerializedName("grading_mode")
    val gradingMode: String = "",
    @SerializedName("correct_answer")
    val correctAnswer: String = "",
)

data class MasteryDrillStartRequest(
    @SerializedName("session_key")
    val sessionKey: String,
    @SerializedName("question_template_ids")
    val questionTemplateIds: List<Int>,
    @SerializedName("configured_question_count")
    val configuredQuestionCount: Int,
    @SerializedName("configured_question_types")
    val configuredQuestionTypes: List<String> = emptyList(),
)

data class MasteryDrillAttemptRequest(
    @SerializedName("exam_paper_item_id")
    val examPaperItemId: Int,
    val answer: String,
    @SerializedName("attempt_key")
    val attemptKey: String,
    @SerializedName("time_spent_seconds")
    val timeSpentSeconds: Int? = null,
    @SerializedName("hint_used")
    val hintUsed: Boolean = false,
    @SerializedName("confidence_self_report")
    val confidenceSelfReport: Int? = null,
)

data class MasteryDrillCompleteRequest(
    @SerializedName("completion_key")
    val completionKey: String,
    @SerializedName("duration_seconds")
    val durationSeconds: Int? = null,
)

data class MasteryDrillAttemptResponse(
    val id: Int = 0,
    @SerializedName("mastery_drill_session_id")
    val masteryDrillSessionId: Int = 0,
    @SerializedName("exam_paper_item_id")
    val examPaperItemId: Int = 0,
    @SerializedName("question_template_id")
    val questionTemplateId: Int = 0,
    @SerializedName("attempt_no")
    val attemptNo: Int = 1,
    @SerializedName("attempt_key")
    val attemptKey: String = "",
    val status: String = "",
    val answer: String = "",
    @SerializedName("is_correct")
    val isCorrect: Boolean? = null,
    @SerializedName("score_obtained")
    val scoreObtained: Double? = null,
    @SerializedName("score_max")
    val scoreMax: Double? = null,
    @SerializedName("feedback_text")
    val feedbackText: String? = null,
    @SerializedName("error_cause_label")
    val errorCauseLabel: String? = null,
    @SerializedName("grading_mode")
    val gradingMode: String? = null,
    @SerializedName("time_spent_seconds")
    val timeSpentSeconds: Int? = null,
    @SerializedName("hint_used")
    val hintUsed: Boolean = false,
    @SerializedName("confidence_self_report")
    val confidenceSelfReport: Int? = null,
    @SerializedName("error_code")
    val errorCode: String? = null,
    @SerializedName("answered_at")
    val answeredAt: String? = null,
    @SerializedName("created_at")
    val createdAt: String = "",
    @SerializedName("updated_at")
    val updatedAt: String = "",
)

data class MasteryDrillSessionResponse(
    val id: Int = 0,
    @SerializedName("exam_paper_id")
    val examPaperId: Int = 0,
    val status: String = "",
    @SerializedName("config_snapshot")
    val configSnapshot: Map<String, Any?> = emptyMap(),
    @SerializedName("total_attempts")
    val totalAttempts: Int = 0,
    @SerializedName("wrong_attempts")
    val wrongAttempts: Int = 0,
    @SerializedName("started_at")
    val startedAt: String = "",
    @SerializedName("completed_at")
    val completedAt: String? = null,
    val attempts: List<MasteryDrillAttemptResponse> = emptyList(),
)

data class MasteryDrillHistorySummary(
    val status: String = "",
    @SerializedName("total_attempts")
    val totalAttempts: Int = 0,
    @SerializedName("wrong_attempts")
    val wrongAttempts: Int = 0,
    @SerializedName("attempt_accuracy")
    val attemptAccuracy: Double? = null,
)

data class QuestionTypeRegistryItemResponse(
    val id: Int = 0,
    @SerializedName("type_key")
    val typeKey: String = "",
    @SerializedName("display_name")
    val displayName: String = "",
    val scope: String = "",
    @SerializedName("course_id")
    val courseId: String = "",
    val description: String = "",
    @SerializedName("answer_format")
    val answerFormat: String = "",
    @SerializedName("grading_method")
    val gradingMethod: String = "",
    @SerializedName("option_schema")
    val optionSchema: Map<String, Any?> = emptyMap(),
    val rubric: Map<String, Any?> = emptyMap(),
    val source: String = "",
    val confidence: Double = 0.0,
    @SerializedName("is_system")
    val isSystem: Boolean = false,
    @SerializedName("is_active")
    val isActive: Boolean = false,
    @SerializedName("created_at")
    val createdAt: String = "",
    @SerializedName("updated_at")
    val updatedAt: String = "",
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
    @SerializedName("mastery_drill")
    val masteryDrill: MasteryDrillHistorySummary? = null,
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
    @SerializedName("profile_sync")
    val profileSync: ExamProfileSyncResponse? = null,
    @SerializedName("mastery_drill")
    val masteryDrill: MasteryDrillSessionResponse? = null,
    @SerializedName("paper_preview")
    val paperPreview: PaperPreview = PaperPreview(),
    val items: List<ExamPaperItemResponse> = emptyList(),
)
