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

data class CourseDeletePreviewRequest(
    @SerializedName("course_id")
    val courseId: String,
)

data class CourseDeleteRequest(
    @SerializedName("course_id")
    val courseId: String,
    val force: Boolean = true,
    @SerializedName("known_detail_counts")
    val knownDetailCounts: Map<String, Int>? = null,
)

data class CourseDeleteData(
    val deleted: Boolean = false,
    @SerializedName("course_id")
    val courseId: String = "",
    @SerializedName("deleted_counts")
    val deletedCounts: Map<String, Int> = emptyMap(),
)

data class CourseDeleteImpactItem(
    val key: String = "",
    val label: String = "",
    val count: Int = 0,
    val description: String = "",
)

data class CourseDeletePreviewData(
    @SerializedName("course_id")
    val courseId: String = "",
    @SerializedName("course_name")
    val courseName: String = "",
    @SerializedName("has_content")
    val hasContent: Boolean = false,
    @SerializedName("total_related_records")
    val totalRelatedRecords: Int = 0,
    @SerializedName("impact_items")
    val impactItems: List<CourseDeleteImpactItem> = emptyList(),
    @SerializedName("detail_counts")
    val detailCounts: Map<String, Int> = emptyMap(),
)
