package com.aiteachme.android.core.data.repository

import com.aiteachme.android.core.network.AiTeachMeApi
import com.aiteachme.android.core.network.dto.AuthSessionData
import com.aiteachme.android.core.network.dto.LoginRequest
import com.aiteachme.android.core.network.dto.RegisterRequest
import com.aiteachme.android.core.network.dto.SendEmailCodeData
import com.aiteachme.android.core.network.dto.SendEmailCodeRequest
import com.aiteachme.android.core.session.SessionStore

class AuthRepository(
    private val api: AiTeachMeApi,
    private val sessionStore: SessionStore,
) {
    suspend fun currentUser(): AuthSessionData {
        val response = api.currentUser()
        return response.requireData().also(::saveSessionCredentials)
    }

    suspend fun login(email: String, password: String): AuthSessionData {
        val response = api.login(LoginRequest(email = email, password = password))
        val session = response.requireData()
        saveSessionCredentials(session)
        return session
    }

    suspend fun register(email: String, password: String, verificationCode: String): AuthSessionData {
        val response = api.register(
            RegisterRequest(
                email = email,
                password = password,
                verificationCode = verificationCode,
            ),
        )
        val session = response.requireData()
        saveSessionCredentials(session)
        return session
    }

    suspend fun sendEmailCode(email: String): SendEmailCodeData {
        val response = api.sendEmailCode(SendEmailCodeRequest(email = email))
        return response.requireData()
    }

    suspend fun logout(): AuthSessionData {
        val response = api.logout()
        val session = response.requireData()
        saveSessionCredentials(session)
        return session
    }

    private fun saveSessionCredentials(session: AuthSessionData) {
        sessionStore.saveAccessToken(session.accessToken)
        sessionStore.saveCsrfToken(session.csrfToken)
    }

    private fun <T> com.aiteachme.android.core.network.dto.ApiResponse<T>.requireData(): T {
        if (code != 0) {
            throw IllegalStateException(message.ifBlank { "请求失败" })
        }
        return data ?: throw IllegalStateException(message.ifBlank { "响应数据为空" })
    }
}
