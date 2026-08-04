package com.aiteachme.android.feature.course.presentation

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.aiteachme.android.core.di.AppServices
import com.aiteachme.android.core.network.dto.ExamPaperDetailResponse
import com.aiteachme.android.core.network.dto.ExamProfileSyncResponse
import com.aiteachme.android.core.network.dto.ExamStudyGuideResponse
import com.aiteachme.android.core.network.dto.ExamSubmitAnswerItem
import com.aiteachme.android.core.network.dto.ExamSubmitRequest
import java.util.UUID
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

enum class ExamPaperStage {
    Answer,
    Review,
    Study,
}

data class ExamPaperUiState(
    val paper: ExamPaperDetailResponse? = null,
    val studyGuide: ExamStudyGuideResponse? = null,
    val answers: Map<Int, String> = emptyMap(),
    val stage: ExamPaperStage = ExamPaperStage.Answer,
    val selectedQuestionId: Int? = null,
    val isLoading: Boolean = false,
    val isSubmitting: Boolean = false,
    val isRetryingProfileSync: Boolean = false,
    val isLoadingStudyGuide: Boolean = false,
    val errorMessage: String? = null,
    val infoMessage: String? = null,
)

class ExamPaperViewModel : ViewModel() {
    private val examRepository = AppServices.examRepository
    private var profileSyncPollingJob: Job? = null

    private val _uiState = MutableStateFlow(ExamPaperUiState())
    val uiState: StateFlow<ExamPaperUiState> = _uiState.asStateFlow()

