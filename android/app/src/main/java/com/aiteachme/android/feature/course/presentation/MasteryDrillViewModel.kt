package com.aiteachme.android.feature.course.presentation

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.aiteachme.android.core.di.AppServices
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
                examRepository.listQuestionTemplates(courseId)
            }.onSuccess { templates ->
                startSession(templates = templates, seed = System.currentTimeMillis())
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

    fun checkCurrentAnswer() {
        val state = _uiState.value
        val current = state.currentTemplate ?: return
        if (state.feedback != null) return
        val answer = state.answers[current.id].orEmpty().trim()
        if (answer.isBlank()) return

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
                errorMessage = null,
            )
        }
    }
}

private fun selectMasteryDrillTemplates(
    templates: List<QuestionTemplateItemResponse>,
    seed: Long,
): List<QuestionTemplateItemResponse> {
    return templates
        .filter { template ->
            template.stem.isNotBlank() &&
                template.answer.isNotBlank() &&
                !template.status.equals("archived", ignoreCase = true)
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
    if (status.equals("active", ignoreCase = true)) priority += 1
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
