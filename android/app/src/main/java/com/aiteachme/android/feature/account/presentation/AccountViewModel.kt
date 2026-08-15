package com.aiteachme.android.feature.account.presentation

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.aiteachme.android.core.di.AppServices
import com.aiteachme.android.core.network.dto.RuntimeUser
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

enum class AuthMode {
    Login,
    Register,
}

data class AccountUiState(
    val authEnabled: Boolean? = null,
    val authReady: Boolean = false,
    val user: RuntimeUser? = null,
    val mode: AuthMode = AuthMode.Login,
    val email: String = "",
    val password: String = "",
    val verificationCode: String = "",
    val isLoading: Boolean = false,
    val isSubmitting: Boolean = false,
    val isSendingCode: Boolean = false,
    val errorMessage: String? = null,
    val infoMessage: String? = null,
)

class AccountViewModel : ViewModel() {
    private val auth = AppServices.authRepository
    private val _uiState = MutableStateFlow(AccountUiState())
    val uiState: StateFlow<AccountUiState> = _uiState.asStateFlow()

    fun loadSession() {
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, errorMessage = null) }
            runCatching {
                auth.currentUser()
            }.onSuccess { session ->
                _uiState.update {
                    it.copy(
                        authEnabled = session.authEnabled,
                        authReady = session.authReady,
                        user = session.currentUser,
                        isLoading = false,
                    )
                }
            }.onFailure { throwable ->
                _uiState.update {
                    it.copy(
                        authEnabled = false,
                        isLoading = false,
                        errorMessage = throwable.message ?: throwable::class.java.simpleName,
                    )
                }
            }
        }
    }

    fun setMode(mode: AuthMode) {
        _uiState.update {
            it.copy(
                mode = mode,
                password = "",
                verificationCode = "",
                errorMessage = null,
                infoMessage = null,
            )
        }
    }

    fun updateEmail(value: String) {
        _uiState.update { it.copy(email = value, errorMessage = null) }
    }

    fun updatePassword(value: String) {
        _uiState.update { it.copy(password = value, errorMessage = null) }
    }

    fun updateVerificationCode(value: String) {
        _uiState.update { it.copy(verificationCode = value, errorMessage = null) }
    }

    fun sendVerificationCode() {
        val email = _uiState.value.email.trim()
        if (email.isBlank()) {
            _uiState.update { it.copy(errorMessage = "请先输入邮箱。") }
            return
        }

        viewModelScope.launch {
            _uiState.update { it.copy(isSendingCode = true, errorMessage = null, infoMessage = null) }
            runCatching {
                auth.sendEmailCode(email)
            }.onSuccess { data ->
                _uiState.update {
                    it.copy(
                        isSendingCode = false,
                        infoMessage = "验证码已发送，有效期 ${data.expiresInSeconds} 秒。",
                    )
                }
            }.onFailure { throwable ->
                _uiState.update {
                    it.copy(
                        isSendingCode = false,
                        errorMessage = throwable.message ?: throwable::class.java.simpleName,
                    )
                }
            }
        }
    }

    fun submit() {
        val state = _uiState.value
        val email = state.email.trim()
        val password = state.password.trim()
        val code = state.verificationCode.trim()

        if (!email.contains("@") || password.length < 6) {
            _uiState.update { it.copy(errorMessage = "请输入有效邮箱，密码至少 6 位。") }
            return
        }
        if (state.mode == AuthMode.Register && code.isBlank()) {
            _uiState.update { it.copy(errorMessage = "注册需要邮箱验证码。") }
            return
        }

        viewModelScope.launch {
            _uiState.update { it.copy(isSubmitting = true, errorMessage = null, infoMessage = null) }
            val result = if (state.mode == AuthMode.Login) {
                runCatching { auth.login(email = email, password = password) }
            } else {
                runCatching {
                    auth.register(
                        email = email,
                        password = password,
                        verificationCode = code,
                    )
                }
            }

            result.onSuccess { session ->
                _uiState.update {
                    it.copy(
                        authEnabled = session.authEnabled,
                        authReady = session.authReady,
                        user = session.currentUser,
                        password = "",
                        verificationCode = "",
                        isSubmitting = false,
                        infoMessage = if (state.mode == AuthMode.Login) "登录成功。" else "注册成功。",
                    )
                }
            }.onFailure { throwable ->
                _uiState.update {
                    it.copy(
                        isSubmitting = false,
                        errorMessage = throwable.message ?: throwable::class.java.simpleName,
                    )
                }
            }
        }
    }

    fun logout() {
        viewModelScope.launch {
            _uiState.update { it.copy(isSubmitting = true, errorMessage = null, infoMessage = null) }
            runCatching {
                auth.logout()
            }.onSuccess { session ->
                _uiState.update {
                    it.copy(
                        authEnabled = session.authEnabled,
                        authReady = session.authReady,
                        user = session.currentUser,
                        isSubmitting = false,
                        infoMessage = "已退出登录。",
                    )
                }
            }.onFailure { throwable ->
                _uiState.update {
                    it.copy(
                        isSubmitting = false,
                        errorMessage = throwable.message ?: throwable::class.java.simpleName,
                    )
                }
            }
        }
    }
}
