package com.aiteachme.android.feature.course.presentation

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.aiteachme.android.core.di.AppServices
import com.aiteachme.android.core.network.dto.ExamGenerateRequest
import com.aiteachme.android.core.network.dto.ExamGradeResponse
import com.aiteachme.android.core.network.dto.ExamHistoryItem
import com.aiteachme.android.core.network.dto.ExamPaperDetailResponse
import com.aiteachme.android.core.network.dto.ExamSubmitAnswerItem
import com.aiteachme.android.core.network.dto.ExamSubmitRequest
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

enum class PracticeMode(
    val apiValue: String,
    val label: String,
    val description: String,
    val defaultQuestionCount: Int,
) {
    WebPractice(
        apiValue = "web_practice",
        label = "练习",
        description = "按当前知识空间快速出题，用于即时巩固。",
        defaultQuestionCount = 8,
    ),
    PaperExam(
        apiValue = "paper_exam",
        label = "测试组卷",
        description = "生成更接近正式测试的试卷。",
        defaultQuestionCount = 24,
    ),
    MasteryDrill(
        apiValue = "mastery_drill",
        label = "闯关",
        description = "优先覆盖薄弱知识点，提交后回写掌握状态。",
        defaultQuestionCount = 8,
    );

    companion object {
        fun fromApiValue(value: String): PracticeMode {
            return values().firstOrNull { it.apiValue == value } ?: WebPractice
        }
    }
}

data class PracticeUiState(
    val mode: PracticeMode = PracticeMode.WebPractice,
    val questionCount: Int = PracticeMode.WebPractice.defaultQuestionCount,
    val prompt: String = "",
    val history: List<ExamHistoryItem> = emptyList(),
    val currentPaper: ExamPaperDetailResponse? = null,
    val answers: Map<Int, String> = emptyMap(),
    val lastGrade: ExamGradeResponse? = null,
    val isLoadingHistory: Boolean = false,
    val isGenerating: Boolean = false,
    val isOpeningPaper: Boolean = false,
    val isSubmitting: Boolean = false,
    val errorMessage: String? = null,
    val infoMessage: String? = null,
)

class PracticeViewModel : ViewModel() {
    private val examRepository = AppServices.examRepository

    private val _uiState = MutableStateFlow(PracticeUiState())
    val uiState: StateFlow<PracticeUiState> = _uiState.asStateFlow()

    fun load(courseId: String) {
        viewModelScope.launch {
            refreshHistory(courseId)
        }
    }

    fun selectMode(mode: PracticeMode) {
        _uiState.update {
            it.copy(
                mode = mode,
                questionCount = mode.defaultQuestionCount,
                errorMessage = null,
                infoMessage = null,
            )
        }
    }

    fun selectQuestionCount(count: Int) {
        _uiState.update {
            it.copy(
                questionCount = count.coerceIn(1, 200),
                errorMessage = null,
                infoMessage = null,
            )
        }
    }

    fun updatePrompt(value: String) {
        _uiState.update { it.copy(prompt = value, errorMessage = null) }
    }

    fun updateAnswer(itemId: Int, value: String) {
        _uiState.update {
            it.copy(
                answers = it.answers + (itemId to value),
                errorMessage = null,
            )
        }
    }

    fun generate(courseId: String) {
        val state = _uiState.value
        if (state.isGenerating || state.isSubmitting) {
            return
        }
        viewModelScope.launch {
            _uiState.update {
                it.copy(
                    isGenerating = true,
                    currentPaper = null,
                    answers = emptyMap(),
                    lastGrade = null,
                    errorMessage = null,
                    infoMessage = "正在生成${state.mode.label}...",
                )
            }
            runCatching {
                val response = examRepository.generateExam(
                    courseId = courseId,
                    request = ExamGenerateRequest(
                        examMode = state.mode.apiValue,
                        userPrompt = state.prompt.trim().takeIf { it.isNotBlank() },
                        numQuestions = state.questionCount,
                    ),
                )
                val paperId = response.examPaperId ?: response.id.takeIf { it > 0 }
                    ?: throw IllegalStateException("后端未返回试卷编号")
                pollPaperUntilReady(courseId = courseId, paperId = paperId)
            }.onSuccess { detail ->
                _uiState.update {
                    it.copy(
                        isGenerating = false,
                        currentPaper = detail,
                        answers = detail.answersByItemId(),
                        mode = PracticeMode.fromApiValue(detail.examMode),
                        questionCount = detail.totalItems.takeIf { count -> count > 0 } ?: it.questionCount,
                        errorMessage = detail.errorMessage(),
                        infoMessage = if (detail.isFailed()) null else "试卷已生成",
                    )
                }
                refreshHistory(courseId)
            }.onFailure { throwable ->
                _uiState.update {
                    it.copy(
                        isGenerating = false,
                        errorMessage = throwable.message ?: throwable::class.java.simpleName,
                        infoMessage = null,
                    )
                }
                refreshHistory(courseId)
            }
        }
    }

