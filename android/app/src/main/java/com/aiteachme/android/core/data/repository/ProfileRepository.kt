package com.aiteachme.android.core.data.repository

import com.aiteachme.android.core.network.AiTeachMeApi
import com.aiteachme.android.core.network.dto.ApiResponse
import com.aiteachme.android.core.network.dto.MasteryOverviewResponse
import com.aiteachme.android.core.network.dto.ReviewTaskResponse
import com.aiteachme.android.core.network.dto.StudyPlanStepResponse

class ProfileRepository(
    private val api: AiTeachMeApi,
) {
    suspend fun getMasteryOverview(courseId: String): MasteryOverviewResponse {
        return api.getMasteryOverview(courseId)
            .requireData("学习画像加载失败")
    }

    suspend fun getStudyPlan(courseId: String): List<StudyPlanStepResponse> {
        return api.getStudyPlan(courseId)
            .requireData("学习计划加载失败")
    }

    suspend fun listReviewTasks(courseId: String): List<ReviewTaskResponse> {
        return api.listReviewTasks(courseId)
            .requireData("复习任务加载失败")
    }

    suspend fun completeReviewTask(courseId: String, taskId: Int): ReviewTaskResponse {
        return api.completeReviewTask(courseId = courseId, taskId = taskId)
            .requireData("复习任务完成失败")
    }

    private fun <T> ApiResponse<T>.requireData(fallbackMessage: String): T {
        if (code != 0) {
            throw IllegalStateException(message.ifBlank { fallbackMessage })
        }
        return data ?: throw IllegalStateException(message.ifBlank { fallbackMessage })
    }
}
