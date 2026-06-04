package com.aiteachme.android.feature.course.presentation

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.aiteachme.android.core.di.AppServices
import com.aiteachme.android.core.network.dto.QuestionTemplateAnswerHistoryItem
import com.aiteachme.android.core.network.dto.QuestionTemplateItemResponse
import com.aiteachme.android.core.network.dto.QuestionTypeRegistryItemResponse
import kotlinx.coroutines.async
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class QuestionBankUiState(
    val isLoading: Boolean = false,
    val isMarkingTemplateId: Int? = null,
    val selectedTemplateId: Int? = null,
    val templates: List<QuestionTemplateItemResponse> = emptyList(),
    val questionTypes: List<QuestionTypeRegistryItemResponse> = emptyList(),
    val history: List<QuestionTemplateAnswerHistoryItem> = emptyList(),
    val errorMessage: String? = null,
    val infoMessage: String? = null,
)

class QuestionBankViewModel : ViewModel() {
    private val examRepository = AppServices.examRepository
    private val _uiState = MutableStateFlow(QuestionBankUiState())
    val uiState: StateFlow<QuestionBankUiState> = _uiState.asStateFlow()

    fun loadTemplates(courseId: String) {
        if (courseId.isBlank()) return
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, errorMessage = null, infoMessage = null) }
            runCatching {
                val templates = async { examRepository.listQuestionTemplates(courseId) }
                val types = async { examRepository.listQuestionTypes(courseId) }
                templates.await() to types.await()
            }.onSuccess { (templates, types) ->
                _uiState.update {
                    it.copy(
                        isLoading = false,
                        templates = templates,
                        questionTypes = types,
                        selectedTemplateId = it.selectedTemplateId ?: templates.firstOrNull()?.id,
                    )
                }
                _uiState.value.selectedTemplateId?.let { loadHistory(courseId, it) }
            }.onFailure { error ->
                _uiState.update {
                    it.copy(isLoading = false, errorMessage = error.message ?: error::class.java.simpleName)
                }
            }
        }
    }

    fun loadQuestionTypes(courseId: String) {
        if (courseId.isBlank()) return
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, errorMessage = null, infoMessage = null) }
            runCatching { examRepository.listQuestionTypes(courseId) }
                .onSuccess { types ->
                    _uiState.update { it.copy(isLoading = false, questionTypes = types) }
                }.onFailure { error ->
                    _uiState.update {
                        it.copy(isLoading = false, errorMessage = error.message ?: error::class.java.simpleName)
                    }
                }
        }
    }

    fun selectTemplate(courseId: String, templateId: Int) {
        _uiState.update { it.copy(selectedTemplateId = templateId, history = emptyList()) }
        loadHistory(courseId, templateId)
    }

    fun toggleMark(courseId: String, template: QuestionTemplateItemResponse) {
        if (_uiState.value.isMarkingTemplateId != null) return
        viewModelScope.launch {
            _uiState.update { it.copy(isMarkingTemplateId = template.id, errorMessage = null, infoMessage = null) }
            runCatching {
                examRepository.markQuestionTemplate(
                    courseId = courseId,
                    questionTemplateId = template.id,
                    isMarked = !template.isMarked,
                )
            }.onSuccess { result ->
                _uiState.update { state ->
                    state.copy(
                        isMarkingTemplateId = null,
                        infoMessage = if (result.isMarked) "已加入重点题" else "已取消重点标记",
                        templates = state.templates.map {
                            if (it.id == result.questionTemplateId) it.copy(isMarked = result.isMarked) else it
                        },
                    )
                }
            }.onFailure { error ->
                _uiState.update {
                    it.copy(isMarkingTemplateId = null, errorMessage = error.message ?: error::class.java.simpleName)
                }
            }
        }
    }

    private fun loadHistory(courseId: String, templateId: Int) {
        viewModelScope.launch {
            runCatching { examRepository.listQuestionTemplateAnswerHistory(courseId, templateId) }
                .onSuccess { history ->
                    _uiState.update { it.copy(history = history) }
                }.onFailure { error ->
                    _uiState.update { it.copy(errorMessage = error.message ?: error::class.java.simpleName) }
                }
        }
    }
}
