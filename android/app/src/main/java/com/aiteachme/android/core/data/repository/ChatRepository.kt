package com.aiteachme.android.core.data.repository

import com.aiteachme.android.core.network.AiTeachMeApi
import com.aiteachme.android.core.network.ApiConfig
import com.aiteachme.android.core.network.NetworkModule
import com.aiteachme.android.core.network.dto.ApiResponse
import com.aiteachme.android.core.network.dto.ChatDoneData
import com.aiteachme.android.core.network.dto.ChatErrorData
import com.aiteachme.android.core.network.dto.ChatListRequest
import com.aiteachme.android.core.network.dto.ChatMessageItem
import com.aiteachme.android.core.network.dto.ChatSendRequest
import com.aiteachme.android.core.network.dto.ChatSessionCreateRequest
import com.aiteachme.android.core.network.dto.ChatSessionDeleteRequest
import com.aiteachme.android.core.network.dto.ChatSessionItem
import com.aiteachme.android.core.network.dto.ChatSessionListRequest
import com.aiteachme.android.core.network.dto.ChatStatusData
import com.aiteachme.android.core.network.dto.ChatStreamResult
import com.aiteachme.android.core.session.SessionStore
import com.google.gson.Gson
import com.google.gson.JsonObject
import com.google.gson.JsonParser
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.IOException
import java.net.URLEncoder
import kotlin.coroutines.coroutineContext

enum class ChatConversationScope {
    Global,
    Course,
}

class ChatStreamException(
    message: String,
    val errorCode: String? = null,
) : IOException(message)

