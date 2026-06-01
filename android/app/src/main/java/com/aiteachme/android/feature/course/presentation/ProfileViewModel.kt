package com.aiteachme.android.feature.course.presentation

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.aiteachme.android.core.di.AppServices
import com.aiteachme.android.core.network.dto.MasteryOverviewResponse
import com.aiteachme.android.core.network.dto.ReviewTaskResponse
import com.aiteachme.android.core.network.dto.StudyPlanStepResponse
import kotlinx.coroutines.async
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class ProfileUiState(
    val isLoading: Boolean = false,
    val isCompletingReviewId: Int? = null,
    val mastery: MasteryOverviewResponse? = null,
    val studyPlan: List<StudyPlanStepResponse> = emptyList(),
    val reviews: List<ReviewTaskResponse> = emptyList(),
    val errorMessage: String? = null,
    val infoMessage: String? = null,
)

class ProfileViewModel : ViewModel() {
    private val profileRepository = AppServices.profileRepository
    private val _uiState = MutableStateFlow(ProfileUiState())
    val uiState: StateFlow<ProfileUiState> = _uiState.asStateFlow()

    fun load(courseId: String) {
        if (courseId.isBlank()) return
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, errorMessage = null, infoMessage = null) }
            runCatching {
                val mastery = async { profileRepository.getMasteryOverview(courseId) }
                val plan = async { profileRepository.getStudyPlan(courseId) }
                val reviews = async { profileRepository.listReviewTasks(courseId) }
                Triple(mastery.await(), plan.await(), reviews.await())
            }.onSuccess { (mastery, plan, reviews) ->
                _uiState.update {
                    it.copy(
                        isLoading = false,
                        mastery = mastery,
                        studyPlan = plan,
                        reviews = reviews,
                    )
                }
            }.onFailure { error ->
                _uiState.update {
                    it.copy(
                        isLoading = false,
                        errorMessage = error.message ?: error::class.java.simpleName,
                    )
                }
            }
        }
    }

    fun completeReview(courseId: String, taskId: Int) {
        if (courseId.isBlank() || taskId <= 0 || _uiState.value.isCompletingReviewId != null) return
        viewModelScope.launch {
            _uiState.update { it.copy(isCompletingReviewId = taskId, errorMessage = null, infoMessage = null) }
            runCatching {
                profileRepository.completeReviewTask(courseId = courseId, taskId = taskId)
            }.onSuccess { updated ->
                _uiState.update { state ->
                    state.copy(
                        isCompletingReviewId = null,
                        infoMessage = "复习任务已完成",
                        reviews = state.reviews.map { if (it.id == updated.id) updated else it }
                            .filterNot { it.id == taskId && it.status.equals("completed", ignoreCase = true) },
                    )
                }
                load(courseId)
            }.onFailure { error ->
                _uiState.update {
                    it.copy(
                        isCompletingReviewId = null,
                        errorMessage = error.message ?: error::class.java.simpleName,
                    )
                }
            }
        }
    }
}
