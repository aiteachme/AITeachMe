package com.aiteachme.android.core.network.dto

import com.google.gson.annotations.SerializedName

data class MasteryOverviewResponse(
    @SerializedName("course_id")
    val courseId: String = "",
    @SerializedName("user_id")
    val userId: String = "",
    @SerializedName("weak_knowledge_unit_count")
    val weakKnowledgeUnitCount: Int = 0,
    @SerializedName("knowledge_unit_states")
    val knowledgeUnitStates: List<MasteryStateResponse> = emptyList(),
    @SerializedName("course_profile")
    val courseProfile: CourseProfileSummary? = null,
    @SerializedName("user_profile")
    val userProfile: UserProfileSummary? = null,
)

data class MasteryStateResponse(
    val id: Int = 0,
    @SerializedName("knowledge_unit_id")
    val knowledgeUnitId: Int = 0,
    @SerializedName("knowledge_unit_name")
    val knowledgeUnitName: String? = null,
    @SerializedName("knowledge_unit_type")
    val knowledgeUnitType: String? = null,
    @SerializedName("mastery_score")
    val masteryScore: Double = 0.0,
    @SerializedName("confidence_score")
    val confidenceScore: Double = 0.0,
    @SerializedName("stability_score")
    val stabilityScore: Double = 0.0,
    @SerializedName("forgetting_due_at")
    val forgettingDueAt: String? = null,
    @SerializedName("review_priority")
    val reviewPriority: Double = 0.0,
    @SerializedName("total_attempts")
    val totalAttempts: Int = 0,
    @SerializedName("correct_attempts")
    val correctAttempts: Int = 0,
    @SerializedName("last_attempt_at")
    val lastAttemptAt: String? = null,
    @SerializedName("state_version")
    val stateVersion: Int = 0,
    @SerializedName("updated_at")
    val updatedAt: String = "",
)

data class CourseProfileSummary(
    @SerializedName("course_id")
    val courseId: String = "",
    @SerializedName("generated_at")
    val generatedAt: String = "",
    @SerializedName("avg_mastery")
    val avgMastery: Double? = null,
    @SerializedName("weak_knowledge_unit_count")
    val weakKnowledgeUnitCount: Int = 0,
    @SerializedName("pending_review_count")
    val pendingReviewCount: Int = 0,
    @SerializedName("due_review_count")
    val dueReviewCount: Int = 0,
    @SerializedName("preferred_question_types")
    val preferredQuestionTypes: List<String> = emptyList(),
    @SerializedName("recommended_question_types")
    val recommendedQuestionTypes: List<String> = emptyList(),
    @SerializedName("recommended_exam_mode")
    val recommendedExamMode: String = "",
    @SerializedName("recommended_question_count")
    val recommendedQuestionCount: Int? = null,
    @SerializedName("difficulty_focus")
    val difficultyFocus: String = "",
    @SerializedName("focus_knowledge_unit_ids")
    val focusKnowledgeUnitIds: List<Int> = emptyList(),
    @SerializedName("question_type_accuracy")
    val questionTypeAccuracy: Map<String, Double> = emptyMap(),
    @SerializedName("difficulty_accuracy")
    val difficultyAccuracy: Map<String, Double> = emptyMap(),
    val notes: List<String> = emptyList(),
)

data class UserProfileSummary(
    @SerializedName("user_id")
    val userId: String = "",
    @SerializedName("generated_at")
    val generatedAt: String = "",
    @SerializedName("active_course_count")
    val activeCourseCount: Int = 0,
    @SerializedName("active_course_ids")
    val activeCourseIds: List<String> = emptyList(),
    @SerializedName("recent_course_ids")
    val recentCourseIds: List<String> = emptyList(),
    @SerializedName("preferred_question_types")
    val preferredQuestionTypes: List<String> = emptyList(),
    @SerializedName("preferred_exam_modes")
    val preferredExamModes: List<String> = emptyList(),
    @SerializedName("dominant_exam_mode")
    val dominantExamMode: String = "",
    @SerializedName("explanation_style")
    val explanationStyle: String = "",
    @SerializedName("pace_preference")
    val pacePreference: String = "",
    @SerializedName("consistency_level")
    val consistencyLevel: String = "",
    @SerializedName("pending_review_count")
    val pendingReviewCount: Int = 0,
    @SerializedName("due_review_count")
    val dueReviewCount: Int = 0,
    val notes: List<String> = emptyList(),
)

data class StudyPlanStepResponse(
    val key: String = "",
    val title: String = "",
    val detail: String = "",
    val action: String = "",
    val priority: Double = 0.0,
    val source: String = "",
)

data class ReviewTaskResponse(
    val id: Int = 0,
    @SerializedName("user_id")
    val userId: String = "",
    @SerializedName("course_id")
    val courseId: String = "",
    @SerializedName("knowledge_unit_id")
    val knowledgeUnitId: Int = 0,
    @SerializedName("knowledge_unit_name")
    val knowledgeUnitName: String? = null,
    @SerializedName("knowledge_unit_type")
    val knowledgeUnitType: String? = null,
    val priority: Double = 0.0,
    @SerializedName("scheduled_at")
    val scheduledAt: String? = null,
    val status: String = "",
    @SerializedName("interval_days")
    val intervalDays: Int = 0,
    @SerializedName("ease_factor")
    val easeFactor: Double = 0.0,
    @SerializedName("repetition_count")
    val repetitionCount: Int = 0,
    val reason: String? = null,
    @SerializedName("source_exam_paper_id")
    val sourceExamPaperId: Int? = null,
    @SerializedName("updated_at")
    val updatedAt: String = "",
)