    fun load(courseId: String, examPaperId: Int) {
        profileSyncPollingJob?.cancel()
        viewModelScope.launch {
            _uiState.update {
                it.copy(
                    isLoading = true,
                    errorMessage = null,
                    infoMessage = null,
                )
            }
            runCatching {
                pollPaperUntilGraded(
                    courseId = courseId,
                    examPaperId = examPaperId,
                    initial = examRepository.getExamDetail(courseId = courseId, examPaperId = examPaperId),
                )
            }.onSuccess { paper ->
                _uiState.update {
                    it.copy(
                        paper = paper,
                        answers = paper.answersByItemId(),
                        stage = if (paper.isGraded()) ExamPaperStage.Review else ExamPaperStage.Answer,
                        selectedQuestionId = paper.items.firstOrNull()?.id,
                        isLoading = false,
                    )
                }
                startProfileSyncPolling(courseId = courseId, examPaperId = paper.id)
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

    fun setStage(stage: ExamPaperStage) {
        val paper = _uiState.value.paper ?: return
        if (stage != ExamPaperStage.Answer && !paper.isGraded()) {
            return
        }
        _uiState.update { it.copy(stage = stage, errorMessage = null, infoMessage = null) }
    }

    fun selectQuestion(itemId: Int) {
        _uiState.update { it.copy(selectedQuestionId = itemId) }
    }

    fun updateAnswer(itemId: Int, value: String) {
        _uiState.update {
            it.copy(
                answers = it.answers + (itemId to value),
                errorMessage = null,
            )
        }
    }

    fun submit(courseId: String) {
        val state = _uiState.value
        val paper = state.paper ?: return
        if (state.isSubmitting || paper.items.isEmpty() || paper.isGraded()) {
            return
        }
        val isGradingRetry = paper.status.lowercase() == "grading_failed"
        viewModelScope.launch {
            _uiState.update {
                it.copy(
                    isSubmitting = true,
                    errorMessage = null,
                    infoMessage = if (isGradingRetry) "正在重新批改已保存的答卷..." else "正在提交并批改...",
                )
            }
            runCatching {
                examRepository.submitExam(
                    courseId = courseId,
                    examPaperId = paper.id,
                    request = ExamSubmitRequest(
                        submissionKey = UUID.randomUUID().toString(),
                        answers = paper.items.map { item ->
                            ExamSubmitAnswerItem(
                                examPaperItemId = item.id,
                                itemOrder = item.itemOrder,
                                answer = if (isGradingRetry) item.userAnswer.orEmpty() else state.answers[item.id].orEmpty(),
                            )
                        },
                    ),
                )
                pollPaperUntilGraded(
                    courseId = courseId,
                    examPaperId = paper.id,
                    initial = examRepository.getExamDetail(courseId = courseId, examPaperId = paper.id),
                )
            }.onSuccess { gradedPaper ->
                _uiState.update {
                    it.copy(
                        paper = gradedPaper,
                        answers = gradedPaper.answersByItemId(),
                        stage = if (gradedPaper.isGraded()) ExamPaperStage.Review else ExamPaperStage.Answer,
                        selectedQuestionId = gradedPaper.items.firstOrNull { item -> item.isCorrect == false }?.id
                            ?: gradedPaper.items.firstOrNull()?.id,
                        isSubmitting = false,
                        infoMessage = when {
                            gradedPaper.isGraded() -> if (gradedPaper.profileSync.isActive()) {
                                "批改完成，学习画像正在后台同步"
                            } else {
                                "批改完成"
                            }
                            gradedPaper.status.lowercase() == "grading_failed" ->
                                "自动判卷多次失败，已停止重试。可再次手动重新批改。"
                            else -> "答卷已提交，后台仍在批改"
                        },
                    )
                }
                startProfileSyncPolling(courseId = courseId, examPaperId = gradedPaper.id)
            }.onFailure { throwable ->
                _uiState.update {
                    it.copy(
                        isSubmitting = false,
                        errorMessage = throwable.message ?: throwable::class.java.simpleName,
                        infoMessage = null,
                    )
                }
            }
        }
    }

    fun retryProfileSync(courseId: String) {
        val paper = _uiState.value.paper ?: return
        if (!paper.isGraded() || _uiState.value.isRetryingProfileSync) {
            return
        }
        viewModelScope.launch {
            _uiState.update {
                it.copy(
                    isRetryingProfileSync = true,
                    errorMessage = null,
                    infoMessage = null,
                )
            }
            runCatching {
                examRepository.retryProfileSync(courseId = courseId, examPaperId = paper.id)
            }.onSuccess { profileSync ->
                _uiState.update { state ->
                    if (state.paper?.id != paper.id) {
                        state.copy(isRetryingProfileSync = false)
                    } else {
                        state.copy(
                            paper = state.paper.copy(profileSync = profileSync),
                            isRetryingProfileSync = false,
                            infoMessage = if (profileSync.status.lowercase() == "completed") {
                                "学习画像已同步"
                            } else {
                                "已重新安排画像同步"
                            },
                        )
                    }
                }
                startProfileSyncPolling(courseId = courseId, examPaperId = paper.id)
            }.onFailure { throwable ->
                _uiState.update {
                    it.copy(
                        isRetryingProfileSync = false,
                        errorMessage = throwable.message ?: throwable::class.java.simpleName,
                    )
                }
            }
        }
    }

    fun loadStudyGuide(courseId: String) {
        val paper = _uiState.value.paper ?: return
        if (!paper.isGraded() || _uiState.value.isLoadingStudyGuide) {
            return
        }
        viewModelScope.launch {
            _uiState.update {
                it.copy(
                    stage = ExamPaperStage.Study,
                    isLoadingStudyGuide = true,
                    errorMessage = null,
                    infoMessage = null,
                )
            }
            runCatching {
                examRepository.getStudyGuide(courseId = courseId, examPaperId = paper.id)
            }.onSuccess { guide ->
                _uiState.update {
                    it.copy(
                        studyGuide = guide,
                        isLoadingStudyGuide = false,
                    )
                }
            }.onFailure { throwable ->
                _uiState.update {
                    it.copy(
                        isLoadingStudyGuide = false,
                        errorMessage = throwable.message ?: throwable::class.java.simpleName,
                    )
                }
            }
        }
    }

    private suspend fun pollPaperUntilGraded(
        courseId: String,
        examPaperId: Int,
        initial: ExamPaperDetailResponse,
    ): ExamPaperDetailResponse {
        var detail = initial
        var attempts = 0
        while (detail.status.lowercase() in setOf("submitted", "grading") && attempts < 120) {
            delay(1_500)
            detail = examRepository.getExamDetail(courseId = courseId, examPaperId = examPaperId)
            attempts += 1
        }
        return detail
    }

    private fun startProfileSyncPolling(courseId: String, examPaperId: Int) {
        profileSyncPollingJob?.cancel()
        if (!_uiState.value.paper?.profileSync.isActive()) {
            return
        }
        profileSyncPollingJob = viewModelScope.launch {
            var attempts = 0
            while (attempts < 120) {
                val currentPaper = _uiState.value.paper
                if (currentPaper?.id != examPaperId || !currentPaper.profileSync.isActive()) {
                    return@launch
                }
                val delayMillis = if (currentPaper.profileSync?.status?.lowercase() == "retry_wait") 15_000L else 3_000L
                delay(delayMillis)
                val updatedPaper = runCatching {
                    examRepository.getExamDetail(courseId = courseId, examPaperId = examPaperId)
                }.getOrNull()
                if (updatedPaper == null) {
                    attempts += 1
                    continue
                }
                val completed = currentPaper.profileSync?.status?.lowercase() != "completed" &&
                    updatedPaper.profileSync?.status?.lowercase() == "completed"
                _uiState.update { state ->
                    if (state.paper?.id != examPaperId) {
                        state
                    } else {
                        state.copy(
                            paper = updatedPaper,
                            infoMessage = if (completed) "学习画像已同步" else state.infoMessage,
                        )
                    }
                }
                attempts += 1
            }
        }
    }
}

private fun ExamPaperDetailResponse.answersByItemId(): Map<Int, String> {
    return items.associate { item -> item.id to item.userAnswer.orEmpty() }
}

private fun ExamPaperDetailResponse.isGraded(): Boolean {
    return status.lowercase() == "graded"
}

private fun ExamProfileSyncResponse?.isActive(): Boolean {
    return this?.status?.lowercase() in setOf("pending", "processing", "retry_wait")
}
