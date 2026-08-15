package com.aiteachme.android.core.network

import com.aiteachme.android.core.session.SessionStore
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import java.util.concurrent.TimeUnit

object NetworkModule {
    private const val READ_TIMEOUT_HEADER = "X-AiTeachMe-Read-Timeout-Seconds"
    private const val ANDROID_ORIGIN = "aiteachme://android"
    private val SAFE_METHODS = setOf("GET", "HEAD", "OPTIONS")

    fun createHttpClient(
        sessionStore: SessionStore? = null,
        readTimeoutSeconds: Long = 60,
    ): OkHttpClient {
        val logging = HttpLoggingInterceptor().apply {
            level = HttpLoggingInterceptor.Level.BASIC
        }

        return OkHttpClient.Builder()
            .connectTimeout(30, TimeUnit.SECONDS)
            .readTimeout(readTimeoutSeconds, TimeUnit.SECONDS)
            .writeTimeout(60, TimeUnit.SECONDS)
            .addInterceptor { chain ->
                val request = chain.request()
                val requestReadTimeoutSeconds = request.header(READ_TIMEOUT_HEADER)
                    ?.toIntOrNull()
                    ?.coerceIn(1, 600)
                val builder = request
                    .newBuilder()
                    .removeHeader(READ_TIMEOUT_HEADER)
                    .header("X-Device-Key", sessionStore?.getDeviceKey() ?: "dk_android_fallback")
                val token = sessionStore?.getAccessToken()
                if (!token.isNullOrBlank()) {
                    builder.header("Authorization", "Bearer $token")
                }
                val csrfToken = sessionStore?.getCsrfToken()
                if (!csrfToken.isNullOrBlank() && request.method !in SAFE_METHODS) {
                    builder
                        .header("Origin", ANDROID_ORIGIN)
                        .header("X-CSRF-Token", csrfToken)
                }
                val requestChain = requestReadTimeoutSeconds
                    ?.let { chain.withReadTimeout(it, TimeUnit.SECONDS) }
                    ?: chain
                requestChain.proceed(builder.build())
            }
            .apply {
                if (sessionStore != null) {
                    cookieJar(PersistentCookieJar(sessionStore))
                }
            }
            .addInterceptor(logging)
            .build()
    }

    fun createApi(
        baseUrl: String = ApiConfig.defaultBaseUrl,
        sessionStore: SessionStore? = null,
    ): AiTeachMeApi {
        val normalizedBaseUrl = baseUrl.trimEnd('/') + "/"

        return Retrofit.Builder()
            .baseUrl(normalizedBaseUrl)
            .client(createHttpClient(sessionStore = sessionStore))
            .addConverterFactory(GsonConverterFactory.create())
            .build()
            .create(AiTeachMeApi::class.java)
    }
}
