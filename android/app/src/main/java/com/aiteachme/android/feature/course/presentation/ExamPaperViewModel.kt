package com.aiteachme.android.feature.course.presentation

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.aiteachme.android.core.di.AppServices
import com.aiteachme.android.core.network.dto.ExamPaperDetailResponse
import com.aiteachme.android.core.network.dto.ExamStudyGuideResponse
import com.aiteachme.android.core.network.dto.ExamSubmitAnswerItem
import com.aiteachme.android.core.network.dto.ExamSubmitRequest
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
    val isLoadingStudyGuide: Boolean = false,
    val errorMessage: String? = null,
    val infoMessage: String? = null,
)

class ExamPaperViewModel : ViewModel() {
    private val examRepository = AppServices.examRepository

    private val _uiState = MutableStateFlow(ExamPaperUiState())
    val uiState: StateFlow<ExamPaperUiState> = _uiState.asStateFlow()

    fun load(courseId: String, examPaperId: Int) {
        viewModelScope.launch {
            _uiState.update {
                it.copy(
                    isLoading = true,
                    errorMessage = null,
                    infoMessage = null,
                )
            }
            runCatching {
                examRepository.getExamDetail(courseId = courseId, examPaperId = examPaperId)
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
        viewModelScope.launch {
            _uiState.update {
                it.copy(
                    isSubmitting = true,
                    errorMessage = null,
                    infoMessage = "正在提交并批改...",
                )
            }
            runCatching {
                examRepository.submitExam(
                    courseId = courseId,
                    examPaperId = paper.id,
                    request = ExamSubmitRequest(
                        answers = paper.items.map { item ->
                            ExamSubmitAnswerItem(
                                examPaperItemId = item.id,
                                itemOrder = item.itemOrder,
                                answer = state.answers[item.id].orEmpty(),
                            )
                        },
                    ),
                )
                examRepository.getExamDetail(courseId = courseId, examPaperId = paper.id)
            }.onSuccess { gradedPaper ->
                _uiState.update {
                    it.copy(
                        paper = gradedPaper,
                        answers = gradedPaper.answersByItemId(),
                        stage = ExamPaperStage.Review,
                        selectedQuestionId = gradedPaper.items.firstOrNull { item -> item.isCorrect == false }?.id
                            ?: gradedPaper.items.firstOrNull()?.id,
                        isSubmitting = false,
                        infoMessage = "批改完成",
                    )
                }
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
}

private fun ExamPaperDetailResponse.answersByItemId(): Map<Int, String> {
    return items.associate { item -> item.id to item.userAnswer.orEmpty() }
}

private fun ExamPaperDetailResponse.isGraded(): Boolean {
    return status.lowercase() == "graded"
}
