package com.aiteachme.android.feature.files.presentation

import android.net.Uri
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.aiteachme.android.core.data.repository.UploadFileRef
import com.aiteachme.android.core.di.AppServices
import com.aiteachme.android.core.network.dto.FileRecord
import com.aiteachme.android.core.network.dto.FilesData
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import java.util.Locale

enum class FileStatusFilter {
    All,
    Ready,
    Processing,
    Failed,
}

data class FileLibraryUiState(
    val data: FilesData = FilesData(),
    val statusFilter: FileStatusFilter = FileStatusFilter.All,
    val isLoading: Boolean = false,
    val isRefreshing: Boolean = false,
    val isUploading: Boolean = false,
    val deletingFileIds: Set<String> = emptySet(),
    val uploadingNames: List<String> = emptyList(),
    val errorMessage: String? = null,
    val infoMessage: String? = null,
)

class FileLibraryViewModel : ViewModel() {
    private val files = AppServices.fileRepository
    private var pollingJob: Job? = null

    private val _uiState = MutableStateFlow(FileLibraryUiState())
    val uiState: StateFlow<FileLibraryUiState> = _uiState.asStateFlow()

    fun loadFiles(showFullLoading: Boolean = false) {
        viewModelScope.launch {
            _uiState.update {
                it.copy(
                    isLoading = showFullLoading,
                    isRefreshing = !showFullLoading,
                    errorMessage = null,
                )
            }
            runCatching {
                files.listFiles()
            }.onSuccess { data ->
                _uiState.update {
                    it.copy(
                        data = data,
                        isLoading = false,
                        isRefreshing = false,
                    )
                }
                updatePolling(data)
            }.onFailure { throwable ->
                _uiState.update {
                    it.copy(
                        isLoading = false,
                        isRefreshing = false,
                        errorMessage = throwable.message ?: throwable::class.java.simpleName,
                    )
                }
            }
        }
    }

    fun setStatusFilter(filter: FileStatusFilter) {
        _uiState.update { it.copy(statusFilter = filter) }
    }

    fun uploadUris(uris: List<Uri>) {
        if (uris.isEmpty() || _uiState.value.isUploading) {
            return
        }

        val resolvedFiles = files.resolveUploadFiles(uris)
        val validationMessage = validateUploadFiles(resolvedFiles)
        if (validationMessage != null) {
            _uiState.update { it.copy(errorMessage = validationMessage, infoMessage = null) }
            return
        }

        viewModelScope.launch {
            _uiState.update {
                it.copy(
                    isUploading = true,
                    uploadingNames = resolvedFiles.map { file -> file.filename },
                    errorMessage = null,
                    infoMessage = null,
                )
            }
            runCatching {
                files.uploadFiles(resolvedFiles)
            }.onSuccess { uploadData ->
                _uiState.update {
                    it.copy(
                        isUploading = false,
                        uploadingNames = emptyList(),
                        infoMessage = "已上传 ${uploadData.uploadedItems.size} 份资料，${uploadData.startedParseCount} 份开始解析。",
                    )
                }
                loadFiles(showFullLoading = false)
            }.onFailure { throwable ->
                _uiState.update {
                    it.copy(
                        isUploading = false,
                        uploadingNames = emptyList(),
                        errorMessage = throwable.message ?: throwable::class.java.simpleName,
                    )
                }
            }
        }
    }

    fun deleteFile(fileId: String) {
        if (fileId.isBlank() || _uiState.value.deletingFileIds.contains(fileId)) {
            return
        }

        viewModelScope.launch {
            _uiState.update {
                it.copy(
                    deletingFileIds = it.deletingFileIds + fileId,
                    errorMessage = null,
                    infoMessage = null,
                )
            }
            runCatching {
                files.deleteFile(fileId)
            }.onSuccess {
                _uiState.update { current ->
                    current.copy(
                        data = current.data.copy(
                            total = (current.data.total - 1).coerceAtLeast(0),
                            items = current.data.items.filterNot { item -> item.id == fileId },
                        ),
                        deletingFileIds = current.deletingFileIds - fileId,
                        infoMessage = "资料已删除。",
                    )
                }
                loadFiles(showFullLoading = false)
            }.onFailure { throwable ->
                _uiState.update {
                    it.copy(
                        deletingFileIds = it.deletingFileIds - fileId,
                        errorMessage = throwable.message ?: throwable::class.java.simpleName,
                    )
                }
            }
        }
    }

