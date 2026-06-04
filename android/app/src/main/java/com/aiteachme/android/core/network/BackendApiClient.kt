package com.aiteachme.android.core.network

import com.aiteachme.android.core.network.generated.BackendApiEndpoint
import com.aiteachme.android.core.network.generated.BackendHttpMethod
import com.aiteachme.android.core.session.SessionStore
import com.google.gson.Gson
import com.google.gson.JsonElement
import com.google.gson.JsonObject
import com.google.gson.JsonParser
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import okhttp3.HttpUrl.Companion.toHttpUrl
import java.io.IOException
import java.net.URLEncoder
import kotlin.coroutines.coroutineContext

data class BackendSseEvent(
    val eventName: String,
    val payload: JsonElement?,
    val rawData: String,
)

class BackendApiException(
    message: String,
    val statusCode: Int? = null,
) : IOException(message)

class BackendApiClient(
    sessionStore: SessionStore,
    private val baseUrl: String = ApiConfig.defaultBaseUrl,
    private val client: OkHttpClient = NetworkModule.createHttpClient(
        sessionStore = sessionStore,
        readTimeoutSeconds = 0,
    ),
) {
    private val gson = Gson()

    suspend fun requestJson(
        endpoint: BackendApiEndpoint,
        pathParams: Map<String, String> = emptyMap(),
        query: Map<String, Any?> = emptyMap(),
        body: JsonElement? = null,
    ): JsonElement {
        val request = buildJsonRequest(endpoint, pathParams, query, body)
        return execute(request) { response ->
            val raw = response.body?.string().orEmpty()
            if (!response.isSuccessful) {
                throw BackendApiException(parseErrorBody(response.code, raw), response.code)
            }
            if (raw.isBlank()) {
                JsonObject()
            } else {
                JsonParser.parseString(raw)
            }
        }
    }

    suspend fun requestText(
        endpoint: BackendApiEndpoint,
        pathParams: Map<String, String> = emptyMap(),
        query: Map<String, Any?> = emptyMap(),
        body: JsonElement? = null,
    ): String {
        val request = buildJsonRequest(endpoint, pathParams, query, body)
        return execute(request) { response ->
            val raw = response.body?.string().orEmpty()
            if (!response.isSuccessful) {
                throw BackendApiException(parseErrorBody(response.code, raw), response.code)
            }
            raw
        }
    }

    suspend fun requestBytes(
        endpoint: BackendApiEndpoint,
        pathParams: Map<String, String> = emptyMap(),
        query: Map<String, Any?> = emptyMap(),
        body: JsonElement? = null,
    ): ByteArray {
        val request = buildJsonRequest(endpoint, pathParams, query, body)
        return execute(request) { response ->
            val bytes = response.body?.bytes() ?: ByteArray(0)
            if (!response.isSuccessful) {
                throw BackendApiException("请求失败（${response.code}）", response.code)
            }
            bytes
        }
    }

    suspend fun requestMultipartJson(
        endpoint: BackendApiEndpoint,
        pathParams: Map<String, String> = emptyMap(),
        query: Map<String, Any?> = emptyMap(),
        fields: Map<String, String?> = emptyMap(),
        parts: List<MultipartBody.Part> = emptyList(),
    ): JsonElement {
        val request = buildMultipartRequest(endpoint, pathParams, query, fields, parts)
        return execute(request) { response ->
            val raw = response.body?.string().orEmpty()
            if (!response.isSuccessful) {
                throw BackendApiException(parseErrorBody(response.code, raw), response.code)
            }
            if (raw.isBlank()) {
                JsonObject()
            } else {
                JsonParser.parseString(raw)
            }
        }
    }

    suspend fun streamSse(
        endpoint: BackendApiEndpoint,
        pathParams: Map<String, String> = emptyMap(),
        query: Map<String, Any?> = emptyMap(),
        body: JsonElement? = null,
        onEvent: suspend (BackendSseEvent) -> Unit,
    ) {
        val request = buildJsonRequest(endpoint, pathParams, query, body)
            .newBuilder()
            .header("Accept", "text/event-stream")
            .header("Cache-Control", "no-cache")
            .build()

        execute(request) { response ->
            if (!response.isSuccessful) {
                val raw = response.body?.string().orEmpty()
                throw BackendApiException(parseErrorBody(response.code, raw), response.code)
            }

            val streamBody = response.body ?: throw BackendApiException("响应流不可用，请重试。", response.code)
            streamBody.charStream().buffered().use { reader ->
                var eventName = "message"
                val dataLines = mutableListOf<String>()

                suspend fun dispatch() {
                    if (eventName == "message" && dataLines.isEmpty()) {
                        return
                    }
                    val currentEventName = eventName
                    val rawData = dataLines.joinToString("\n")
                    eventName = "message"
                    dataLines.clear()
                    if (rawData.isBlank()) {
                        return
                    }
                    val payload = if (rawData.trim() == "[DONE]") {
                        null
                    } else {
                        runCatching { JsonParser.parseString(rawData) }.getOrNull()
                    }
                    onEvent(
                        BackendSseEvent(
                            eventName = currentEventName,
                            payload = payload,
                            rawData = rawData,
                        ),
                    )
                }

                while (true) {
                    coroutineContext.ensureActive()
                    val line = reader.readLine() ?: break
                    val normalizedLine = line.trimEnd('\r')
                    when {
                        normalizedLine.isEmpty() -> dispatch()
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
                    dispatch()
                }
            }
        }
    }

    fun buildUrl(
        endpoint: BackendApiEndpoint,
        pathParams: Map<String, String> = emptyMap(),
        query: Map<String, Any?> = emptyMap(),
    ): String {
        var resolvedPath = endpoint.path
        endpoint.pathParams.forEach { name ->
            val value = pathParams[name]
                ?: throw IllegalArgumentException("缺少路径参数：$name")
            val encodedValue = if (name.endsWith("_path")) {
                encodePath(value)
            } else {
                encodePathSegment(value)
            }
            resolvedPath = resolvedPath.replace("{$name}", encodedValue)
        }

        val builder = "${baseUrl.trimEnd('/')}$resolvedPath".toHttpUrl().newBuilder()
        query.forEach { (name, value) ->
            addQueryValue(builder, name, value)
        }
        return builder.build().toString()
    }

    private fun buildJsonRequest(
        endpoint: BackendApiEndpoint,
        pathParams: Map<String, String>,
        query: Map<String, Any?>,
        body: JsonElement?,
    ): Request {
        val requestBody = when {
            endpoint.hasRequestBody || body != null -> {
                gson.toJson(body ?: JsonObject()).toRequestBody(JSON_MEDIA_TYPE)
            }
            else -> null
        }
        return Request.Builder()
            .url(buildUrl(endpoint, pathParams, query))
            .methodForEndpoint(endpoint, requestBody)
            .build()
    }

    private fun buildMultipartRequest(
        endpoint: BackendApiEndpoint,
        pathParams: Map<String, String>,
        query: Map<String, Any?>,
        fields: Map<String, String?>,
        parts: List<MultipartBody.Part>,
    ): Request {
        val bodyBuilder = MultipartBody.Builder().setType(MultipartBody.FORM)
        fields.forEach { (name, value) ->
            if (value != null) {
                bodyBuilder.addFormDataPart(name, value)
            }
        }
        parts.forEach(bodyBuilder::addPart)
        return Request.Builder()
            .url(buildUrl(endpoint, pathParams, query))
            .methodForEndpoint(endpoint, bodyBuilder.build())
            .build()
    }

    private fun Request.Builder.methodForEndpoint(
        endpoint: BackendApiEndpoint,
        body: RequestBody?,
    ): Request.Builder {
        return when (endpoint.method) {
            BackendHttpMethod.GET -> get()
            BackendHttpMethod.POST -> post(body ?: EMPTY_JSON_BODY)
            BackendHttpMethod.PUT -> put(body ?: EMPTY_JSON_BODY)
            BackendHttpMethod.PATCH -> patch(body ?: EMPTY_JSON_BODY)
            BackendHttpMethod.DELETE -> if (body != null) delete(body) else delete()
        }
    }

    private suspend fun <T> execute(
        request: Request,
        consume: suspend (Response) -> T,
    ): T = withContext(Dispatchers.IO) {
        val call = client.newCall(request)
        val cancellationHandle = coroutineContext[Job]?.invokeOnCompletion { cause ->
            if (cause is CancellationException) {
                call.cancel()
            }
        }
        try {
            call.execute().use { response ->
                consume(response)
            }
        } catch (error: IOException) {
            coroutineContext.ensureActive()
            throw error
        } finally {
            cancellationHandle?.dispose()
        }
    }

    private fun addQueryValue(
        builder: okhttp3.HttpUrl.Builder,
        name: String,
        value: Any?,
    ) {
        when (value) {
            null -> Unit
            is Iterable<*> -> value.forEach { addQueryValue(builder, name, it) }
            is Array<*> -> value.forEach { addQueryValue(builder, name, it) }
            else -> builder.addQueryParameter(name, value.toString())
        }
    }

    private fun encodePathSegment(value: String): String {
        return URLEncoder.encode(value, Charsets.UTF_8.name()).replace("+", "%20")
    }

    private fun encodePath(value: String): String {
        return value.split('/').joinToString("/") { segment ->
            encodePathSegment(segment)
        }
    }

    private fun parseErrorBody(statusCode: Int, rawBody: String): String {
        val fallback = "请求失败（$statusCode）"
        if (rawBody.isBlank()) {
            return fallback
        }
        val payload = runCatching { JsonParser.parseString(rawBody).asJsonObject }.getOrNull()
        return payload?.get("detail")?.takeUnless { it.isJsonNull }?.asString?.takeIf { it.isNotBlank() }
            ?: payload?.get("message")?.takeUnless { it.isJsonNull }?.asString?.takeIf { it.isNotBlank() }
            ?: rawBody.ifBlank { fallback }
    }

    private companion object {
        val JSON_MEDIA_TYPE = "application/json; charset=utf-8".toMediaType()
        val EMPTY_JSON_BODY = "{}".toRequestBody(JSON_MEDIA_TYPE)
    }
}
