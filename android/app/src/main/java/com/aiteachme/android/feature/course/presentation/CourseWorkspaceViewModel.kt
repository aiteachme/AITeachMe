package com.aiteachme.android.feature.course.presentation

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.aiteachme.android.core.di.AppServices
import com.aiteachme.android.core.network.dto.CourseItem
import com.aiteachme.android.core.network.dto.DocGenGetResponse
import com.aiteachme.android.core.network.dto.FileRecord
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class CourseWorkspaceUiState(
    val course: CourseItem? = null,
    val files: List<FileRecord> = emptyList(),
    val docs: DocGenGetResponse? = null,
    val buildPrompt: String = "",
    val isLoading: Boolean = false,
    val isBuilding: Boolean = false,
    val errorMessage: String? = null,
    val infoMessage: String? = null,
)

class CourseWorkspaceViewModel : ViewModel() {
    private val courseContext = AppServices.courseContextStore
    private val fileRepository = AppServices.fileRepository
    private val knowledgeRepository = AppServices.knowledgeRepository

    private val _uiState = MutableStateFlow(CourseWorkspaceUiState())
    val uiState: StateFlow<CourseWorkspaceUiState> = _uiState.asStateFlow()

    fun load(courseId: String) {
        viewModelScope.launch {
            val course = courseContext.state.value.courses.firstOrNull { it.courseId == courseId }
            _uiState.update {
                it.copy(
                    course = course,
                    isLoading = true,
                    errorMessage = null,
                    infoMessage = null,
                )
            }

            runCatching {
                val files = fileRepository.listCourseFiles(courseId).items
                val docs = knowledgeRepository.getDocs(courseId)
                files to docs
            }.onSuccess { (files, docs) ->
                _uiState.update {
                    it.copy(
                        files = files,
                        docs = docs,
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

    fun updateBuildPrompt(value: String) {
        _uiState.update { it.copy(buildPrompt = value, errorMessage = null) }
    }

    fun startBuild(courseId: String) {
        val state = _uiState.value
        if (state.isBuilding) {
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(isBuilding = true, errorMessage = null, infoMessage = null) }
            runCatching {
                knowledgeRepository.startDocsBuild(
                    courseId = courseId,
                    prompt = state.buildPrompt,
                    fileIds = state.files.filter { it.markdownReady }.map { it.id }.takeIf { it.isNotEmpty() },
                    confirmedPlanId = state.docs?.confirmedPlanId,
                )
            }.onSuccess { data ->
                _uiState.update {
                    it.copy(
                        isBuilding = false,
                        infoMessage = "已提交构建请求，准备 ${data.readyFileCount} 份可用资料。",
                    )
                }
                load(courseId)
            }.onFailure { throwable ->
                _uiState.update {
                    it.copy(
                        isBuilding = false,
                        errorMessage = throwable.message ?: throwable::class.java.simpleName,
                    )
                }
            }
        }
    }
}
