package com.aiteachme.android.feature.course.presentation

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.aiteachme.android.core.di.AppServices
import com.aiteachme.android.core.network.dto.ExamPaperDetailResponse
import com.aiteachme.android.core.network.dto.MasteryDrillAttemptRequest
import com.aiteachme.android.core.network.dto.MasteryDrillAttemptResponse
import com.aiteachme.android.core.network.dto.MasteryDrillCompleteRequest
import com.aiteachme.android.core.network.dto.MasteryDrillStartRequest
import com.aiteachme.android.core.network.dto.QuestionTemplateItemResponse
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import java.util.UUID
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
    val examPaperId: Int? = null,
    val templates: List<QuestionTemplateItemResponse> = emptyList(),
    val selectedTemplates: List<QuestionTemplateItemResponse> = emptyList(),
    val paperItemIdByTemplateId: Map<Int, Int> = emptyMap(),
    val queue: List<Int> = emptyList(),
    val completedIds: Set<Int> = emptySet(),
    val answers: Map<Int, String> = emptyMap(),
    val feedback: MasteryDrillFeedback? = null,
    val wrongAttemptCount: Int = 0,
    val completedAt: String? = null,
    val isLoading: Boolean = false,
    val isCheckingAnswer: Boolean = false,
    val isCompleting: Boolean = false,
    val errorMessage: String? = null,
) {
    val currentTemplate: QuestionTemplateItemResponse?
        get() = queue.firstOrNull()?.let { templateId ->
            selectedTemplates.firstOrNull { it.id == templateId }
        }
}

class MasteryDrillViewModel : ViewModel() {
    private val examRepository = AppServices.examRepository
    private var currentCourseId: String? = null
    private val pendingAttemptKeys = mutableMapOf<String, String>()
    private val completionKeys = mutableMapOf<Int, String>()

    private val _uiState = MutableStateFlow(MasteryDrillUiState())
    val uiState: StateFlow<MasteryDrillUiState> = _uiState.asStateFlow()

