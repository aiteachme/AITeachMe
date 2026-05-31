package com.aiteachme.android.core.data.repository

import com.aiteachme.android.core.network.ApiConfig
import com.aiteachme.android.core.network.AiTeachMeApi
import com.aiteachme.android.core.network.NetworkModule
import com.aiteachme.android.core.network.dto.BuildPlannerCreateRequest
import com.aiteachme.android.core.network.dto.BuildPlannerConfirmResponse
import com.aiteachme.android.core.network.dto.BuildPlannerDoneData
import com.aiteachme.android.core.network.dto.BuildPlannerSessionResponse
import com.aiteachme.android.core.network.dto.BuildPlannerStatusData
import com.aiteachme.android.core.network.dto.ChatErrorData
import com.aiteachme.android.core.network.dto.DocGenBuildData
import com.aiteachme.android.core.network.dto.DocGenBuildRequest
import com.aiteachme.android.core.network.dto.DocGenGetResponse
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

class KnowledgeRepository(
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

    suspend fun confirmPlannerSession(
        courseId: String,
        sessionId: String,
    ): BuildPlannerConfirmResponse {
        val response = api.confirmBuildPlannerSession(courseId = courseId, sessionId = sessionId)
        if (response.code != 0) {
            throw IllegalStateException(response.message.ifBlank { "确认构建方案失败" })
        }
        return response.data ?: throw IllegalStateException("确认构建方案响应为空")
    }

    suspend fun createPlannerSessionStream(
        courseId: String,
        fileIds: List<String>,
        userPrompt: String,
        model: String? = null,
        onToken: suspend (String) -> Unit,
        onStatus: suspend (BuildPlannerStatusData) -> Unit,
    ): BuildPlannerSessionResponse = withContext(Dispatchers.IO) {
        val request = BuildPlannerCreateRequest(
            fileIds = fileIds.takeIf { it.isNotEmpty() },
            userPrompt = userPrompt,
            model = model?.takeIf { it.isNotBlank() },
        )
        val httpRequest = Request.Builder()
            .url("$normalizedBaseUrl/api/v1/courses/${encodePathSegment(courseId)}/knowledge/build/plans/stream")
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

        var sawDone = false
        var session: BuildPlannerSessionResponse? = null

        try {
            call.execute().use { response ->
                if (!response.isSuccessful) {
                    throw IOException(parseHttpError(response.code, response.body?.string().orEmpty()))
                }
                val body = response.body ?: throw IOException("Planner stream response body is empty.")
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
                        val payload = parseJsonObject(rawData) ?: return
                        when (normalizeSseEvent(rawEventName, payload)) {
                            "token" -> {
                                val content = payload.stringOrNull("content").orEmpty()
                                if (content.isNotEmpty()) {
                                    onToken(content)
                                }
                            }
                            "status" -> onStatus(gson.fromJson(payload, BuildPlannerStatusData::class.java))
                            "done" -> {
                                sawDone = true
                                session = gson.fromJson(payload, BuildPlannerDoneData::class.java).session
                            }
                            "error" -> {
                                val error = gson.fromJson(payload, ChatErrorData::class.java)
                                throw IOException(error.detail ?: error.message ?: "Planner stream failed.")
                            }
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

        if (!sawDone || session == null) {
            throw IOException("主模型调用失败，未生成构建规划。")
        }
        session ?: throw IOException("主模型调用失败，未生成构建规划。")
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

    private fun normalizeSseEvent(eventName: String, payload: JsonObject): String {
        return when (eventName) {
            "token", "status", "done", "error" -> eventName
            else -> when {
                payload.has("content") -> "token"
                payload.has("session") -> "done"
                payload.has("error_code") || payload.has("detail") && !payload.has("stage") -> "error"
                else -> "status"
            }
        }
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

    private companion object {
        val JSON_MEDIA_TYPE = "application/json; charset=utf-8".toMediaType()
    }
}
