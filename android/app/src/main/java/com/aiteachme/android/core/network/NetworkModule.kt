package com.aiteachme.android.core.network

import com.aiteachme.android.core.session.SessionStore
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import java.util.concurrent.TimeUnit

object NetworkModule {
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
                val builder = chain.request()
                    .newBuilder()
                    .header("X-Device-Key", sessionStore?.getDeviceKey() ?: "dk_android_fallback")
                val token = sessionStore?.getAccessToken()
                if (!token.isNullOrBlank()) {
                    builder.header("Authorization", "Bearer $token")
                }
                chain.proceed(builder.build())
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