    fun load(courseId: String) {
        currentCourseId = courseId
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, errorMessage = null) }
            runCatching {
                val templates = examRepository.listQuestionTemplates(courseId)
                startOrResumeSession(
                    courseId = courseId,
                    templates = templates,
                    seed = System.currentTimeMillis(),
                )
            }.onSuccess { paper ->
                applyServerSession(paper = paper, templates = _uiState.value.templates)
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
        val courseId = currentCourseId ?: return
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, errorMessage = null) }
            runCatching {
                val templates = _uiState.value.templates.ifEmpty {
                    examRepository.listQuestionTemplates(courseId)
                }
                startOrResumeSession(
                    courseId = courseId,
                    templates = templates,
                    seed = System.currentTimeMillis(),
                )
            }.onSuccess { paper ->
                pendingAttemptKeys.clear()
                applyServerSession(paper = paper, templates = _uiState.value.templates)
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
        if (!isSupportedExamQuestionType(current.questionType)) {
            _uiState.update {
                it.copy(errorMessage = "当前版本不支持题型「${current.questionType.ifBlank { "未指定" }}」")
            }
            return
        }
        val answer = state.answers[current.id].orEmpty().trim()
        if (answer.isBlank()) return

        val paperId = state.examPaperId ?: return
        val paperItemId = state.paperItemIdByTemplateId[current.id] ?: return
        val payloadKey = "$paperId:$paperItemId:$answer"
        val attemptKey = pendingAttemptKeys.getOrPut(payloadKey) { "android-attempt-${UUID.randomUUID()}" }
        viewModelScope.launch {
            _uiState.update { it.copy(isCheckingAnswer = true, errorMessage = null) }
            runCatching {
                examRepository.recordMasteryDrillAttempt(
                    courseId = courseId,
                    examPaperId = paperId,
                    request = MasteryDrillAttemptRequest(
                        examPaperItemId = paperItemId,
                        answer = answer,
                        attemptKey = attemptKey,
                    ),
                )
            }.onSuccess { attempt ->
                pendingAttemptKeys.remove(payloadKey)
                _uiState.update {
                    it.copy(
                        isCheckingAnswer = false,
                        feedback = current.toFeedback(answer = answer, attempt = attempt),
                        wrongAttemptCount = it.wrongAttemptCount + if (attempt.isCorrect == true) 0 else 1,
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
                )
            }
            if (remaining.isEmpty()) {
                currentCourseId?.let(::completeCurrentSession)
            }
            return
        }

        _uiState.update {
            it.copy(
                queue = remaining + current.id,
                answers = it.answers - current.id,
                feedback = null,
            )
        }
    }

    private suspend fun startOrResumeSession(
        courseId: String,
        templates: List<QuestionTemplateItemResponse>,
        seed: Long,
    ): ExamPaperDetailResponse {
        _uiState.update { it.copy(templates = templates) }
        examRepository.getActiveMasteryDrill(courseId)?.let { return it }
        val selected = selectMasteryDrillTemplates(templates = templates, seed = seed)
        if (selected.isEmpty()) {
            return ExamPaperDetailResponse()
        }
        return examRepository.startMasteryDrill(
            courseId = courseId,
            request = MasteryDrillStartRequest(
                sessionKey = "android-drill-${UUID.randomUUID()}",
                questionTemplateIds = selected.map { it.id },
                configuredQuestionCount = MasteryDrillQuestionCount,
                configuredQuestionTypes = selected.map { it.questionType }.distinct(),
            ),
        )
    }

    private fun applyServerSession(
        paper: ExamPaperDetailResponse,
        templates: List<QuestionTemplateItemResponse>,
    ) {
        if (paper.id <= 0) {
            _uiState.update {
                it.copy(
                    examPaperId = null,
                    selectedTemplates = emptyList(),
                    paperItemIdByTemplateId = emptyMap(),
                    queue = emptyList(),
                    isLoading = false,
                    isCheckingAnswer = false,
                    isCompleting = false,
                )
            }
            return
        }
        val templateById = templates.associateBy { it.id }
        val orderedItems = paper.items.sortedBy { it.itemOrder }
        val selected = orderedItems.map { item ->
            templateById[item.questionTemplateId] ?: QuestionTemplateItemResponse(
                id = item.questionTemplateId,
                courseId = paper.courseId,
                questionType = item.questionType,
                difficulty = item.difficulty,
                stem = item.stem,
                options = item.options,
                answer = item.correctAnswer.orEmpty(),
                explanation = item.explanation,
                status = "active",
                isMarked = item.isMarked,
            )
        }
        val completedTemplateIds = orderedItems
            .filter { it.isCorrect == true }
            .map { it.questionTemplateId }
            .toSet()
        val queue = selected.map { it.id }.filterNot(completedTemplateIds::contains)
        val persistedAnswers = orderedItems
            .filter { it.isCorrect == true && !it.userAnswer.isNullOrBlank() }
            .associate { it.questionTemplateId to it.userAnswer.orEmpty() }
        _uiState.update {
            it.copy(
                examPaperId = paper.id,
                templates = templates,
                selectedTemplates = selected,
                paperItemIdByTemplateId = orderedItems.associate { it.questionTemplateId to it.id },
                queue = queue,
                completedIds = completedTemplateIds,
                answers = persistedAnswers,
                feedback = null,
                wrongAttemptCount = paper.masteryDrill?.wrongAttempts ?: 0,
                completedAt = paper.masteryDrill?.completedAt,
                isLoading = false,
                isCheckingAnswer = false,
                isCompleting = false,
                errorMessage = null,
            )
        }
        if (queue.isEmpty() && paper.masteryDrill?.status == "active") {
            currentCourseId?.let(::completeCurrentSession)
        }
    }

    fun retryCompletion() {
        currentCourseId?.let(::completeCurrentSession)
    }

    private fun completeCurrentSession(courseId: String) {
        val state = _uiState.value
        val paperId = state.examPaperId ?: return
        if (state.isCompleting || state.completedAt != null || state.queue.isNotEmpty()) return
        val completionKey = completionKeys.getOrPut(paperId) { "android-complete-${UUID.randomUUID()}" }
        viewModelScope.launch {
            _uiState.update { it.copy(isCompleting = true, errorMessage = null) }
            runCatching {
                examRepository.completeMasteryDrill(
                    courseId = courseId,
                    examPaperId = paperId,
                    request = MasteryDrillCompleteRequest(completionKey = completionKey),
                )
            }.onSuccess {
                _uiState.update {
                    it.copy(
                        isCompleting = false,
                        completedAt = System.currentTimeMillis().toString(),
                    )
                }
            }.onFailure { throwable ->
                _uiState.update {
                    it.copy(
                        isCompleting = false,
                        errorMessage = throwable.message ?: throwable::class.java.simpleName,
                    )
                }
            }
        }
    }
}

private fun QuestionTemplateItemResponse.toFeedback(
    answer: String,
    attempt: MasteryDrillAttemptResponse,
): MasteryDrillFeedback {
    return MasteryDrillFeedback(
        templateId = id,
        answer = answer,
        isCorrect = attempt.isCorrect == true,
        feedbackText = attempt.feedbackText?.takeIf { it.isNotBlank() },
        gradingMode = attempt.gradingMode?.takeIf { it.isNotBlank() },
    )
}

private fun selectMasteryDrillTemplates(
    templates: List<QuestionTemplateItemResponse>,
    seed: Long,
): List<QuestionTemplateItemResponse> {
    return templates
        .filter { template ->
            template.stem.isNotBlank() &&
                template.answer.isNotBlank() &&
                isSupportedExamQuestionType(template.questionType) &&
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
