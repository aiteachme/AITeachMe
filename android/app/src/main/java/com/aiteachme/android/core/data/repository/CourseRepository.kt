package com.aiteachme.android.core.data.repository

import com.aiteachme.android.core.network.AiTeachMeApi
import com.aiteachme.android.core.network.dto.CourseItem
import com.aiteachme.android.core.network.dto.PageRequest

class CourseRepository(
    private val api: AiTeachMeApi,
) {
    suspend fun listCourses(page: Int = 1, size: Int = 20): List<CourseItem> {
        val response = api.listCourses(PageRequest(page = page, size = size))
        if (response.code != 0) {
            throw IllegalStateException(response.message.ifBlank { "课程列表加载失败" })
        }
        return response.data?.items.orEmpty()
    }

    suspend fun createDraftCourse(): CourseItem {
        val response = api.createDraftCourse()
        if (response.code != 0) {
            throw IllegalStateException(response.message.ifBlank { "课程创建失败" })
        }
        return response.data ?: throw IllegalStateException("课程创建响应为空")
    }
}
