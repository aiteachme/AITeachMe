package com.aiteachme.android.feature.home

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.aiteachme.android.core.network.ApiConfig
import com.aiteachme.android.core.network.NetworkModule
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class HomeUiState(
    val apiBaseUrl: String = ApiConfig.defaultBaseUrl,
    val healthStatus: String = "未检查",
    val isCheckingHealth: Boolean = false,
    val errorMessage: String? = null,
)

class HomeViewModel : ViewModel() {
    private val api = NetworkModule.createApi()
    private val _uiState = MutableStateFlow(HomeUiState())
    val uiState: StateFlow<HomeUiState> = _uiState.asStateFlow()

    fun checkHealth() {
        viewModelScope.launch {
            _uiState.update {
                it.copy(isCheckingHealth = true, errorMessage = null)
            }

            runCatching {
                api.health()
            }.onSuccess { response ->
                val status = if (response.code == 0) {
                    response.data?.status ?: "ok"
                } else {
                    "错误 ${response.code}"
                }
                _uiState.update {
                    it.copy(
                        healthStatus = status,
                        isCheckingHealth = false,
                        errorMessage = response.message.takeIf { message ->
                            response.code != 0 && message.isNotBlank()
                        },
                    )
                }
            }.onFailure { throwable ->
                _uiState.update {
                    it.copy(
                        healthStatus = "连接失败",
                        isCheckingHealth = false,
                        errorMessage = throwable.message ?: throwable::class.java.simpleName,
                    )
                }
            }
        }
    }
}
