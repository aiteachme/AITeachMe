package com.aiteachme.android.feature.course.presentation

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.aiteachme.android.core.di.AppServices
import com.aiteachme.android.core.network.dto.QuestionTemplateGradeResponse
import com.aiteachme.android.core.network.dto.QuestionTemplateItemResponse
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlin.math.abs

private const val MasteryDrillQuestionCount = 10

data class MasteryDrillFeedback(
    val templateId: Int,
    val answer: String,
    val isCorrect: Boolean,
    val feedbackText: String? = null,
    val gradingMode: String? = null,
)

data class MasteryDrillUiState(
    val templates: List<QuestionTemplateItemResponse> = emptyList(),
    val selectedTemplates: List<QuestionTemplateItemResponse> = emptyList(),
    val queue: List<Int> = emptyList(),
    val completedIds: Set<Int> = emptySet(),
    val answers: Map<Int, String> = emptyMap(),
    val feedback: MasteryDrillFeedback? = null,
    val wrongAttemptCount: Int = 0,
    val completedAt: String? = null,
    val isLoading: Boolean = false,
    val isCheckingAnswer: Boolean = false,
    val markingTemplateId: Int? = null,
    val errorMessage: String? = null,
) {
    val currentTemplate: QuestionTemplateItemResponse?
        get() = queue.firstOrNull()?.let { templateId ->
            selectedTemplates.firstOrNull { it.id == templateId }
        }
}

class MasteryDrillViewModel : ViewModel() {
    private val examRepository = AppServices.examRepository

    private val _uiState = MutableStateFlow(MasteryDrillUiState())
    val uiState: StateFlow<MasteryDrillUiState> = _uiState.asStateFlow()

    fun load(courseId: String) {
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, errorMessage = null) }
            runCatching {
                examRepository.prepareMasteryDrill(
                    courseId = courseId,
                    numQuestions = MasteryDrillQuestionCount,
                )
            }.onSuccess { prepared ->
                startSession(templates = prepared.templates, seed = System.currentTimeMillis())
            }.onFailure { throwable ->
                _uiState.update {
                    it.copy(
                        isLoading = false,
                        errorMessage = throwable.message ?: throwable::class.java.simpleName,
                    )
                }
            }
        }
    }

    fun restart() {
        startSession(
            templates = _uiState.value.templates,
            seed = System.currentTimeMillis(),
        )
    }

    fun updateAnswer(templateId: Int, answer: String) {
        _uiState.update {
            it.copy(
                answers = it.answers + (templateId to answer),
                errorMessage = null,
            )
        }
    }

    fun checkCurrentAnswer(courseId: String) {
        val state = _uiState.value
        val current = state.currentTemplate ?: return
        if (state.feedback != null || state.isCheckingAnswer) return
        val answer = state.answers[current.id].orEmpty().trim()
        if (answer.isBlank()) return

        if (current.requiresAiGrade()) {
            viewModelScope.launch {
                _uiState.update { it.copy(isCheckingAnswer = true, errorMessage = null) }
                runCatching {
                    examRepository.gradeQuestionTemplateAnswer(
                        courseId = courseId,
                        questionTemplateId = current.id,
                        answer = answer,
                        ephemeral = true,
                    )
                }.onSuccess { grade ->
                    _uiState.update {
                        it.copy(
                            isCheckingAnswer = false,
                            feedback = current.toFeedback(answer = answer, grade = grade),
                        )
                    }
                }.onFailure { throwable ->
                    _uiState.update {
                        it.copy(
                            isCheckingAnswer = false,
                            errorMessage = throwable.message ?: throwable::class.java.simpleName,
                        )
                    }
                }
            }
            return
        }

        _uiState.update {
            it.copy(
                feedback = MasteryDrillFeedback(
                    templateId = current.id,
                    answer = answer,
                    isCorrect = isAnswerCorrect(current, answer),
                ),
            )
        }
    }

    fun toggleCurrentMark(courseId: String) {
        val state = _uiState.value
        val current = state.currentTemplate ?: return
        if (state.markingTemplateId != null) return
        val targetMarked = !current.isMarked

        _uiState.update {
            it.patchTemplateMark(current.id, targetMarked).copy(
                markingTemplateId = current.id,
                errorMessage = null,
            )
        }
        viewModelScope.launch {
            runCatching {
                examRepository.markQuestionTemplate(
                    courseId = courseId,
                    questionTemplateId = current.id,
                    isMarked = targetMarked,
                )
            }.onSuccess { response ->
                _uiState.update {
                    it.patchTemplateMark(current.id, response.isMarked).copy(markingTemplateId = null)
                }
            }.onFailure { throwable ->
                _uiState.update {
                    it.patchTemplateMark(current.id, current.isMarked).copy(
                        markingTemplateId = null,
                        errorMessage = throwable.message ?: throwable::class.java.simpleName,
                    )
                }
            }
        }
    }

    fun continueAfterFeedback() {
        val state = _uiState.value
        val current = state.currentTemplate ?: return
        val feedback = state.feedback?.takeIf { it.templateId == current.id } ?: return
        val remaining = state.queue.drop(1)

        if (feedback.isCorrect) {
            val completedIds = state.completedIds + current.id
            _uiState.update {
                it.copy(
                    completedIds = completedIds,
                    queue = remaining,
                    feedback = null,
                    completedAt = if (remaining.isEmpty()) System.currentTimeMillis().toString() else it.completedAt,
                )
            }
            return
        }

        _uiState.update {
            it.copy(
                queue = remaining + current.id,
                answers = it.answers - current.id,
                feedback = null,
                wrongAttemptCount = it.wrongAttemptCount + 1,
            )
        }
    }

    private fun startSession(
        templates: List<QuestionTemplateItemResponse>,
        seed: Long,
    ) {
        val selected = selectMasteryDrillTemplates(templates = templates, seed = seed)
        _uiState.update {
            it.copy(
                templates = templates,
                selectedTemplates = selected,
                queue = selected.map { template -> template.id },
                completedIds = emptySet(),
                answers = emptyMap(),
                feedback = null,
                wrongAttemptCount = 0,
                completedAt = null,
                isLoading = false,
                isCheckingAnswer = false,
                markingTemplateId = null,
                errorMessage = null,
            )
        }
    }
}