    override fun onCleared() {
        pollingJob?.cancel()
        super.onCleared()
    }

    private fun updatePolling(data: FilesData) {
        if (data.processingCount <= 0) {
            pollingJob?.cancel()
            pollingJob = null
            return
        }
        if (pollingJob?.isActive == true) {
            return
        }
        pollingJob = viewModelScope.launch {
            while (true) {
                delay(2_000)
                val nextData = runCatching { files.listFiles() }.getOrNull() ?: continue
                _uiState.update { it.copy(data = nextData) }
                if (nextData.processingCount <= 0) {
                    break
                }
            }
            pollingJob = null
        }
    }

    private fun validateUploadFiles(files: List<UploadFileRef>): String? {
        if (files.size > MAX_FILES_PER_UPLOAD) {
            return "单次最多上传 $MAX_FILES_PER_UPLOAD 个文件，当前选择 ${files.size} 个。"
        }
        val unsupported = files.filterNot { file -> SUPPORTED_EXTENSIONS.contains(file.extension()) }
        if (unsupported.isNotEmpty()) {
            val preview = unsupported.take(3).joinToString("、") { it.filename }
            val suffix = if (unsupported.size > 3) " 等 ${unsupported.size} 个文件" else ""
            return "暂时仅支持 txt、docx、pptx、pdf、md、jpeg、jpg、png、bmp。未上传：$preview$suffix。"
        }
        val knownTotalBytes = files.mapNotNull { it.sizeBytes }.sum()
        if (knownTotalBytes > MAX_TOTAL_UPLOAD_BYTES) {
            return "单次上传总大小不能超过 10 MB，当前约 ${formatFileSize(knownTotalBytes)}。"
        }
        return null
    }

    private fun UploadFileRef.extension(): String {
        return filename.substringAfterLast('.', "")
            .lowercase(Locale.US)
            .trim()
    }

    private companion object {
        const val MAX_FILES_PER_UPLOAD = 10
        const val MAX_TOTAL_UPLOAD_BYTES = 10L * 1024L * 1024L
        val SUPPORTED_EXTENSIONS = setOf("pdf", "docx", "pptx", "md", "txt", "jpeg", "jpg", "png", "bmp")
    }
}

fun fileStatusKind(file: FileRecord): FileStatusFilter {
    if (file.markdownReady) {
        return FileStatusFilter.Ready
    }
    if (!file.errorMessage.isNullOrBlank() || file.status == "failed") {
        return FileStatusFilter.Failed
    }
    return FileStatusFilter.Processing
}

fun fileStatusLabel(file: FileRecord): String {
    if (!file.errorMessage.isNullOrBlank()) {
        return "解析失败"
    }
    if (file.digestCurrentStep?.isNotBlank() == true) {
        return "已进入 ${file.digestCurrentStep}"
    }
    if (file.markdownReady) {
        return if (file.assetReady) "已完成解析与素材抽取" else "已完成正文解析"
    }
    return when (file.ingestStatus) {
        "classifying" -> "正在识别文档类型"
        "fast_parsing", "parsing" -> "正在提取正文与结构"
        "enhancing" -> "正在做公式、图片和结构增强"
        "ready_for_digest" -> "已准备进入知识构建"
        else -> if (file.status == "processing") "上传完成，正在处理" else "等待处理"
    }
}

fun formatFileSize(bytes: Long?): String {
    if (bytes == null || bytes <= 0) {
        return "未知"
    }
    val units = listOf("B", "KB", "MB", "GB")
    var value = bytes.toDouble()
    var index = 0
    while (value >= 1024 && index < units.lastIndex) {
        value /= 1024
        index += 1
    }
    val formatted = if (value >= 10 || index == 0) {
        "%.0f".format(Locale.US, value)
    } else {
        "%.1f".format(Locale.US, value)
    }
    return "$formatted ${units[index]}"
}
