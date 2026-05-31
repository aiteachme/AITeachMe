package com.aiteachme.android.feature.files.presentation

import androidx.compose.foundation.background
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material.icons.outlined.CheckCircle
import androidx.compose.material.icons.outlined.DeleteOutline
import androidx.compose.material.icons.outlined.Description
import androidx.compose.material.icons.outlined.ErrorOutline
import androidx.compose.material.icons.outlined.FolderOpen
import androidx.compose.material.icons.outlined.HourglassEmpty
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material.icons.outlined.UploadFile
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.aiteachme.android.core.network.dto.FileRecord

@Composable
fun FileLibraryScreen(
    contentPadding: PaddingValues,
    onBack: (() -> Unit)? = null,
    onOpenFile: (String) -> Unit = {},
    viewModel: FileLibraryViewModel = viewModel(),
) {
    val uiState by viewModel.uiState.collectAsState()
    val filePicker = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.OpenMultipleDocuments(),
    ) { uris ->
        viewModel.uploadUris(uris)
    }

    LaunchedEffect(Unit) {
        viewModel.loadFiles(showFullLoading = true)
    }

    val visibleFiles = uiState.data.items.filter { file ->
        uiState.statusFilter == FileStatusFilter.All || fileStatusKind(file) == uiState.statusFilter
    }

    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .background(Color.White)
            .padding(contentPadding),
        contentPadding = PaddingValues(horizontal = 20.dp, vertical = 18.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        item {
            FileLibraryHeader(
                uiState = uiState,
                onBack = onBack,
                onUpload = { filePicker.launch(FILE_PICKER_MIME_TYPES) },
                onRefresh = { viewModel.loadFiles(showFullLoading = false) },
            )
        }

        item {
            LibraryStats(data = uiState.data)
        }

        item {
            StatusFilters(
                uiState = uiState,
                onFilterChange = viewModel::setStatusFilter,
            )
        }

        if (uiState.errorMessage != null || uiState.infoMessage != null || uiState.uploadingNames.isNotEmpty()) {
            item {
                FileLibraryMessages(uiState = uiState)
            }
        }

        when {
            uiState.isLoading -> {
                item { LoadingFiles() }
            }
            uiState.data.items.isEmpty() -> {
                item {
                    EmptyFiles(onUpload = { filePicker.launch(FILE_PICKER_MIME_TYPES) })
                }
            }
            visibleFiles.isEmpty() -> {
                item { EmptyFilteredFiles() }
            }
            else -> {
                items(
                    items = visibleFiles,
                    key = { it.id },
                ) { file ->
                    FileCard(
                        file = file,
                        isDeleting = uiState.deletingFileIds.contains(file.id),
                        onOpen = { onOpenFile(file.id) },
                        onDelete = { viewModel.deleteFile(file.id) },
                    )
                }
            }
        }
    }
}

@Composable
private fun FileLibraryHeader(
    uiState: FileLibraryUiState,
    onBack: (() -> Unit)?,
    onUpload: () -> Unit,
    onRefresh: () -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(14.dp)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(10.dp),
            verticalAlignment = Alignment.Top,
        ) {
            if (onBack != null) {
                OutlinedButton(onClick = onBack) {
                    Icon(
                        imageVector = Icons.AutoMirrored.Outlined.ArrowBack,
                        contentDescription = null,
                        modifier = Modifier.size(18.dp),
                    )
                }
            }
            Column(
                modifier = Modifier.weight(1f),
                verticalArrangement = Arrangement.spacedBy(4.dp),
            ) {
                Text(
                    text = "全局资料库",
                    style = MaterialTheme.typography.headlineSmall,
                    fontWeight = FontWeight.SemiBold,
                )
                Text(
                    text = "上传资料后会自动解析，解析完成后可被不同学习空间引用。",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }

        Row(
            horizontalArrangement = Arrangement.spacedBy(10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Button(
                onClick = onUpload,
                enabled = !uiState.isUploading,
            ) {
                if (uiState.isUploading) {
                    CircularProgressIndicator(modifier = Modifier.size(16.dp), strokeWidth = 2.dp)
                } else {
                    Icon(
                        imageVector = Icons.Outlined.UploadFile,
                        contentDescription = null,
                        modifier = Modifier.size(18.dp),
                    )
                }
                Spacer(modifier = Modifier.width(8.dp))
                Text(if (uiState.isUploading) "上传中" else "选择文件")
            }
            FilledTonalButton(
                onClick = onRefresh,
                enabled = !uiState.isRefreshing && !uiState.isUploading,
            ) {
                if (uiState.isRefreshing) {
                    CircularProgressIndicator(modifier = Modifier.size(16.dp), strokeWidth = 2.dp)
                } else {
                    Icon(
                        imageVector = Icons.Outlined.Refresh,
                        contentDescription = null,
                        modifier = Modifier.size(18.dp),
                    )
                }
                Spacer(modifier = Modifier.width(8.dp))
                Text("刷新")
            }
        }
    }
}

@Composable
private fun LibraryStats(data: com.aiteachme.android.core.network.dto.FilesData) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        StatTile(
            label = "全部",
            value = data.total,
            modifier = Modifier.weight(1f),
        )
        StatTile(
            label = "已解析",
            value = data.readyCount,
            modifier = Modifier.weight(1f),
        )
        StatTile(
            label = "解析中",
            value = data.processingCount,
            modifier = Modifier.weight(1f),
        )
        StatTile(
            label = "失败",
            value = data.failedCount,
            modifier = Modifier.weight(1f),
        )
    }
}