private fun MasteryDrillUiState.patchTemplateMark(
    templateId: Int,
    isMarked: Boolean,
): MasteryDrillUiState {
    fun List<QuestionTemplateItemResponse>.patch(): List<QuestionTemplateItemResponse> {
        return map { template ->
            if (template.id == templateId) template.copy(isMarked = isMarked) else template
        }
    }
    return copy(
        templates = templates.patch(),
        selectedTemplates = selectedTemplates.patch(),
    )
}

private fun QuestionTemplateItemResponse.requiresAiGrade(): Boolean {
    return questionType.lowercase() in setOf("fill_blank", "short_answer")
}

private fun QuestionTemplateItemResponse.toFeedback(
    answer: String,
    grade: QuestionTemplateGradeResponse,
): MasteryDrillFeedback {
    return MasteryDrillFeedback(
        templateId = id,
        answer = answer,
        isCorrect = grade.isCorrect,
        feedbackText = grade.feedbackText.takeIf { it.isNotBlank() },
        gradingMode = grade.gradingMode.takeIf { it.isNotBlank() },
    )
}

private fun selectMasteryDrillTemplates(
    templates: List<QuestionTemplateItemResponse>,
    seed: Long,
): List<QuestionTemplateItemResponse> {
    return templates
        .filter { template ->
            isSupportedExamQuestionType(template.questionType) &&
                template.stem.isNotBlank() &&
                template.answer.isNotBlank() &&
                template.status.equals("active", ignoreCase = true)
        }
        .sortedWith(
            compareByDescending<QuestionTemplateItemResponse> { template -> template.drillPriority() }
                .thenBy { template -> hashTemplateForSession(template.id, seed) }
                .thenByDescending { template -> template.updatedAt }
                .thenByDescending { template -> template.id },
        )
        .take(MasteryDrillQuestionCount)
}

private fun QuestionTemplateItemResponse.drillPriority(): Int {
    var priority = 0
    if (hasWrongAttempt) priority += 4
    if (isMarked) priority += 2
    return priority
}

private fun hashTemplateForSession(templateId: Int, seed: Long): Int {
    var hash = 2_166_136_261L
    "$templateId:$seed".forEach { char ->
        hash = (hash xor char.code.toLong()) * 16_777_619L
        hash = hash and 0xFFFF_FFFFL
    }
    return abs(hash.toInt())
}

private fun isAnswerCorrect(
    template: QuestionTemplateItemResponse,
    answer: String,
): Boolean {
    return when (template.questionType.lowercase()) {
        "multiple_choice", "multi_choice" -> {
            val expected = drillSplitMultiChoiceAnswer(template.answer)
            val actual = drillSplitMultiChoiceAnswer(answer)
            expected.isNotEmpty() && expected == actual
        }
        "true_false" -> normalizeTrueFalseAnswer(template.answer) == normalizeTrueFalseAnswer(answer)
        else -> drillNormalizeTextAnswer(template.answer) == drillNormalizeTextAnswer(answer)
    }
}

fun drillSplitMultiChoiceAnswer(value: String?): Set<String> {
    return value.orEmpty()
        .replace("，", ",")
        .replace("、", ",")
        .replace("；", ",")
        .replace(";", ",")
        .split(",", " ")
        .map { it.trim().uppercase() }
        .filter { it.isNotBlank() }
        .toSet()
}

fun drillNormalizeTextAnswer(value: String?): String {
    return value.orEmpty()
        .replace("，", ",")
        .replace("、", ",")
        .replace("；", ",")
        .replace(";", ",")
        .replace(Regex("\\s+"), " ")
        .trim()
        .lowercase()
}

private fun normalizeTrueFalseAnswer(value: String?): String {
    return when (drillNormalizeTextAnswer(value)) {
        "true", "t", "yes", "y", "正确", "对", "是" -> "true"
        "false", "f", "no", "n", "错误", "错", "否" -> "false"
        else -> drillNormalizeTextAnswer(value)
    }
}
