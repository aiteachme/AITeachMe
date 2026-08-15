package com.aiteachme.android.core.network.dto

import com.google.gson.annotations.SerializedName

data class LoginRequest(
    val email: String,
    val password: String,
)

data class RegisterRequest(
    val email: String,
    val password: String,
    @SerializedName("verification_code")
    val verificationCode: String,
)

data class SendEmailCodeRequest(
    val email: String,
)

class LogoutRequest

data class SendEmailCodeData(
    @SerializedName("expires_in_s")
    val expiresInSeconds: Int = 0,
    @SerializedName("resend_after_s")
    val resendAfterSeconds: Int = 0,
)

data class AuthSessionData(
    @SerializedName("auth_enabled")
    val authEnabled: Boolean = false,
    @SerializedName("auth_ready")
    val authReady: Boolean = false,
    @SerializedName("token_type")
    val tokenType: String = "bearer",
    @SerializedName("access_token")
    val accessToken: String? = null,
    @SerializedName("csrf_token")
    val csrfToken: String? = null,
    @SerializedName("current_user")
    val currentUser: RuntimeUser? = null,
)

data class RuntimeUser(
    @SerializedName("user_id")
    val userId: String,
    val email: String? = null,
    @SerializedName("is_local")
    val isLocal: Boolean = false,
    @SerializedName("device_key")
    val deviceKey: String? = null,
    @SerializedName("is_authenticated")
    val isAuthenticated: Boolean = false,
)
