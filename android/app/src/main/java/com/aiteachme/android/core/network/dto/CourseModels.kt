package com.aiteachme.android.core.network.dto

import com.google.gson.annotations.SerializedName

data class PageRequest(
    val page: Int = 1,
    val size: Int = 20,
)

data class PaginatedData<T>(
    val items: List<T> = emptyList(),
    val page: Int = 1,
    val size: Int = 20,
    val total: Int = 0,
    val pages: Int = 0,
)

data class CourseItem(
    @SerializedName("course_id")
    val courseId: String,
    val name: String,
    val description: String = "",
    @SerializedName("user_intent")
    val userIntent: String = "",
    @SerializedName("icon_key")
    val iconKey: String? = null,
    @SerializedName("created_at")
    val createdAt: String = "",
    @SerializedName("updated_at")
    val updatedAt: String = "",
)
