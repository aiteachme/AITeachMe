package com.aiteachme.android.feature.course.presentation

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.calculateEndPadding
import androidx.compose.foundation.layout.calculateStartPadding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material.icons.outlined.FolderOpen
import androidx.compose.material.icons.outlined.Insights
import androidx.compose.material.icons.outlined.Psychology
import androidx.compose.material.icons.outlined.Quiz
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material.icons.outlined.Settings
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
import androidx.compose.ui.platform.LocalLayoutDirection
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.aiteachme.android.core.network.dto.ExamHistoryItem
import com.aiteachme.android.core.network.dto.ExamPaperDetailResponse
import com.aiteachme.android.core.network.dto.ExamPaperItemResponse
import com.aiteachme.android.core.network.dto.FileRecord
import com.aiteachme.android.core.ui.MarkdownText
import com.aiteachme.android.feature.files.presentation.fileStatusLabel
import com.aiteachme.android.feature.files.presentation.formatFileSize
import kotlinx.coroutines.delay

@Composable
fun CourseBuildScreen(
    courseId: String,
    initialPrompt: String?,
    contentPadding: PaddingValues,
    onBack: () -> Unit,
    onOpenFiles: () -> Unit,
    onOpenDocs: (String) -> Unit,
    viewModel: CourseWorkspaceViewModel = viewModel(),
) {
    val uiState by viewModel.uiState.collectAsState()

    LaunchedEffect(courseId, initialPrompt) {
        viewModel.openBuild(courseId, initialPrompt)
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
                title = "构建规划",
                subtitle = uiState.course?.name ?: courseId,
                icon = Icons.Outlined.Psychology,
                onBack = onBack,
                onRefresh = { viewModel.load(courseId) },
                isLoading = uiState.isLoading,
            )
        }
        item { FeedbackMessages(uiState) }
        item {
            PlannerPlanCard(
                uiState = uiState,
                onStartBuild = {
                    viewModel.startBuild(courseId) {
                        onOpenDocs(courseId)
                    }
                },
            )
        }
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
                        onClick = { viewModel.startPlanner(courseId) },
                        enabled = !uiState.isPlanning && !uiState.isLoading && uiState.buildPrompt.isNotBlank(),
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        if (uiState.isPlanning) {
                            CircularProgressIndicator(modifier = Modifier.size(16.dp), strokeWidth = 2.dp)
                            Spacer(modifier = Modifier.width(8.dp))
                        }
                        Text(
                            when {
                                uiState.isPlanning -> "正在生成规划"
                                uiState.plannerPreviewPlan != null || uiState.plannerSession != null -> "重新规划"
                                else -> "生成构建规划"
                            },
                        )
                    }
                }
            }
        }
        item {
            SectionTitle(
                title = "当前学习空间资料",
                subtitle = "${uiState.files.size} 份资料，解析完成后可参与构建",
                actionLabel = "全局资料库",
                onAction = onOpenFiles,
            )
        }
        if (uiState.isLoading && uiState.files.isEmpty()) {
            item { LoadingBlock("正在加载学习空间资料...") }
        } else if (uiState.files.isEmpty()) {
            item { EmptyBlock("这个学习空间还没有关联资料。先到全局资料库上传，再在后续构建流程中关联。") }
        } else {
            items(uiState.files, key = { it.id }) { file ->
                FileMiniCard(file = file)
            }
        }
    }
}

