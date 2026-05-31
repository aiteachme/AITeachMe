package com.aiteachme.android.app

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.aiteachme.android.core.di.AppServices
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class AppStartupUiState(
    val isLoading: Boolean = true,
    val isReady: Boolean = false,
    val targetCourseId: String? = null,
)

class AppStartupViewModel : ViewModel() {
    private val courseRepository = AppServices.courseRepository
    private val courseContext = AppServices.courseContextStore

    private val _uiState = MutableStateFlow(AppStartupUiState())
    val uiState: StateFlow<AppStartupUiState> = _uiState.asStateFlow()

    init {
        loadInitialCourse()
    }

    private fun loadInitialCourse() {
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, isReady = false) }
            runCatching {
                courseRepository.listCourses(size = 100)
            }.onSuccess { courses ->
                courseContext.setCourses(courses)
                _uiState.update {
                    it.copy(
                        isLoading = false,
                        isReady = true,
                        targetCourseId = courseContext.state.value.selectedCourseId,
                    )
                }
            }.onFailure {
                _uiState.update {
                    it.copy(
                        isLoading = false,
                        isReady = true,
                        targetCourseId = courseContext.state.value.selectedCourseId,
                    )
                }
            }
        }
    }
}
