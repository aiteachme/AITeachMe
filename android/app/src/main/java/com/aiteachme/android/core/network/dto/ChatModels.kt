package com.aiteachme.android.core.network.dto

import com.google.gson.annotations.SerializedName

data class ChatSendRequest(
    val question: String,
    @SerializedName("session_id")
    val sessionId: String? = null,
    val scene: String? = null,
    val source: String? = null,
    val model: String? = null,
    @SerializedName("anchor_id")
    val anchorId: String? = null,
    @SerializedName("selected_text")
    val selectedText: String? = null,
    @SerializedName("selected_context")
    val selectedContext: String? = null,
    @SerializedName("source_chunk_id")
    val sourceChunkId: Int? = null,
    @SerializedName("attached_file_ids")
    val attachedFileIds: List<String> = emptyList(),
)

data class ChatListRequest(
    val page: Int = 1,
    val size: Int = 80,
    @SerializedName("session_id")
    val sessionId: String? = null,
)

data class ChatSessionListRequest(
    val page: Int = 1,
    val size: Int = 30,
    @SerializedName("include_all_courses")
    val includeAllCourses: Boolean = false,
)

data class ChatSessionCreateRequest(
    val title: String? = null,
    val source: String? = null,
)

data class ChatSessionDeleteRequest(
    @SerializedName("session_id")
    val sessionId: String,
)

data class ChatSessionItem(
    val id: String,
    val title: String = "",
    @SerializedName("course_id")
    val courseId: String? = null,
    @SerializedName("course_name")
    val courseName: String? = null,
    val source: String? = null,
    @SerializedName("anchor_id")
    val anchorId: String? = null,
    @SerializedName("selected_text")
    val selectedText: String? = null,
    @SerializedName("source_chunk_id")
    val sourceChunkId: Int? = null,
    @SerializedName("message_count")
    val messageCount: Int = 0,
    @SerializedName("created_at")
    val createdAt: String = "",
    @SerializedName("updated_at")
    val updatedAt: String = "",
    @SerializedName("last_message_at")
    val lastMessageAt: String = "",
)

data class ChatSessionCreateData(
    val session: ChatSessionItem,
)

data class ChatSessionDeleteData(
    val deleted: Boolean = false,
    @SerializedName("deleted_message_count")
    val deletedMessageCount: Int = 0,
)

data class ChatMessageItem(
    val id: Long,
    @SerializedName("turn_id")
    val turnId: String = "",
    val role: String = "",
    val content: String = "",
    @SerializedName("created_at")
    val createdAt: String = "",
)

data class ChatDoneData(
    @SerializedName("turn_id")
    val turnId: String? = null,
    @SerializedName("session_id")
    val sessionId: String? = null,
    @SerializedName("session_title")
    val sessionTitle: String? = null,
    @SerializedName("elapsed_ms")
    val elapsedMs: Long? = null,
    @SerializedName("elapsed_s")
    val elapsedSeconds: Double? = null,
)

data class ChatStatusData(
    val stage: String? = null,
    val detail: String? = null,
    val step: String? = null,
    @SerializedName("session_id")
    val sessionId: String? = null,
    @SerializedName("session_title")
    val sessionTitle: String? = null,
    @SerializedName("elapsed_ms")
    val elapsedMs: Long? = null,
    @SerializedName("elapsed_s")
    val elapsedSeconds: Double? = null,
    @SerializedName("tool_name")
    val toolName: String? = null,
    @SerializedName("tool_display_name")
    val toolDisplayName: String? = null,
)

data class ChatErrorData(
    val detail: String? = null,
    val message: String? = null,
    @SerializedName("error_code")
    val errorCode: String? = null,
)

data class ChatStreamResult(
    val receivedToken: Boolean,
    val sawDone: Boolean,
    val done: ChatDoneData?,
)
