package com.aiteachme.android.feature.course.presentation

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.aiteachme.android.core.di.AppServices
import com.aiteachme.android.core.network.dto.SettingsOverviewData
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class SettingsUiState(
    val isLoading: Boolean = false,
    val isSubmittingFeedback: Boolean = false,
    val settings: SettingsOverviewData? = null,
    val feedbackDraft: String = "",
    val errorMessage: String? = null,
    val infoMessage: String? = null,
)

class SettingsViewModel : ViewModel() {
    private val systemRepository = AppServices.systemRepository
    private val _uiState = MutableStateFlow(SettingsUiState())
    val uiState: StateFlow<SettingsUiState> = _uiState.asStateFlow()

    fun load() {
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, errorMessage = null, infoMessage = null) }
            runCatching { systemRepository.getSettings() }
                .onSuccess { settings ->
                    _uiState.update { it.copy(isLoading = false, settings = settings) }
                }.onFailure { error ->
                    _uiState.update { it.copy(isLoading = false, errorMessage = error.message ?: error::class.java.simpleName) }
                }
        }
    }

    fun updateFeedbackDraft(value: String) {
        _uiState.update { it.copy(feedbackDraft = value, errorMessage = null, infoMessage = null) }
    }

    fun submitFeedback() {
        val content = _uiState.value.feedbackDraft.trim()
        if (content.isBlank() || _uiState.value.isSubmittingFeedback) return
        viewModelScope.launch {
            _uiState.update { it.copy(isSubmittingFeedback = true, errorMessage = null, infoMessage = null) }
            runCatching { systemRepository.submitFeedback(content) }
                .onSuccess {
                    _uiState.update {
                        it.copy(
                            isSubmittingFeedback = false,
                            feedbackDraft = "",
                            infoMessage = "反馈已提交",
                        )
                    }
                }.onFailure { error ->
                    _uiState.update {
                        it.copy(
                            isSubmittingFeedback = false,
                            errorMessage = error.message ?: error::class.java.simpleName,
                        )
                    }
                }
        }
    }
}
