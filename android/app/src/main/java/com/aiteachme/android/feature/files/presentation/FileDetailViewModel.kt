package com.aiteachme.android.feature.files.presentation

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.aiteachme.android.core.di.AppServices
import com.aiteachme.android.core.network.dto.FileRecord
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class FileDetailUiState(
    val file: FileRecord? = null,
    val isLoading: Boolean = false,
    val errorMessage: String? = null,
)

class FileDetailViewModel : ViewModel() {
    private val files = AppServices.fileRepository
    private val _uiState = MutableStateFlow(FileDetailUiState())
    val uiState: StateFlow<FileDetailUiState> = _uiState.asStateFlow()

    fun load(fileId: String) {
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, errorMessage = null) }
            runCatching { files.getFile(fileId) }
                .onSuccess { file ->
                    _uiState.update {
                        it.copy(
                            file = file,
                            isLoading = false,
                            errorMessage = if (file == null) "没有找到这份资料" else null,
                        )
                    }
                }
                .onFailure { throwable ->
                    _uiState.update {
                        it.copy(
                            isLoading = false,
                            errorMessage = throwable.message ?: throwable::class.java.simpleName,
                        )
                    }
                }
        }
    }
}
