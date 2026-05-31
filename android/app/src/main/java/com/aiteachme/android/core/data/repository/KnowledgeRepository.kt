package com.aiteachme.android.core.data.repository

import com.aiteachme.android.core.network.AiTeachMeApi
import com.aiteachme.android.core.network.dto.DocGenBuildData
import com.aiteachme.android.core.network.dto.DocGenBuildRequest
import com.aiteachme.android.core.network.dto.DocGenGetResponse

class KnowledgeRepository(
    private val api: AiTeachMeApi,
) {
    suspend fun getDocs(courseId: String): DocGenGetResponse {
        val response = api.getKnowledgeDocs(courseId)
        if (response.code != 0) {
            throw IllegalStateException(response.message.ifBlank { "知识文档加载失败" })
        }
        return response.data ?: DocGenGetResponse()
    }

    suspend fun startDocsBuild(
        courseId: String,
        prompt: String?,
        fileIds: List<String>? = null,
        confirmedPlanId: String? = null,
    ): DocGenBuildData {
        val response = api.startKnowledgeBuild(
            courseId = courseId,
            request = DocGenBuildRequest(
                fileIds = fileIds,
                prompt = prompt?.takeIf { it.isNotBlank() },
                confirmedPlanId = confirmedPlanId,
            ),
        )
        if (response.code != 0) {
            throw IllegalStateException(response.message.ifBlank { "知识构建启动失败" })
        }
        return response.data ?: throw IllegalStateException("知识构建响应为空")
    }
}