@Composable
private fun StatTile(
    label: String,
    value: Int,
    modifier: Modifier = Modifier,
) {
    Surface(
        modifier = modifier,
        color = MaterialTheme.colorScheme.surfaceContainer,
        shape = MaterialTheme.shapes.medium,
    ) {
        Column(
            modifier = Modifier.padding(horizontal = 10.dp, vertical = 12.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(3.dp),
        ) {
            Text(
                text = value.toString(),
                style = MaterialTheme.typography.titleLarge,
                fontWeight = FontWeight.SemiBold,
            )
            Text(
                text = label,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
    }
}

@Composable
private fun StatusFilters(
    uiState: FileLibraryUiState,
    onFilterChange: (FileStatusFilter) -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .horizontalScroll(rememberScrollState()),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        FileStatusFilter.entries.forEach { filter ->
            AssistChip(
                onClick = { onFilterChange(filter) },
                label = { Text(filter.label()) },
                leadingIcon = if (uiState.statusFilter == filter) {
                    {
                        Icon(
                            imageVector = Icons.Outlined.CheckCircle,
                            contentDescription = null,
                            modifier = Modifier.size(16.dp),
                        )
                    }
                } else {
                    null
                },
            )
        }
    }
}

@Composable
private fun FileLibraryMessages(uiState: FileLibraryUiState) {
    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        if (uiState.uploadingNames.isNotEmpty()) {
            Surface(
                modifier = Modifier.fillMaxWidth(),
                color = MaterialTheme.colorScheme.primaryContainer,
                shape = MaterialTheme.shapes.medium,
            ) {
                Column(
                    modifier = Modifier.padding(14.dp),
                    verticalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    Text(
                        text = "正在上传 ${uiState.uploadingNames.size} 份资料",
                        style = MaterialTheme.typography.bodyMedium,
                        fontWeight = FontWeight.SemiBold,
                    )
                    Text(
                        text = uiState.uploadingNames.joinToString("、"),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onPrimaryContainer,
                        maxLines = 2,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
            }
        }
        uiState.infoMessage?.let { message ->
            Text(
                text = message,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.primary,
            )
        }
        uiState.errorMessage?.let { message ->
            Text(
                text = message,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.error,
            )
        }
    }
}

@Composable
private fun LoadingFiles() {
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .height(180.dp),
        contentAlignment = Alignment.Center,
    ) {
        Row(
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            CircularProgressIndicator(modifier = Modifier.size(22.dp), strokeWidth = 2.dp)
            Text("正在加载全局资料库")
        }
    }
}

@Composable
private fun EmptyFiles(onUpload: () -> Unit) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = MaterialTheme.colorScheme.surfaceContainer,
        shape = MaterialTheme.shapes.large,
    ) {
        Column(
            modifier = Modifier.padding(18.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
            horizontalAlignment = Alignment.Start,
        ) {
            Icon(
                imageVector = Icons.Outlined.FolderOpen,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.primary,
                modifier = Modifier.size(28.dp),
            )
            Text(
                text = "还没有资料",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold,
            )
            Text(
                text = "支持 txt、docx、pptx、pdf、md、jpeg、jpg、png、bmp。上传后后端会立即开始解析。",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            OutlinedButton(onClick = onUpload) {
                Icon(
                    imageVector = Icons.Outlined.UploadFile,
                    contentDescription = null,
                    modifier = Modifier.size(18.dp),
                )
                Spacer(modifier = Modifier.width(8.dp))
                Text("选择文件")
            }
        }
    }
}

@Composable
private fun EmptyFilteredFiles() {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = MaterialTheme.colorScheme.surfaceContainer,
        shape = MaterialTheme.shapes.large,
    ) {
        Text(
            text = "当前筛选条件下没有资料。",
            modifier = Modifier.padding(18.dp),
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun FileCard(
    file: FileRecord,
    isDeleting: Boolean,
    onOpen: () -> Unit,
    onDelete: () -> Unit,
) {
    val status = fileStatusKind(file)
    val statusColor = when (status) {
        FileStatusFilter.Ready -> MaterialTheme.colorScheme.primary
        FileStatusFilter.Processing -> MaterialTheme.colorScheme.tertiary
        FileStatusFilter.Failed -> MaterialTheme.colorScheme.error
        FileStatusFilter.All -> MaterialTheme.colorScheme.onSurfaceVariant
    }
    val statusIcon = when (status) {
        FileStatusFilter.Ready -> Icons.Outlined.CheckCircle
        FileStatusFilter.Processing -> Icons.Outlined.HourglassEmpty
        FileStatusFilter.Failed -> Icons.Outlined.ErrorOutline
        FileStatusFilter.All -> Icons.Outlined.Description
    }

    Surface(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onOpen),
        color = MaterialTheme.colorScheme.surfaceContainer,
        shape = MaterialTheme.shapes.large,
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.Top,
            ) {
                Row(
                    modifier = Modifier.weight(1f),
                    horizontalArrangement = Arrangement.spacedBy(12.dp),
                    verticalAlignment = Alignment.Top,
                ) {
                    Icon(
                        imageVector = fileIcon(file),
                        contentDescription = null,
                        tint = MaterialTheme.colorScheme.primary,
                        modifier = Modifier.size(28.dp),
                    )
                    Column(
                        modifier = Modifier.weight(1f),
                        verticalArrangement = Arrangement.spacedBy(4.dp),
                    ) {
                        Text(
                            text = file.filename.ifBlank { "未命名文件" },
                            style = MaterialTheme.typography.titleMedium,
                            fontWeight = FontWeight.SemiBold,
                            maxLines = 2,
                            overflow = TextOverflow.Ellipsis,
                        )
                        Text(
                            text = buildMetaText(file),
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                        )
                    }
                }
                IconButton(
                    onClick = onDelete,
                    enabled = !isDeleting,
                ) {
                    if (isDeleting) {
                        CircularProgressIndicator(modifier = Modifier.size(18.dp), strokeWidth = 2.dp)
                    } else {
                        Icon(
                            imageVector = Icons.Outlined.DeleteOutline,
                            contentDescription = "删除资料",
                            tint = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            }

            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                StatusPill(
                    icon = statusIcon,
                    text = fileStatusLabel(file),
                    color = statusColor,
                )
            }

            file.errorMessage?.takeIf { it.isNotBlank() }?.let { error ->
                Text(
                    text = error,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.error,
                    maxLines = 3,
                    overflow = TextOverflow.Ellipsis,
                )
            }

            if (file.markdownReady && file.markdownContent.isNotBlank()) {
                Text(
                    text = file.markdownContent.trim(),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 4,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
    }
}

@Composable
private fun StatusPill(
    icon: ImageVector,
    text: String,
    color: Color,
) {
    Surface(
        color = color.copy(alpha = 0.12f),
        contentColor = color,
        shape = MaterialTheme.shapes.medium,
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 10.dp, vertical = 6.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            Icon(
                imageVector = icon,
                contentDescription = null,
                modifier = Modifier.size(15.dp),
            )
            Text(
                text = text,
                style = MaterialTheme.typography.bodySmall,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
    }
}

private fun FileStatusFilter.label(): String {
    return when (this) {
        FileStatusFilter.All -> "全部"
        FileStatusFilter.Ready -> "已解析"
        FileStatusFilter.Processing -> "解析中"
        FileStatusFilter.Failed -> "失败"
    }
}

private fun fileIcon(file: FileRecord): ImageVector {
    return when (file.filetype.lowercase().trimStart('.')) {
        "pdf", "docx", "pptx", "md", "txt" -> Icons.Outlined.Description
        "jpeg", "jpg", "png", "bmp" -> Icons.Outlined.Description
        else -> Icons.Outlined.Description
    }
}

private fun buildMetaText(file: FileRecord): String {
    val parts = buildList {
        add(file.filetype.uppercase().trimStart('.').ifBlank { "FILE" })
        add(formatFileSize(file.fileSizeBytes))
        file.estimatedPages?.takeIf { it > 0 }?.let { add("${it} 页") }
        file.imageCount?.takeIf { it > 0 }?.let { add("${it} 图") }
        file.parserUsed?.takeIf { it.isNotBlank() }?.let { add(it) }
    }
    return parts.joinToString(" · ")
}

private val FILE_PICKER_MIME_TYPES = arrayOf("*/*")