class ChatRepository(
    private val api: AiTeachMeApi,
    sessionStore: SessionStore,
    baseUrl: String = ApiConfig.defaultBaseUrl,
    private val client: OkHttpClient = NetworkModule.createHttpClient(
        sessionStore = sessionStore,
        readTimeoutSeconds = 0,
    ),
) {
    private val gson = Gson()
    private val normalizedBaseUrl = baseUrl.trimEnd('/')

    suspend fun sendGlobalMessage(
        request: ChatSendRequest,
        onToken: suspend (String) -> Unit,
        onStatus: suspend (ChatStatusData) -> Unit,
        onDone: suspend (ChatDoneData) -> Unit,
    ): ChatStreamResult {
        return sendMessage(
            scope = ChatConversationScope.Global,
            courseId = null,
            request = request,
            onToken = onToken,
            onStatus = onStatus,
            onDone = onDone,
        )
    }

    suspend fun sendMessage(
        scope: ChatConversationScope,
        courseId: String?,
        request: ChatSendRequest,
        onToken: suspend (String) -> Unit,
        onStatus: suspend (ChatStatusData) -> Unit,
        onDone: suspend (ChatDoneData) -> Unit,
    ): ChatStreamResult = withContext(Dispatchers.IO) {
        val httpRequest = Request.Builder()
            .url(sendUrl(scope = scope, courseId = courseId))
            .header("Accept", "text/event-stream")
            .header("Cache-Control", "no-cache")
            .post(gson.toJson(request).toRequestBody(JSON_MEDIA_TYPE))
            .build()
        val call = client.newCall(httpRequest)
        val cancellationHandle = coroutineContext[Job]?.invokeOnCompletion { cause ->
            if (cause is CancellationException) {
                call.cancel()
            }
        }

        var receivedToken = false
        var sawDone = false
        var donePayload: ChatDoneData? = null

        try {
            call.execute().use { response ->
                if (!response.isSuccessful) {
                    throw IOException(parseHttpError(response.code, response.body?.string().orEmpty()))
                }
                val body = response.body ?: throw IOException("Stream response body is empty.")
                body.charStream().buffered().use { reader ->
                    var eventName = "message"
                    val dataLines = mutableListOf<String>()

                    suspend fun dispatchCurrentEvent() {
                        if (eventName == "message" && dataLines.isEmpty()) {
                            return
                        }
                        val rawEventName = eventName
                        val rawData = dataLines.joinToString("\n")
                        eventName = "message"
                        dataLines.clear()
                        if (rawData.isBlank()) {
                            return
                        }
                        if (rawData.trim() == "[DONE]") {
                            sawDone = true
                            return
                        }

                        val payload = parseJsonObject(rawData) ?: return
                        when (normalizeSseEvent(eventName = rawEventName, payload = payload)) {
                            "token" -> {
                                val content = payload.stringOrNull("content").orEmpty()
                                if (content.isNotEmpty()) {
                                    receivedToken = true
                                    onToken(content)
                                }
                            }
                            "done" -> {
                                val done = gson.fromJson(payload, ChatDoneData::class.java)
                                sawDone = true
                                donePayload = done
                                onDone(done)
                            }
                            "error" -> {
                                val error = gson.fromJson(payload, ChatErrorData::class.java)
                                throw ChatStreamException(
                                    message = error.detail ?: error.message ?: "Send message failed.",
                                    errorCode = error.errorCode,
                                )
                            }
                            "status" -> onStatus(gson.fromJson(payload, ChatStatusData::class.java))
                        }
                    }

                    while (true) {
                        coroutineContext.ensureActive()
                        val line = reader.readLine() ?: break
                        val normalizedLine = line.trimEnd('\r')
                        when {
                            normalizedLine.isEmpty() -> dispatchCurrentEvent()
                            normalizedLine.startsWith(":") -> Unit
                            normalizedLine.startsWith("event:") -> {
                                eventName = normalizedLine.substringAfter("event:").trim().ifBlank { "message" }
                            }
                            normalizedLine.startsWith("data:") -> {
                                dataLines += normalizedLine.substringAfter("data:").trimStart()
                            }
                        }
                    }
                    if (dataLines.isNotEmpty()) {
                        dispatchCurrentEvent()
                    }
                }
            }
        } catch (error: IOException) {
            coroutineContext.ensureActive()
            throw error
        } finally {
            cancellationHandle?.dispose()
        }

        ChatStreamResult(
            receivedToken = receivedToken,
            sawDone = sawDone,
            done = donePayload,
        )
    }

    suspend fun listSessions(
        scope: ChatConversationScope,
        courseId: String?,
    ): List<ChatSessionItem> {
        val request = ChatSessionListRequest(size = 30)
        val response = when (scope) {
            ChatConversationScope.Global -> api.listGlobalChatSessions(request)
            ChatConversationScope.Course -> api.listCourseChatSessions(
                courseId = requireCourseId(courseId),
                request = request,
            )
        }
        return response.requireData("Failed to load chat sessions.").items
    }

    suspend fun createSession(
        scope: ChatConversationScope,
        courseId: String?,
        title: String? = null,
    ): ChatSessionItem {
        val request = ChatSessionCreateRequest(
            title = title,
            source = when (scope) {
                ChatConversationScope.Global -> "android_global_chat"
                ChatConversationScope.Course -> "android_course_chat"
            },
        )
        val response = when (scope) {
            ChatConversationScope.Global -> api.createGlobalChatSession(request)
            ChatConversationScope.Course -> api.createCourseChatSession(
                courseId = requireCourseId(courseId),
                request = request,
            )
        }
        return response.requireData("Failed to create chat session.").session
    }

    suspend fun deleteSession(
        scope: ChatConversationScope,
        courseId: String?,
        sessionId: String,
    ) {
        val request = ChatSessionDeleteRequest(sessionId = sessionId)
        val response = when (scope) {
            ChatConversationScope.Global -> api.deleteGlobalChatSession(request)
            ChatConversationScope.Course -> api.deleteCourseChatSession(
                courseId = requireCourseId(courseId),
                request = request,
            )
        }
        response.requireData("Failed to delete chat session.")
    }

    suspend fun listMessages(
        scope: ChatConversationScope,
        courseId: String?,
        sessionId: String,
    ): List<ChatMessageItem> {
        val request = ChatListRequest(sessionId = sessionId, size = 80)
        val response = when (scope) {
            ChatConversationScope.Global -> api.listGlobalChatMessages(request)
            ChatConversationScope.Course -> api.listCourseChatMessages(
                courseId = requireCourseId(courseId),
                request = request,
            )
        }
        return response.requireData("Failed to load chat messages.").items
    }

    private fun parseHttpError(statusCode: Int, rawBody: String): String {
        val fallback = "Request failed: $statusCode"
        if (rawBody.isBlank()) {
            return fallback
        }
        val payload = parseJsonObject(rawBody) ?: return rawBody.ifBlank { fallback }
        return payload.stringOrNull("detail")
            ?: payload.stringOrNull("message")
            ?: fallback
    }

    private fun parseJsonObject(rawData: String): JsonObject? {
        return runCatching {
            JsonParser.parseString(rawData).asJsonObject
        }.getOrNull()
    }

    private fun normalizeSseEvent(
        eventName: String,
        payload: JsonObject,
    ): String {
        return when (eventName) {
            "token", "done", "error", "status" -> eventName
            else -> when {
                payload.has("content") -> "token"
                payload.has("turn_id") || payload.has("contexts") -> "done"
                payload.has("error_code") || payload.has("detail") -> "error"
                payload.has("stage") || payload.has("step") || payload.has("elapsed_ms") -> "status"
                else -> "status"
            }
        }
    }

    private fun sendUrl(
        scope: ChatConversationScope,
        courseId: String?,
    ): String {
        return when (scope) {
            ChatConversationScope.Global -> "$normalizedBaseUrl/api/v1/chats/send"
            ChatConversationScope.Course -> {
                val encodedCourseId = encodePathSegment(requireCourseId(courseId))
                "$normalizedBaseUrl/api/v1/courses/$encodedCourseId/chats/send"
            }
        }
    }

    private fun requireCourseId(courseId: String?): String {
        return courseId?.takeIf { it.isNotBlank() }
            ?: throw IllegalStateException("Please select a course first.")
    }

    private fun encodePathSegment(value: String): String {
        return URLEncoder.encode(value, Charsets.UTF_8.name()).replace("+", "%20")
    }

    private fun JsonObject.stringOrNull(name: String): String? {
        val element = get(name) ?: return null
        if (element.isJsonNull) {
            return null
        }
        return element.asString?.takeIf { it.isNotBlank() }
    }

    private fun <T> ApiResponse<T>.requireData(fallbackMessage: String): T {
        if (code != 0) {
            throw IllegalStateException(message.ifBlank { fallbackMessage })
        }
        return data ?: throw IllegalStateException(message.ifBlank { fallbackMessage })
    }

    private companion object {
        val JSON_MEDIA_TYPE = "application/json; charset=utf-8".toMediaType()
    }
}
