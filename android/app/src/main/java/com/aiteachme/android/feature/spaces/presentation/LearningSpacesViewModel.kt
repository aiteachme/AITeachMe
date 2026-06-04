package com.aiteachme.android.feature.spaces.presentation

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.aiteachme.android.core.di.AppServices
import com.aiteachme.android.core.network.dto.CourseDeletePreviewData
import com.aiteachme.android.core.network.dto.CourseItem
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class LearningSpacesUiState(
    val courses: List<CourseItem> = emptyList(),
    val selectedCourseId: String? = null,
    val isLoading: Boolean = false,
    val isLoadingDeletePreview: Boolean = false,
    val deletingCourseIds: Set<String> = emptySet(),
    val deletePreview: CourseDeletePreviewData? = null,
    val errorMessage: String? = null,
)

class LearningSpacesViewModel : ViewModel() {
    private val courseRepository = AppServices.courseRepository
    private val courseContext = AppServices.courseContextStore

    private val _uiState = MutableStateFlow(LearningSpacesUiState())
    val uiState: StateFlow<LearningSpacesUiState> = _uiState.asStateFlow()

    init {
        viewModelScope.launch {
            courseContext.state.collect { context ->
                _uiState.update {
                    it.copy(
                        courses = context.courses,
                        selectedCourseId = context.selectedCourseId,
                    )
                }
            }
        }
    }

    fun loadCourses() {
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, errorMessage = null) }
            runCatching {
                courseRepository.listCourses(size = 100)
            }.onSuccess { courses ->
                courseContext.setCourses(courses)
                _uiState.update { it.copy(isLoading = false) }
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

    fun openCourse(courseId: String, onOpenCourse: (String) -> Unit) {
        courseContext.selectCourse(courseId)
        onOpenCourse(courseId)
    }

    fun previewDeleteCourse(courseId: String) {
        if (_uiState.value.isLoadingDeletePreview || _uiState.value.deletingCourseIds.contains(courseId)) {
            return
        }

        viewModelScope.launch {
            _uiState.update {
                it.copy(
                    isLoadingDeletePreview = true,
                    errorMessage = null,
                    deletePreview = null,
                )
            }
            runCatching {
                courseRepository.previewDeleteCourse(courseId)
            }.onSuccess { preview ->
                _uiState.update {
                    it.copy(
                        isLoadingDeletePreview = false,
                        deletePreview = preview,
                    )
                }
            }.onFailure { throwable ->
                _uiState.update {
                    it.copy(
                        isLoadingDeletePreview = false,
                        errorMessage = throwable.message ?: throwable::class.java.simpleName,
                    )
                }
            }
        }
    }

    fun dismissDeletePreview() {
        _uiState.update { it.copy(deletePreview = null) }
    }

    fun confirmDeleteCourse() {
        val preview = _uiState.value.deletePreview ?: return
        if (_uiState.value.deletingCourseIds.contains(preview.courseId)) {
            return
        }

        viewModelScope.launch {
            _uiState.update {
                it.copy(
                    deletingCourseIds = it.deletingCourseIds + preview.courseId,
                    deletePreview = null,
                    errorMessage = null,
                )
            }
            runCatching {
                courseRepository.deleteCourse(preview)
            }.onSuccess { deleted ->
                if (deleted.deleted) {
                    courseContext.removeCourse(deleted.courseId)
                }
                _uiState.update {
                    it.copy(
                        deletingCourseIds = it.deletingCourseIds - preview.courseId,
                    )
                }
                loadCourses()
            }.onFailure { throwable ->
                _uiState.update {
                    it.copy(
                        deletingCourseIds = it.deletingCourseIds - preview.courseId,
                        errorMessage = throwable.message ?: throwable::class.java.simpleName,
                    )
                }
            }
        }
    }
}
