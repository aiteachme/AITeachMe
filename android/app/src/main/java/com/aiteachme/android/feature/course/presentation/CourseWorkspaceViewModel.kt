package com.aiteachme.android.feature.course.presentation

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.aiteachme.android.core.di.AppServices
import com.aiteachme.android.core.network.dto.BuildPlannerPlanResponse
import com.aiteachme.android.core.network.dto.BuildPlannerSessionResponse
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
    val plannerSession: BuildPlannerSessionResponse? = null,
    val plannerPreviewPlan: BuildPlannerPlanResponse? = null,
    val plannerStreamingPreview: String = "",
    val plannerStatus: String? = null,
    val buildPrompt: String = "",
    val isLoading: Boolean = false,
    val isPlanning: Boolean = false,
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

    fun openBuild(courseId: String, initialPrompt: String?) {
        val prompt = initialPrompt?.trim().orEmpty()
        viewModelScope.launch {
            val loaded = loadWorkspace(courseId, prompt.takeIf { it.isNotBlank() })
            if (loaded && prompt.isNotBlank()) {
                startPlannerInternal(courseId = courseId, prompt = prompt)
            }
        }
    }

    fun load(courseId: String) {
        viewModelScope.launch {
            loadWorkspace(courseId, null)
        }
    }

    fun updateBuildPrompt(value: String) {
        _uiState.update { it.copy(buildPrompt = value, errorMessage = null) }
    }

    fun startBuild(courseId: String, onBuildStarted: (() -> Unit)? = null) {
        val state = _uiState.value
        if (state.isBuilding || state.isPlanning) {
            return
        }
        val plan = state.plannerPreviewPlan ?: state.plannerSession?.latestPlan
        val plannerSessionId = state.plannerSession?.sessionId
            ?: plan?.plannerSessionId
            ?: state.docs?.plannerSessionId
        val existingConfirmedPlanId = plan?.confirmedPlanId ?: state.docs?.confirmedPlanId
        if (plannerSessionId.isNullOrBlank() && existingConfirmedPlanId.isNullOrBlank()) {
            _uiState.update { it.copy(errorMessage = "请先生成构建规划，再开始构建。") }
            return
        }
        if (plan != null && plan.chapterPlan.isEmpty()) {
            _uiState.update { it.copy(errorMessage = "当前规划缺少章节大纲，请先重新规划。") }
            return
        }

        viewModelScope.launch {
            _uiState.update {
                it.copy(
                    isBuilding = true,
                    plannerStatus = "方案已确认，正在创建知识文档构建任务...",
                    errorMessage = null,
                    infoMessage = null,
                )
            }
            runCatching {
                val confirmed = if (!plannerSessionId.isNullOrBlank()) {
                    knowledgeRepository.confirmPlannerSession(
                        courseId = courseId,
                        sessionId = plannerSessionId,
                    )
                } else {
                    null
                }
                val confirmedPlanId = confirmed?.confirmedPlanId
                    ?: existingConfirmedPlanId
                    ?: throw IllegalStateException("确认构建方案失败，缺少 confirmed_plan_id。")
                knowledgeRepository.startDocsBuild(
                    courseId = courseId,
                    prompt = confirmed?.userPrompt?.takeIf { it.isNotBlank() }
                        ?: plan?.userPrompt?.takeIf { it.isNotBlank() }
                        ?: state.buildPrompt,
                    fileIds = state.files.filter { it.markdownReady }.map { it.id }.takeIf { it.isNotEmpty() },
                    confirmedPlanId = confirmedPlanId,
                )
            }.onSuccess { data ->
                _uiState.update {
                    it.copy(
                        isBuilding = false,
                        plannerStatus = "知识文档构建已启动。",
                        infoMessage = "已开始构建知识文档，准备 ${data.readyFileCount} 份可用资料。",
                    )
                }
                onBuildStarted?.invoke()
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

    fun startPlanner(courseId: String) {
        val prompt = _uiState.value.buildPrompt.trim()
        if (prompt.isBlank()) {
            _uiState.update { it.copy(errorMessage = "先输入你希望构建的课程目标。") }
            return
        }
        viewModelScope.launch {
            startPlannerInternal(courseId = courseId, prompt = prompt)
        }
    }

    private suspend fun loadWorkspace(courseId: String, prompt: String?): Boolean {
        courseContext.selectCourse(courseId)
        val course = courseContext.state.value.courses.firstOrNull { it.courseId == courseId }
        _uiState.update {
            it.copy(
                course = course,
                buildPrompt = prompt ?: it.buildPrompt,
                isLoading = true,
                errorMessage = null,
                infoMessage = null,
            )
        }

        return runCatching {
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
        }.isSuccess
    }

    private suspend fun startPlannerInternal(courseId: String, prompt: String) {
        if (_uiState.value.isPlanning) {
            return
        }

        val readyFileIds = _uiState.value.files.filter { it.markdownReady }.map { it.id }
        _uiState.update {
            it.copy(
                buildPrompt = prompt,
                isPlanning = true,
                plannerSession = null,
                plannerPreviewPlan = null,
                plannerStreamingPreview = "",
                plannerStatus = "正在理解目标和资料，整理思考过程...",
                errorMessage = null,
                infoMessage = null,
            )
        }
        runCatching {
            knowledgeRepository.createPlannerSessionStream(
                courseId = courseId,
                fileIds = readyFileIds,
                userPrompt = prompt,
                onToken = { token ->
                    _uiState.update {
                        it.copy(
                            plannerStreamingPreview = it.plannerStreamingPreview + token,
                            plannerStatus = it.plannerStatus ?: "正在生成构建规划...",
                        )
                    }
                },
                onStatus = { status ->
                    _uiState.update {
                        it.copy(
                            plannerStatus = status.detail?.takeIf { detail -> detail.isNotBlank() } ?: it.plannerStatus,
                            plannerPreviewPlan = status.planPreview ?: it.plannerPreviewPlan,
                        )
                    }
                },
            )
        }.onSuccess { session ->
            _uiState.update {
                it.copy(
                    plannerSession = session,
                    plannerPreviewPlan = session.latestPlan ?: it.plannerPreviewPlan,
                    plannerStatus = "构建方案已生成。",
                    isPlanning = false,
                    infoMessage = "已生成构建规划，可继续调整或开始构建知识文档。",
                )
            }
        }.onFailure { throwable ->
            _uiState.update {
                it.copy(
                    isPlanning = false,
                    plannerStatus = null,
                    errorMessage = throwable.message ?: throwable::class.java.simpleName,
                )
            }
        }
    }
}
