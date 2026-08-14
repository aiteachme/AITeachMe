package com.aiteachme.android.feature.course.presentation

internal val SupportedExamQuestionTypes = setOf(
    "single_choice",
    "multiple_choice",
    "true_false",
    "fill_blank",
    "short_answer",
)
private val AiGradedExamQuestionTypes = setOf("fill_blank", "short_answer")

internal fun normalizeExamQuestionType(questionType: String): String {
    val normalized = questionType.trim().lowercase()
    return if (normalized == "multi_choice") "multiple_choice" else normalized
}

internal fun isSupportedExamQuestionType(questionType: String): Boolean {
    return normalizeExamQuestionType(questionType) in SupportedExamQuestionTypes
}

internal fun isAiGradedExamQuestionType(questionType: String): Boolean {
    return normalizeExamQuestionType(questionType) in AiGradedExamQuestionTypes
}
