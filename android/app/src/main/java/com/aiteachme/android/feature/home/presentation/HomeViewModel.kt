package com.aiteachme.android.feature.home.presentation

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.aiteachme.android.core.di.AppServices
import com.aiteachme.android.core.network.ApiConfig
import com.aiteachme.android.core.network.dto.CourseItem
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class HomeUiState(
    val apiBaseUrl: String = ApiConfig.defaultBaseUrl,
    val healthStatus: String = "未检查",
    val isCheckingHealth: Boolean = false,
    val isLoadingCourses: Boolean = false,
    val isCreatingCourse: Boolean = false,
    val courses: List<CourseItem> = emptyList(),
    val selectedCourseId: String? = null,
    val backgroundImagePath: String? = null,
    val errorMessage: String? = null,
    val infoMessage: String? = null,
) {
    val selectedCourse: CourseItem?
        get() = courses.firstOrNull { it.courseId == selectedCourseId }
}

class HomeViewModel : ViewModel() {
    private val api = AppServices.api
    private val coursesRepository = AppServices.courseRepository
    private val courseContext = AppServices.courseContextStore
    private val dailyWallpaperRepository = AppServices.dailyWallpaperRepository
    private val _uiState = MutableStateFlow(HomeUiState())
    val uiState: StateFlow<HomeUiState> = _uiState.asStateFlow()

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

    fun refresh() {
        checkHealth()
        loadCourses()
    }

    fun loadRandomWallpaper() {
        viewModelScope.launch {
            val wallpaper = dailyWallpaperRepository.loadRandom()
            if (wallpaper != null) {
                _uiState.update {
                    it.copy(backgroundImagePath = wallpaper.filePath)
                }
            }
        }
    }

    fun checkHealth() {
        viewModelScope.launch {
            _uiState.update { it.copy(isCheckingHealth = true, errorMessage = null) }

            runCatching { api.health() }
                .onSuccess { response ->
                    val status = if (response.code == 0) {
                        response.data?.status ?: "ok"
                    } else {
                        "错误 ${response.code}"
                    }
                    _uiState.update {
                        it.copy(
                            healthStatus = status,
                            isCheckingHealth = false,
                            errorMessage = response.message.takeIf { message ->
                                response.code != 0 && message.isNotBlank()
                            },
                        )
                    }
                }
                .onFailure { throwable ->
                    _uiState.update {
                        it.copy(
                            healthStatus = "连接失败",
                            isCheckingHealth = false,
                            errorMessage = throwable.message ?: throwable::class.java.simpleName,
                        )
                    }
                }
        }
    }

    fun loadCourses() {
        viewModelScope.launch {
            _uiState.update { it.copy(isLoadingCourses = true, errorMessage = null) }

            runCatching { coursesRepository.listCourses(size = 100) }
                .onSuccess { courseItems ->
                    courseContext.setCourses(courseItems)
                    _uiState.update {
                        it.copy(
                            isLoadingCourses = false,
                            infoMessage = if (courseItems.isEmpty()) "还没有学科，可以先新建一个。" else null,
                        )
                    }
                }
                .onFailure { throwable ->
                    _uiState.update {
                        it.copy(
                            isLoadingCourses = false,
                            errorMessage = throwable.message ?: throwable::class.java.simpleName,
                        )
                    }
                }
        }
    }

    fun selectCourse(courseId: String) {
        courseContext.selectCourse(courseId)
    }

    fun createDraftCourse(onCreated: (String) -> Unit = {}) {
        if (_uiState.value.isCreatingCourse) {
            return
        }

        viewModelScope.launch {
            _uiState.update { it.copy(isCreatingCourse = true, errorMessage = null, infoMessage = null) }
            runCatching {
                coursesRepository.createDraftCourse()
            }.onSuccess { course ->
                courseContext.upsertCourse(course)
                _uiState.update {
                    it.copy(
                        isCreatingCourse = false,
                        infoMessage = "已创建学科草稿，请在构建对话中完成规划。",
                    )
                }
                onCreated(course.courseId)
            }.onFailure { throwable ->
                _uiState.update {
                    it.copy(
                        isCreatingCourse = false,
                        errorMessage = throwable.message ?: throwable::class.java.simpleName,
                    )
                }
            }
        }
    }
}