@Composable
private fun PlannerPlanCard(
    uiState: CourseWorkspaceUiState,
    onStartBuild: () -> Unit,
) {
    val plan = uiState.plannerPreviewPlan ?: uiState.plannerSession?.latestPlan
    val streamingText = uiState.plannerStreamingPreview.trim()
    val hasConfirmedPlan = !uiState.docs?.confirmedPlanId.isNullOrBlank() ||
        !uiState.docs?.build?.confirmedPlanId.isNullOrBlank()
    val shouldShow = uiState.isPlanning || plan != null || hasConfirmedPlan || streamingText.isNotBlank()
    if (!shouldShow) {
        Surface(
            modifier = Modifier.fillMaxWidth(),
            color = MaterialTheme.colorScheme.surfaceContainer,
            shape = MaterialTheme.shapes.large,
        ) {
            Column(
                modifier = Modifier.padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Text("构建规划", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
                Text(
                    "输入学习目标后会直接检索资料、判断范围并生成章节规划。",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
        return
    }

    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = MaterialTheme.colorScheme.surface,
        shape = MaterialTheme.shapes.large,
        tonalElevation = 1.dp,
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(modifier = Modifier.weight(1f)) {
                    Text("规划判断", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
                    Text(
                        uiState.plannerStatus ?: "正在思考目标与资料...",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        maxLines = 2,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
                if (uiState.isPlanning) {
                    CircularProgressIndicator(modifier = Modifier.size(22.dp), strokeWidth = 2.dp)
                }
            }

            if (uiState.isPlanning) {
                LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
            }

            if ((plan != null || hasConfirmedPlan) && !uiState.isPlanning) {
                PlannerBuildActionButton(
                    uiState = uiState,
                    planHasChapters = plan?.chapterPlan?.isNotEmpty() ?: hasConfirmedPlan,
                    onStartBuild = onStartBuild,
                )
            }

            if (plan == null && hasConfirmedPlan && streamingText.isBlank()) {
                Text(
                    text = "已有确认过的构建方案，可以直接重新开始知识文档构建。",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }

            if (streamingText.isNotBlank()) {
                Text(
                    text = streamingText,
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurface,
                )
            }

            plan?.planSummary?.takeIf { it.isNotBlank() }?.let { summary ->
                Text(
                    text = summary,
                    style = MaterialTheme.typography.bodyMedium,
                    fontWeight = FontWeight.SemiBold,
                )
            }

            plan?.planSteps?.take(6)?.forEach { step ->
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("•", color = MaterialTheme.colorScheme.primary)
                    Text(
                        text = step,
                        modifier = Modifier.weight(1f),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }

            plan?.chapterPlan?.take(8)?.forEach { chapter ->
                Surface(
                    modifier = Modifier.fillMaxWidth(),
                    color = MaterialTheme.colorScheme.surfaceContainerLow,
                    shape = MaterialTheme.shapes.medium,
                ) {
                    Column(
                        modifier = Modifier.padding(12.dp),
                        verticalArrangement = Arrangement.spacedBy(4.dp),
                    ) {
                        Text(
                            text = chapter.title.ifBlank { "第 ${chapter.chapterIndex} 章" },
                            style = MaterialTheme.typography.titleSmall,
                            fontWeight = FontWeight.SemiBold,
                        )
                        chapter.objective.takeIf { it.isNotBlank() }?.let {
                            Text(
                                text = it,
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun PlannerBuildActionButton(
    uiState: CourseWorkspaceUiState,
    planHasChapters: Boolean,
    onStartBuild: () -> Unit,
) {
    Button(
        onClick = onStartBuild,
        enabled = !uiState.isBuilding && planHasChapters,
        modifier = Modifier.fillMaxWidth(),
    ) {
        if (uiState.isBuilding) {
            CircularProgressIndicator(
                modifier = Modifier.size(16.dp),
                strokeWidth = 2.dp,
            )
            Spacer(modifier = Modifier.width(8.dp))
        }
        Text(
            when {
                uiState.isBuilding -> "正在启动构建"
                uiState.docs?.exists == true -> "重新构建"
                else -> "开始构建"
            },
        )
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

    val buildStatus = uiState.docs?.build?.status
    LaunchedEffect(courseId, buildStatus) {
        if (isKnowledgeBuildActive(buildStatus)) {
            while (true) {
                delay(2_500)
                viewModel.load(courseId)
            }
        }
    }

    val docs = uiState.docs
    val markdown = docs?.markdown?.takeIf { it.isNotBlank() }
        ?: docs?.draftMarkdown?.takeIf { it.isNotBlank() }
    val layoutDirection = LocalLayoutDirection.current
    val startPadding = contentPadding.calculateStartPadding(layoutDirection) + 20.dp
    val endPadding = contentPadding.calculateEndPadding(layoutDirection) + 20.dp
    val topPadding = contentPadding.calculateTopPadding() + 8.dp
    val bottomPadding = contentPadding.calculateBottomPadding() + 28.dp

    Box(modifier = Modifier.fillMaxSize()) {
        LazyColumn(
            modifier = Modifier.fillMaxSize(),
            contentPadding = PaddingValues(
                start = startPadding,
                top = topPadding,
                end = endPadding,
                bottom = bottomPadding,
            ),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            item {
                CourseInlineActions(
                    onBack = onBack,
                    onRefresh = { viewModel.load(courseId) },
                    isLoading = uiState.isLoading,
                )
            }
            item { FeedbackMessages(uiState) }
            if (markdown == null || isKnowledgeBuildActive(buildStatus)) {
                item {
                    BuildStatusCard(uiState = uiState, onOpenDocs = null)
                }
            }
            if (uiState.isLoading && markdown == null) {
                item { LoadingBlock("正在加载知识文档...") }
            } else if (markdown == null) {
                item {
                    EmptyBlock(
                        text = "还没有知识文档。先完成资料解析和构建后，这里会显示适合手机阅读的学习文档。",
                        actionLabel = "去构建",
                        onAction = { onOpenBuild(courseId) },
                    )
                }
            } else {
                item {
                    MarkdownText(
                        markdown = markdown,
                        modifier = Modifier.fillMaxWidth(),
                        color = MaterialTheme.colorScheme.onSurface,
                        linkColor = MaterialTheme.colorScheme.primary,
                        textSizeSp = MaterialTheme.typography.bodyLarge.fontSize.value,
                        selectable = true,
                    )
                }
            }
        }

    }
}

private fun isKnowledgeBuildActive(status: String?): Boolean {
    return status?.lowercase() in setOf("accepted", "pending", "queued", "running")
}

@Composable
fun PracticeScreen(
    courseId: String,
    contentPadding: PaddingValues,
    onBack: () -> Unit,
    onOpenDocs: (String) -> Unit,
    onOpenPaper: (String, Int) -> Unit,
    workspaceViewModel: CourseWorkspaceViewModel = viewModel(),
    practiceViewModel: PracticeViewModel = viewModel(),
) {
    val workspaceState by workspaceViewModel.uiState.collectAsState()
    val practiceState by practiceViewModel.uiState.collectAsState()

    LaunchedEffect(courseId) {
        workspaceViewModel.load(courseId)
        practiceViewModel.load(courseId)
    }

    val paper: ExamPaperDetailResponse? = null
    val docsReady = workspaceState.docs?.exists == true ||
        workspaceState.docs?.markdown?.isNotBlank() == true ||
        workspaceState.docs?.draftMarkdown?.isNotBlank() == true
    val layoutDirection = LocalLayoutDirection.current
    val startPadding = contentPadding.calculateStartPadding(layoutDirection) + 20.dp
    val endPadding = contentPadding.calculateEndPadding(layoutDirection) + 20.dp
    val topPadding = contentPadding.calculateTopPadding() + 8.dp
    val bottomPadding = contentPadding.calculateBottomPadding() + 28.dp

    Box(modifier = Modifier.fillMaxSize()) {
        LazyColumn(
            modifier = Modifier.fillMaxSize(),
            contentPadding = PaddingValues(
                start = startPadding,
                top = topPadding,
                end = endPadding,
                bottom = bottomPadding,
            ),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            item {
                CourseInlineActions(
                    onBack = onBack,
                    onRefresh = {
                        workspaceViewModel.load(courseId)
                        practiceViewModel.load(courseId)
                    },
                    isLoading = workspaceState.isLoading ||
                        practiceState.isLoadingHistory ||
                        practiceState.isGenerating ||
                        practiceState.isOpeningPaper,
                )
            }
            item { FeedbackMessages(workspaceState) }
            item { PracticeFeedbackMessages(practiceState) }
            if (!docsReady && !workspaceState.isLoading) {
                item {
                    EmptyBlock(
                        text = "当前学习空间还没有可阅读的知识文档。可以继续生成试题；如果题目范围不准，建议先完成知识文档构建。",
                        actionLabel = "查看知识文档",
                        onAction = { onOpenDocs(courseId) },
                    )
                }
            }
            item {
                PracticeControlCard(
                    state = practiceState,
                    onModeSelected = practiceViewModel::selectMode,
                    onQuestionCountSelected = practiceViewModel::selectQuestionCount,
                    onPromptChange = practiceViewModel::updatePrompt,
                    onGenerate = {
                        practiceViewModel.generate(courseId) { paperId ->
                            onOpenPaper(courseId, paperId)
                        }
                    },
                )
            }
            if (practiceState.isGenerating) {
                item { LoadingBlock("正在生成题目，请稍候...") }
            }
            paper?.let { detail ->
                item {
                    ExamPaperSummaryCard(detail)
                }
                if (detail.items.isEmpty()) {
                    item { EmptyBlock("题目还在生成中，稍后会自动刷新。") }
                } else {
                    items(detail.items, key = { it.id }) { question ->
                        ExamQuestionCard(
                            paper = detail,
                            question = question,
                            answer = practiceState.answers[question.id].orEmpty(),
                            onAnswerChange = { value -> practiceViewModel.updateAnswer(question.id, value) },
                        )
                    }
                    item {
                        Button(
                            onClick = { practiceViewModel.submit(courseId) },
                            enabled = detail.canSubmit() && !practiceState.isSubmitting && !practiceState.isGenerating,
                            modifier = Modifier.fillMaxWidth(),
                        ) {
                            if (practiceState.isSubmitting) {
                                CircularProgressIndicator(modifier = Modifier.size(16.dp), strokeWidth = 2.dp)
                                Spacer(modifier = Modifier.width(8.dp))
                            }
                            Text(if (practiceState.isSubmitting) "正在批改" else "提交并批改")
                        }
                    }
                }
            }
            item {
                SectionTitle(
                    title = "历史试卷",
                    subtitle = if (practiceState.history.isEmpty()) "还没有生成记录" else "${practiceState.history.size} 份记录",
                    actionLabel = "刷新",
                    onAction = { practiceViewModel.load(courseId) },
                )
            }
            if (practiceState.isLoadingHistory && practiceState.history.isEmpty()) {
                item { LoadingBlock("正在加载历史试卷...") }
            } else if (practiceState.history.isEmpty()) {
                item { EmptyBlock("还没有考试、测试组卷或闯关记录。生成一次后会在这里保留入口。") }
            } else {
                items(practiceState.history, key = { it.id }) { history ->
                    ExamHistoryCard(
                        item = history,
                        selected = false,
                        onClick = { onOpenPaper(courseId, history.id) },
                    )
                }
            }
        }

    }
}

@Composable
private fun LegacyPracticeScreen(
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
                body = "这里先承接当前学习空间上下文。后续会接入试卷生成、答题、批改和错题复盘；现在可以先通过知识文档继续学习。",
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
private fun PracticeFeedbackMessages(state: PracticeUiState) {
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        state.errorMessage?.let {
            Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error)
        }
        state.infoMessage?.let {
            Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.primary)
        }
    }
}

@Composable
private fun PracticeControlCard(
    state: PracticeUiState,
    onModeSelected: (PracticeMode) -> Unit,
    onQuestionCountSelected: (Int) -> Unit,
    onPromptChange: (String) -> Unit,
    onGenerate: () -> Unit,
) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = MaterialTheme.colorScheme.surfaceContainer,
        shape = MaterialTheme.shapes.large,
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text("生成题目", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
                Text(
                    state.mode.description,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                PracticeMode.generatedPaperModes.forEach { mode ->
                    val selected = mode == state.mode
                    val modifier = Modifier.weight(1f)
                    if (selected) {
                        FilledTonalButton(onClick = { onModeSelected(mode) }, modifier = modifier) {
                            Text(mode.label, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        }
                    } else {
                        OutlinedButton(onClick = { onModeSelected(mode) }, modifier = modifier) {
                            Text(mode.label, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        }
                    }
                }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                listOf(5, 8, 12, 24).forEach { count ->
                    val selected = count == state.questionCount
                    val modifier = Modifier.weight(1f)
                    if (selected) {
                        FilledTonalButton(onClick = { onQuestionCountSelected(count) }, modifier = modifier) {
                            Text("${count}题")
                        }
                    } else {
                        OutlinedButton(onClick = { onQuestionCountSelected(count) }, modifier = modifier) {
                            Text("${count}题")
                        }
                    }
                }
            }
            OutlinedTextField(
                value = state.prompt,
                onValueChange = onPromptChange,
                modifier = Modifier.fillMaxWidth(),
                minLines = 2,
                maxLines = 4,
                placeholder = { Text("可选：输入范围、难度或题型要求") },
            )
            Button(
                onClick = onGenerate,
                enabled = !state.isGenerating && !state.isSubmitting,
                modifier = Modifier.fillMaxWidth(),
            ) {
                if (state.isGenerating) {
                    CircularProgressIndicator(modifier = Modifier.size(16.dp), strokeWidth = 2.dp)
                    Spacer(modifier = Modifier.width(8.dp))
                }
                Text(if (state.isGenerating) "正在生成" else "开始生成")
            }
        }
    }
}

@Composable
private fun ExamPaperSummaryCard(paper: ExamPaperDetailResponse) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = MaterialTheme.colorScheme.surfaceContainer,
        shape = MaterialTheme.shapes.large,
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        "${examModeLabel(paper.examMode)} #${paper.id}",
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.SemiBold,
                    )
                    Text(
                        "${examStatusLabel(paper.status)} · 共 ${paper.totalItems} 题",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                paper.scoreText()?.let { score ->
                    Text(score, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
                }
            }
            if (paper.paperPreview.keywords.isNotEmpty()) {
                Text(
                    paper.paperPreview.keywords.take(6).joinToString(" / "),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
    }
}

@Composable
private fun ExamQuestionCard(
    paper: ExamPaperDetailResponse,
    question: ExamPaperItemResponse,
    answer: String,
    onAnswerChange: (String) -> Unit,
) {
    val showResult = paper.isGraded() || question.isCorrect != null
    val canAnswer = paper.canSubmit()
    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = MaterialTheme.colorScheme.surface,
        shape = MaterialTheme.shapes.large,
        tonalElevation = 1.dp,
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    "第 ${question.itemOrder} 题",
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.SemiBold,
                )
                Text(
                    listOf(question.questionType, question.difficulty).filter { it.isNotBlank() }.joinToString(" · "),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            Text(question.stem, style = MaterialTheme.typography.bodyMedium)
            question.options.orEmpty().forEachIndexed { index, option ->
                Text(
                    "${('A'.code + index).toChar()}. $option",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            OutlinedTextField(
                value = answer,
                onValueChange = onAnswerChange,
                enabled = canAnswer,
                modifier = Modifier.fillMaxWidth(),
                minLines = 1,
                maxLines = 4,
                placeholder = { Text("填写你的答案") },
            )
            if (showResult) {
                val resultText = when (question.isCorrect) {
                    true -> "回答正确"
                    false -> "回答错误"
                    null -> "已批改"
                }
                Text(
                    resultText,
                    style = MaterialTheme.typography.bodySmall,
                    color = if (question.isCorrect == false) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.primary,
                    fontWeight = FontWeight.SemiBold,
                )
                question.correctAnswer?.takeIf { it.isNotBlank() }?.let { correct ->
                    Text("参考答案：$correct", style = MaterialTheme.typography.bodySmall)
                }
                question.explanation.takeIf { it.isNotBlank() }?.let { explanation ->
                    Text(
                        explanation,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }
    }
}

@Composable
private fun ExamHistoryCard(
    item: ExamHistoryItem,
    selected: Boolean,
    onClick: () -> Unit,
) {
    Surface(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick),
        color = if (selected) MaterialTheme.colorScheme.primaryContainer else MaterialTheme.colorScheme.surfaceContainer,
        shape = MaterialTheme.shapes.large,
    ) {
        Row(
            modifier = Modifier.padding(14.dp),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(
                    "${examModeLabel(item.examMode)} #${item.id}",
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.SemiBold,
                )
                Text(
                    "${examStatusLabel(item.status)} · ${item.totalItems} 题 · ${compactDate(item.createdAt)}",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            item.scoreText()?.let { score ->
                Text(score, style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.SemiBold)
            }
        }
    }
}

private fun ExamPaperDetailResponse.canSubmit(): Boolean {
    return status.lowercase() in setOf("ready", "generated") && items.isNotEmpty()
}

private fun ExamPaperDetailResponse.isGraded(): Boolean {
    return status.lowercase() == "graded"
}

private fun ExamPaperDetailResponse.scoreText(): String? {
    return scoreLabel(scoreObtained, totalScore)
}

private fun ExamHistoryItem.scoreText(): String? {
    return scoreLabel(scoreObtained, totalScore)
}

private fun scoreLabel(score: Double?, total: Double?): String? {
    if (score == null) {
        return null
    }
    return if (total != null && total > 0.0) {
        "${formatScore(score)}/${formatScore(total)}"
    } else {
        formatScore(score)
    }
}

private fun formatScore(value: Double): String {
    val rounded = value.toInt()
    return if (value == rounded.toDouble()) rounded.toString() else "%.1f".format(value)
}

private fun examModeLabel(mode: String): String {
    return PracticeMode.fromApiValue(mode).label
}

private fun examStatusLabel(status: String): String {
    return when (status.lowercase()) {
        "accepted", "pending", "queued", "running", "generating", "preparing" -> "生成中"
        "ready", "generated" -> "可作答"
        "submitted" -> "已提交"
        "graded", "completed" -> "已批改"
        "failed" -> "生成失败"
        else -> status.ifBlank { "未知状态" }
    }
}

private fun compactDate(value: String): String {
    return value.replace("T", " ").take(16).ifBlank { "--" }
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
                body = "移动端画像页先聚合资料、构建和练习信号。练习、组卷和闯关提交后会回写掌握状态，后续可在这里继续展开薄弱点和复习任务。",
                primaryLabel = "开始练习",
                onPrimary = { onOpenPractice(courseId) },
            )
        }
        item {
            MetricRow(
                items = listOf(
                    "空间资料" to uiState.files.size.toString(),
                    "可阅读文档" to if (uiState.docs?.exists == true) "1" else "0",
                    "构建状态" to (uiState.docs?.build?.status ?: "idle"),
                ),
            )
        }
    }
}

@Composable
fun CourseSettingsScreen(
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

    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .padding(contentPadding),
        contentPadding = PaddingValues(horizontal = 20.dp, vertical = 18.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        item {
            CoursePageHeader(
                title = "学科设置",
                subtitle = uiState.course?.name ?: courseId,
                icon = Icons.Outlined.Settings,
                onBack = onBack,
                onRefresh = { viewModel.load(courseId) },
                isLoading = uiState.isLoading,
            )
        }
        item { FeedbackMessages(uiState) }
        item {
            CapabilityCard(
                title = "当前学习空间",
                body = "这里只管理当前学习空间的信息，不影响全局助手、全局资料库和账号设置。学科名称、目标和知识结构仍通过构建对话统一调整。",
                primaryLabel = "打开构建对话",
                onPrimary = { onOpenBuild(courseId) },
            )
        }
        item {
            MetricRow(
                items = listOf(
                    "资料" to uiState.files.size.toString(),
                    "文档" to if (uiState.docs?.exists == true) "已生成" else "未生成",
                    "状态" to (uiState.docs?.build?.status ?: "idle"),
                ),
            )
        }
        item {
            EmptyBlock(
                text = "后续这里会加入学科显示名称、学习目标、默认练习偏好和删除学科等设置。当前阶段先把入口固定为当前学习空间的从属页。",
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
private fun CourseInlineActions(
    onBack: () -> Unit,
    onRefresh: () -> Unit,
    isLoading: Boolean,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        OutlinedButton(onClick = onBack) {
            Icon(
                imageVector = Icons.AutoMirrored.Outlined.ArrowBack,
                contentDescription = null,
                modifier = Modifier.size(18.dp),
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
