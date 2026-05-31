package com.aiteachme.android.feature.course.presentation

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
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material.icons.outlined.AutoStories
import androidx.compose.material.icons.outlined.FolderOpen
import androidx.compose.material.icons.outlined.Insights
import androidx.compose.material.icons.outlined.Psychology
import androidx.compose.material.icons.outlined.Quiz
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.aiteachme.android.core.network.dto.FileRecord
import com.aiteachme.android.feature.files.presentation.fileStatusLabel
import com.aiteachme.android.feature.files.presentation.formatFileSize

@Composable
fun CourseBuildScreen(
    courseId: String,
    contentPadding: PaddingValues,
    onBack: () -> Unit,
    onOpenFiles: () -> Unit,
    onOpenDocs: (String) -> Unit,
    viewModel: CourseWorkspaceViewModel = viewModel(),
) {
    val uiState by viewModel.uiState.collectAsState()

    LaunchedEffect(courseId) {
        viewModel.load(courseId)
    }

    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .padding(contentPadding),
        contentPadding = PaddingValues(horizontal = 20.dp, vertical = 18.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        item {
            CoursePageHeader(
                title = "资料构建",
                subtitle = uiState.course?.name ?: courseId,
                icon = Icons.Outlined.Psychology,
                onBack = onBack,
                onRefresh = { viewModel.load(courseId) },
                isLoading = uiState.isLoading,
            )
        }
        item { FeedbackMessages(uiState) }
        item {
            BuildStatusCard(uiState = uiState, onOpenDocs = { onOpenDocs(courseId) })
        }
        item {
            Surface(
                modifier = Modifier.fillMaxWidth(),
                color = MaterialTheme.colorScheme.surfaceContainer,
                shape = MaterialTheme.shapes.large,
            ) {
                Column(
                    modifier = Modifier.padding(16.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    Text("构建目标", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
                    OutlinedTextField(
                        value = uiState.buildPrompt,
                        onValueChange = viewModel::updateBuildPrompt,
                        modifier = Modifier.fillMaxWidth(),
                        minLines = 3,
                        maxLines = 5,
                        placeholder = { Text("例如：帮我整理成适合期末复习的系统讲义") },
                    )
                    Button(
                        onClick = { viewModel.startBuild(courseId) },
                        enabled = !uiState.isBuilding && !uiState.isLoading,
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        if (uiState.isBuilding) {
                            CircularProgressIndicator(modifier = Modifier.size(16.dp), strokeWidth = 2.dp)
                            Spacer(modifier = Modifier.width(8.dp))
                        }
                        Text("启动知识构建")
                    }
                }
            }
        }
        item {
            SectionTitle(
                title = "当前学科资料",
                subtitle = "${uiState.files.size} 份资料，解析完成后可参与构建",
                actionLabel = "资料库",
                onAction = onOpenFiles,
            )
        }
        if (uiState.isLoading && uiState.files.isEmpty()) {
            item { LoadingBlock("正在加载课程资料...") }
        } else if (uiState.files.isEmpty()) {
            item { EmptyBlock("这个学科还没有关联资料。先到资料库上传，再在 Web/后续移动端构建流程中关联。") }
        } else {
            items(uiState.files, key = { it.id }) { file ->
                FileMiniCard(file = file)
            }
        }
    }
}

@Composable
fun KnowledgeDocsScreen(
    courseId: String,
    contentPadding: PaddingValues,
    onBack: () -> Unit,
    onOpenBuild: (String) -> Unit,
    viewModel: CourseWorkspaceViewModel = viewModel(),
) {
    val uiState by viewModel.uiState.collectAsState()

    LaunchedEffect(courseId) {
        viewModel.load(courseId)
    }

    val docs = uiState.docs
    val markdown = docs?.markdown?.takeIf { it.isNotBlank() }
        ?: docs?.draftMarkdown?.takeIf { it.isNotBlank() }

    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .padding(contentPadding),
        contentPadding = PaddingValues(horizontal = 20.dp, vertical = 18.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        item {
            CoursePageHeader(
                title = "知识文档",
                subtitle = uiState.course?.name ?: courseId,
                icon = Icons.Outlined.AutoStories,
                onBack = onBack,
                onRefresh = { viewModel.load(courseId) },
                isLoading = uiState.isLoading,
            )
        }
        item { FeedbackMessages(uiState) }
        item {
            BuildStatusCard(uiState = uiState, onOpenDocs = null)
        }
        if (uiState.isLoading && markdown == null) {
            item { LoadingBlock("正在加载知识文档...") }
        } else if (markdown == null) {
            item {
                EmptyBlock(
                    text = "还没有知识文档。先完成资料解析和构建后，这里会显示适合手机阅读的课程文档。",
                    actionLabel = "去构建",
                    onAction = { onOpenBuild(courseId) },
                )
            }
        } else {
            item {
                Surface(
                    modifier = Modifier.fillMaxWidth(),
                    color = MaterialTheme.colorScheme.surfaceContainer,
                    shape = MaterialTheme.shapes.large,
                ) {
                    Column(
                        modifier = Modifier.padding(16.dp),
                        verticalArrangement = Arrangement.spacedBy(10.dp),
                    ) {
                        Text(
                            text = if (docs?.exists == true) "已发布文档" else "构建草稿",
                            style = MaterialTheme.typography.titleMedium,
                            fontWeight = FontWeight.SemiBold,
                        )
                        Text(
                            text = markdown,
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurface,
                        )
                    }
                }
            }
        }
    }
}

@Composable
fun PracticeScreen(
    courseId: String,
    contentPadding: PaddingValues,
    onBack: () -> Unit,
    onOpenDocs: (String) -> Unit,
    viewModel: CourseWorkspaceViewModel = viewModel(),
) {
    val uiState by viewModel.uiState.collectAsState()

    LaunchedEffect(courseId) {
        viewModel.load(courseId)
    }

    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .padding(contentPadding),
        contentPadding = PaddingValues(horizontal = 20.dp, vertical = 18.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        item {
            CoursePageHeader(
                title = "练习考试",
                subtitle = uiState.course?.name ?: courseId,
                icon = Icons.Outlined.Quiz,
                onBack = onBack,
                onRefresh = { viewModel.load(courseId) },
                isLoading = uiState.isLoading,
            )
        }
        item {
            CapabilityCard(
                title = "移动端练习入口",
                body = "这里先承接当前学科上下文。后续会接入试卷生成、答题、批改和错题复盘；现在可以先通过知识文档继续学习。",
                primaryLabel = "查看知识文档",
                onPrimary = { onOpenDocs(courseId) },
            )
        }
        item {
            MetricRow(
                items = listOf(
                    "资料" to uiState.files.size.toString(),
                    "已解析" to uiState.files.count { it.markdownReady }.toString(),
                    "文档" to if (uiState.docs?.exists == true) "已生成" else "未生成",
                ),
            )
        }
    }
}

@Composable
fun ProfileScreen(
    courseId: String,
    contentPadding: PaddingValues,
    onBack: () -> Unit,
    onOpenPractice: (String) -> Unit,
    viewModel: CourseWorkspaceViewModel = viewModel(),
) {
    val uiState by viewModel.uiState.collectAsState()

    LaunchedEffect(courseId) {
        viewModel.load(courseId)
    }

    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .padding(contentPadding),
        contentPadding = PaddingValues(horizontal = 20.dp, vertical = 18.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        item {
            CoursePageHeader(
                title = "学习画像",
                subtitle = uiState.course?.name ?: courseId,
                icon = Icons.Outlined.Insights,
                onBack = onBack,
                onRefresh = { viewModel.load(courseId) },
                isLoading = uiState.isLoading,
            )
        }
        item {
            CapabilityCard(
                title = "画像摘要",
                body = "移动端画像页先聚合资料、构建和后续练习信号。等练习模块接入后，会在这里展示掌握度、薄弱知识点和复习任务。",
                primaryLabel = "开始练习",
                onPrimary = { onOpenPractice(courseId) },
            )
        }
        item {
            MetricRow(
                items = listOf(
                    "课程资料" to uiState.files.size.toString(),
                    "可阅读文档" to if (uiState.docs?.exists == true) "1" else "0",
                    "构建状态" to (uiState.docs?.build?.status ?: "idle"),
                ),
            )
        }
    }
}

@Composable
private fun CoursePageHeader(
    title: String,
    subtitle: String,
    icon: ImageVector,
    onBack: () -> Unit,
    onRefresh: () -> Unit,
    isLoading: Boolean,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        OutlinedButton(onClick = onBack) {
            Icon(imageVector = Icons.AutoMirrored.Outlined.ArrowBack, contentDescription = null, modifier = Modifier.size(18.dp))
        }
        Icon(imageVector = icon, contentDescription = null, tint = MaterialTheme.colorScheme.primary)
        Column(modifier = Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.SemiBold)
            Text(
                subtitle,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
        FilledTonalButton(onClick = onRefresh, enabled = !isLoading) {
            if (isLoading) {
                CircularProgressIndicator(modifier = Modifier.size(16.dp), strokeWidth = 2.dp)
            } else {
                Icon(imageVector = Icons.Outlined.Refresh, contentDescription = null, modifier = Modifier.size(18.dp))
            }
        }
    }
}

@Composable
private fun BuildStatusCard(
    uiState: CourseWorkspaceUiState,
    onOpenDocs: (() -> Unit)?,
) {
    val docs = uiState.docs
    val build = docs?.build
    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = MaterialTheme.colorScheme.surfaceContainer,
        shape = MaterialTheme.shapes.large,
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Text("知识状态", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
            Text(
                text = when {
                    docs?.exists == true -> "已生成知识文档"
                    build?.status?.isNotBlank() == true -> "构建状态：${build.status}"
                    docs?.draftMarkdown?.isNotBlank() == true -> "已有构建草稿"
                    else -> "还没有知识文档"
                },
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            val progress = build?.progressPct
            if (progress != null) {
                LinearProgressIndicator(
                    progress = { (progress.coerceIn(0, 100)) / 100f },
                    modifier = Modifier.fillMaxWidth(),
                )
            }
            build?.currentStageDescription?.takeIf { it.isNotBlank() }?.let {
                Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            if (onOpenDocs != null && (docs?.exists == true || docs?.draftMarkdown?.isNotBlank() == true)) {
                OutlinedButton(onClick = onOpenDocs) {
                    Text("查看文档")
                }
            }
        }
    }
}

@Composable
private fun FileMiniCard(file: FileRecord) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = MaterialTheme.colorScheme.surfaceContainer,
        shape = MaterialTheme.shapes.large,
    ) {
        Column(
            modifier = Modifier.padding(14.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp), verticalAlignment = Alignment.CenterVertically) {
                Icon(imageVector = Icons.Outlined.FolderOpen, contentDescription = null, tint = MaterialTheme.colorScheme.primary)
                Column(modifier = Modifier.weight(1f)) {
                    Text(file.filename.ifBlank { file.id }, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
                    Text(
                        "${fileStatusLabel(file)} · ${formatFileSize(file.fileSizeBytes)}",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }
    }
}

@Composable
private fun SectionTitle(
    title: String,
    subtitle: String,
    actionLabel: String,
    onAction: () -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(modifier = Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.SemiBold)
            Text(subtitle, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        OutlinedButton(onClick = onAction) {
            Text(actionLabel)
        }
    }
}

@Composable
private fun CapabilityCard(
    title: String,
    body: String,
    primaryLabel: String,
    onPrimary: () -> Unit,
) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = MaterialTheme.colorScheme.surfaceContainer,
        shape = MaterialTheme.shapes.large,
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text(title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
            Text(body, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Button(onClick = onPrimary) {
                Text(primaryLabel)
            }
        }
    }
}

@Composable
private fun MetricRow(items: List<Pair<String, String>>) {
    Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        items.forEach { (label, value) ->
            Surface(
                modifier = Modifier.weight(1f),
                color = MaterialTheme.colorScheme.surfaceContainer,
                shape = MaterialTheme.shapes.medium,
            ) {
                Column(
                    modifier = Modifier.padding(12.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(4.dp),
                ) {
                    Text(value, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
                    Text(
                        label,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
            }
        }
    }
}

@Composable
private fun LoadingBlock(text: String) {
    Box(modifier = Modifier.fillMaxWidth().height(140.dp), contentAlignment = Alignment.Center) {
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp), verticalAlignment = Alignment.CenterVertically) {
            CircularProgressIndicator(modifier = Modifier.size(22.dp), strokeWidth = 2.dp)
            Text(text)
        }
    }
}

@Composable
private fun EmptyBlock(
    text: String,
    actionLabel: String? = null,
    onAction: (() -> Unit)? = null,
) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = MaterialTheme.colorScheme.surfaceContainer,
        shape = MaterialTheme.shapes.large,
    ) {
        Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text(text, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            if (actionLabel != null && onAction != null) {
                Button(onClick = onAction) {
                    Text(actionLabel)
                }
            }
        }
    }
}

@Composable
private fun FeedbackMessages(uiState: CourseWorkspaceUiState) {
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        uiState.errorMessage?.let {
            Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error)
        }
        uiState.infoMessage?.let {
            Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.primary)
        }
    }
}