    fun openPaper(courseId: String, paperId: Int) {
        if (_uiState.value.isOpeningPaper) {
            return
        }
        viewModelScope.launch {
            _uiState.update {
                it.copy(
                    isOpeningPaper = true,
                    lastGrade = null,
                    errorMessage = null,
                    infoMessage = null,
                )
            }
            runCatching {
                pollPaperUntilReady(courseId = courseId, paperId = paperId)
            }.onSuccess { detail ->
                _uiState.update {
                    it.copy(
                        isOpeningPaper = false,
                        currentPaper = detail,
                        answers = detail.answersByItemId(),
                        mode = PracticeMode.fromApiValue(detail.examMode),
                        questionCount = detail.totalItems.takeIf { count -> count > 0 } ?: it.questionCount,
                        errorMessage = detail.errorMessage(),
                    )
                }
            }.onFailure { throwable ->
                _uiState.update {
                    it.copy(
                        isOpeningPaper = false,
                        errorMessage = throwable.message ?: throwable::class.java.simpleName,
                    )
                }
            }
        }
    }

    fun submit(courseId: String) {
        val state = _uiState.value
        val paper = state.currentPaper ?: return
        if (state.isSubmitting || state.isGenerating || paper.items.isEmpty()) {
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
                val request = ExamSubmitRequest(
                    answers = paper.items.map { item ->
                        ExamSubmitAnswerItem(
                            examPaperItemId = item.id,
                            itemOrder = item.itemOrder,
                            answer = state.answers[item.id].orEmpty(),
                        )
                    },
                )
                val grade = examRepository.submitExam(
                    courseId = courseId,
                    examPaperId = paper.id,
                    request = request,
                )
                grade to examRepository.getExamDetail(courseId = courseId, examPaperId = paper.id)
            }.onSuccess { (grade, detail) ->
                _uiState.update {
                    it.copy(
                        isSubmitting = false,
                        currentPaper = detail,
                        answers = detail.answersByItemId(),
                        lastGrade = grade,
                        errorMessage = null,
                        infoMessage = "批改完成",
                    )
                }
                refreshHistory(courseId)
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

    private suspend fun refreshHistory(courseId: String) {
        _uiState.update { it.copy(isLoadingHistory = true) }
        runCatching {
            examRepository.listHistory(courseId = courseId, size = 30)
        }.onSuccess { history ->
            _uiState.update {
                it.copy(
                    history = history,
                    isLoadingHistory = false,
                )
            }
        }.onFailure { throwable ->
            _uiState.update {
                it.copy(
                    isLoadingHistory = false,
                    errorMessage = throwable.message ?: throwable::class.java.simpleName,
                )
            }
        }
    }

    private suspend fun pollPaperUntilReady(
        courseId: String,
        paperId: Int,
    ): ExamPaperDetailResponse {
        var detail = examRepository.getExamDetail(courseId = courseId, examPaperId = paperId)
        var attempts = 0
        while (detail.status.isGeneratingStatus() && attempts < 40) {
            delay(1_500)
            detail = examRepository.getExamDetail(courseId = courseId, examPaperId = paperId)
            attempts += 1
        }
        return detail
    }
}

private fun String.isGeneratingStatus(): Boolean {
    return lowercase() in setOf("accepted", "pending", "queued", "running", "generating", "preparing")
}

private fun ExamPaperDetailResponse.answersByItemId(): Map<Int, String> {
    return items.associate { item -> item.id to item.userAnswer.orEmpty() }
}

private fun ExamPaperDetailResponse.isFailed(): Boolean {
    return status.lowercase() == "failed"
}

private fun ExamPaperDetailResponse.errorMessage(): String? {
    return if (isFailed()) {
        "试卷生成失败，请调整要求后重试。"
    } else {
        null
    }
}
