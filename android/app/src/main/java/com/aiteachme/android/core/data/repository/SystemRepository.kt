package com.aiteachme.android.core.data.repository

import com.aiteachme.android.core.network.AiTeachMeApi
import com.aiteachme.android.core.network.dto.ApiResponse
import com.aiteachme.android.core.network.dto.FeedbackSubmitRequest
import com.aiteachme.android.core.network.dto.FeedbackSubmitResponse
import com.aiteachme.android.core.network.dto.SettingsOverviewData

class SystemRepository(
    private val api: AiTeachMeApi,
) {
    suspend fun getSettings(): SettingsOverviewData {
        return api.getSystemSettings()
            .requireData("系统设置加载失败")
    }

    suspend fun submitFeedback(content: String, scene: String = "android_course_settings"): FeedbackSubmitResponse {
        return api.submitFeedback(
            FeedbackSubmitRequest(
                content = content,
                scene = scene,
            ),
        ).requireData("反馈提交失败")
    }

    private fun <T> ApiResponse<T>.requireData(fallbackMessage: String): T {
        if (code != 0) {
            throw IllegalStateException(message.ifBlank { fallbackMessage })
        }
        return data ?: throw IllegalStateException(message.ifBlank { fallbackMessage })
    }
}
