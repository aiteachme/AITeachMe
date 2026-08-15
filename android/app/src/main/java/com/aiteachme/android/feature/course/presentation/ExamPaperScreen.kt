package com.aiteachme.android.feature.course.presentation

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
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
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material.icons.outlined.CheckCircle
import androidx.compose.material.icons.outlined.Description
import androidx.compose.material.icons.outlined.School
import androidx.compose.material.icons.outlined.TipsAndUpdates
import androidx.compose.material.icons.outlined.Visibility
import androidx.compose.material.icons.outlined.WarningAmber
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
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
import com.aiteachme.android.core.network.dto.ExamPaperDetailResponse
import com.aiteachme.android.core.network.dto.ExamPaperItemResponse
import com.aiteachme.android.core.network.dto.ExamProfileSyncResponse
import com.aiteachme.android.core.network.dto.ExamStudyGuideFocusUnit
import com.aiteachme.android.core.network.dto.ExamStudyGuideResponse
import com.aiteachme.android.core.ui.MarkdownText

@Composable
fun ExamPaperScreen(
    courseId: String,
    examPaperId: Int,
    contentPadding: PaddingValues,
    onBack: () -> Unit,
    viewModel: ExamPaperViewModel = viewModel(),
) {
    val state by viewModel.uiState.collectAsState()
    val paper = state.paper
    val studyGuide = state.studyGuide

    LaunchedEffect(courseId, examPaperId) {
        viewModel.load(courseId = courseId, examPaperId = examPaperId)
    }

    LaunchedEffect(state.stage, paper?.id) {
        if (state.stage == ExamPaperStage.Study && paper != null && studyGuide == null) {
            viewModel.loadStudyGuide(courseId)
        }
    }

    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .padding(contentPadding)
            .background(MaterialTheme.colorScheme.background),
        contentPadding = PaddingValues(horizontal = 18.dp, vertical = 14.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        item {
            ExamPaperTopBar(
                title = paper?.title() ?: "试卷",
                subtitle = paper?.let { "${examModeLabel(it.examMode)} · ${examStatusLabel(it.status)}" } ?: "正在加载",
                onBack = onBack,
            )
        }

        if (state.errorMessage != null || state.infoMessage != null) {
            item {
                ExamPaperFeedback(
                    error = state.errorMessage,
                    info = state.infoMessage,
                )
            }
        }

        if (state.isLoading && paper == null) {
            item { ExamPaperLoading("正在加载试卷...") }
            return@LazyColumn
        }
        if (paper == null) {
            item { ExamPaperEmpty("这份试卷不存在，或暂时无法访问。") }
            return@LazyColumn
        }

        if (paper.isGraded() && paper.profileSync?.status?.lowercase() != "completed") {
            item {
                ExamProfileSyncBanner(
                    profileSync = paper.profileSync,
                    isRetrying = state.isRetryingProfileSync,
                    onRetry = { viewModel.retryProfileSync(courseId) },
                )
            }
        }

        if (paper.status.lowercase() == "grading_failed") {
            item {
                ExamPaperFeedback(
                    error = "自动判卷多次失败，原答卷已锁定保存。点击“重新批改”可启动一轮新的判卷。",
                    info = null,
                )
            }
        }

        item {
            ExamStageTabs(
                stage = state.stage,
                isGraded = paper.isGraded(),
                onAnswer = { viewModel.setStage(ExamPaperStage.Answer) },
                onReview = { viewModel.setStage(ExamPaperStage.Review) },
                onStudy = { viewModel.loadStudyGuide(courseId) },
            )
        }

        when {
            paper.status.lowercase() == "failed" -> {
                item { ExamPaperEmpty("试卷生成失败，请返回重新生成。") }
            }

            paper.status.isGeneratingStatus() -> {
                item { ExamPaperLoading("题目还在生成中，请稍后返回查看。") }
            }

            state.stage == ExamPaperStage.Answer -> {
                item {
                    ExamPaperSummary(
                        paper = paper,
                        answeredCount = paper.items.count { state.answers[it.id].orEmpty().isNotBlank() },
                    )
                }
                items(paper.items, key = { it.id }) { item ->
                    ExamQuestionCard(
                        item = item,
                        answer = state.answers[item.id].orEmpty(),
                        readOnly = paper.isGraded() || paper.status.lowercase() == "grading_failed",
                        showAnalysis = false,
                        onAnswerChange = { viewModel.updateAnswer(item.id, it) },
                    )
                }
                item {
                    Button(
                        onClick = { viewModel.submit(courseId) },
                        enabled = paper.canSubmit() && !state.isSubmitting,
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        if (state.isSubmitting) {
                            CircularProgressIndicator(modifier = Modifier.size(16.dp), strokeWidth = 2.dp)
                            Spacer(modifier = Modifier.width(8.dp))
                        }
                        Text(
                            when {
                                state.isSubmitting -> "正在批改"
                                paper.status.lowercase() == "grading_failed" -> "重新批改"
                                else -> "提交并批改"
                            }
                        )
                    }
                }
            }

            state.stage == ExamPaperStage.Review -> {
                item { ExamReviewSummary(paper = paper, onOpenStudy = { viewModel.loadStudyGuide(courseId) }) }
                items(paper.items, key = { it.id }) { item ->
                    ExamQuestionCard(
                        item = item,
                        answer = state.answers[item.id].orEmpty(),
                        readOnly = true,
                        showAnalysis = true,
                        onAnswerChange = {},
                    )
                }
            }

            state.stage == ExamPaperStage.Study -> {
                when {
                    state.isLoadingStudyGuide && studyGuide == null -> item { ExamPaperLoading("正在生成复习建议...") }
                    studyGuide != null -> item {
                        StudyGuideCard(
                            guide = studyGuide,
                            paper = paper,
                            onBackToReview = { viewModel.setStage(ExamPaperStage.Review) },
                        )
                    }
                    else -> item {
                        ExamPaperEmpty("复习页需要先完成批改。")
                    }
                }
            }
        }
    }
}

@Composable
private fun ExamProfileSyncBanner(
    profileSync: ExamProfileSyncResponse?,
    isRetrying: Boolean,
    onRetry: () -> Unit,
) {
    val status = profileSync?.status?.lowercase() ?: "not_tracked"
    val isActive = status in setOf("pending", "processing")
    val canRetry = profileSync?.canRetry == true || status in setOf("retry_wait", "failed", "not_tracked")
    val title = when (status) {
        "pending", "processing" -> "成绩已保存，正在同步学习画像"
        "retry_wait" -> "画像同步暂时失败，系统将自动重试"
        "failed" -> "画像同步失败"
        else -> "这份旧试卷尚未同步学习画像"
    }
    val containerColor = when (status) {
        "failed" -> MaterialTheme.colorScheme.errorContainer
        "retry_wait", "not_tracked" -> MaterialTheme.colorScheme.tertiaryContainer
        else -> MaterialTheme.colorScheme.secondaryContainer
    }
    val contentColor = when (status) {
        "failed" -> MaterialTheme.colorScheme.onErrorContainer
        "retry_wait", "not_tracked" -> MaterialTheme.colorScheme.onTertiaryContainer
        else -> MaterialTheme.colorScheme.onSecondaryContainer
    }

    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = containerColor,
        contentColor = contentColor,
        shape = RoundedCornerShape(18.dp),
    ) {
        Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                if (isActive) {
                    CircularProgressIndicator(modifier = Modifier.size(18.dp), strokeWidth = 2.dp)
                } else {
                    Icon(Icons.Outlined.WarningAmber, contentDescription = null, modifier = Modifier.size(20.dp))
                }
                Column(modifier = Modifier.weight(1f)) {
                    Text(title, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
                    profileSync?.lastErrorCode?.takeIf { it.isNotBlank() }?.let { errorCode ->
                        Text(
                            "错误代码：$errorCode",
                            style = MaterialTheme.typography.bodySmall,
                            color = contentColor.copy(alpha = 0.75f),
                        )
                    }
                }
            }
            if (canRetry) {
                Button(onClick = onRetry, enabled = !isRetrying, modifier = Modifier.fillMaxWidth()) {
                    if (isRetrying) {
                        CircularProgressIndicator(modifier = Modifier.size(16.dp), strokeWidth = 2.dp)
                        Spacer(modifier = Modifier.width(8.dp))
                    }
                    Text(if (isRetrying) "正在重试" else "立即重试")
                }
            }
        }
    }
}

@Composable
private fun ExamPaperTopBar(
    title: String,
    subtitle: String,
    onBack: () -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        IconButton(onClick = onBack) {
            Icon(Icons.AutoMirrored.Outlined.ArrowBack, contentDescription = "返回")
        }
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = title,
                style = MaterialTheme.typography.titleLarge,
                fontWeight = FontWeight.SemiBold,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Text(
                text = subtitle,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
    }
}

@Composable
private fun ExamStageTabs(
    stage: ExamPaperStage,
    isGraded: Boolean,
    onAnswer: () -> Unit,
    onReview: () -> Unit,
    onStudy: () -> Unit,
) {
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
        StageButton(
            label = "答题",
            icon = Icons.Outlined.Description,
            selected = stage == ExamPaperStage.Answer,
            enabled = true,
            modifier = Modifier.weight(1f),
            onClick = onAnswer,
        )
        StageButton(
            label = "讲评",
            icon = Icons.Outlined.Visibility,
            selected = stage == ExamPaperStage.Review,
            enabled = isGraded,
            modifier = Modifier.weight(1f),
            onClick = onReview,
        )
        StageButton(
            label = "复习",
            icon = Icons.Outlined.School,
            selected = stage == ExamPaperStage.Study,
            enabled = isGraded,
            modifier = Modifier.weight(1f),
            onClick = onStudy,
        )
    }
}

@Composable
private fun StageButton(
    label: String,
    icon: ImageVector,
    selected: Boolean,
    enabled: Boolean,
    modifier: Modifier,
    onClick: () -> Unit,
) {
    if (selected) {
        FilledTonalButton(onClick = onClick, enabled = enabled, modifier = modifier) {
            Icon(icon, contentDescription = null, modifier = Modifier.size(16.dp))
            Spacer(modifier = Modifier.width(6.dp))
            Text(label)
        }
    } else {
        Button(onClick = onClick, enabled = enabled, modifier = modifier) {
            Icon(icon, contentDescription = null, modifier = Modifier.size(16.dp))
            Spacer(modifier = Modifier.width(6.dp))
            Text(label)
        }
    }
}

@Composable
private fun ExamPaperSummary(
    paper: ExamPaperDetailResponse,
    answeredCount: Int,
) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = MaterialTheme.colorScheme.surfaceContainer,
        shape = RoundedCornerShape(18.dp),
    ) {
        Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("正式答题页", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
            Text(
                "已作答 $answeredCount / ${paper.items.size} 题。提交后会进入判题讲评，再生成最后的复习页。",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            if (paper.paperPreview.keywords.isNotEmpty()) {
                Text(
                    paper.paperPreview.keywords.take(8).joinToString(" / "),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.primary,
                )
            }
        }
    }
}

@Composable
private fun ExamReviewSummary(
    paper: ExamPaperDetailResponse,
    onOpenStudy: () -> Unit,
) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = MaterialTheme.colorScheme.surfaceContainer,
        shape = RoundedCornerShape(18.dp),
    ) {
        Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text("判题讲评", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
            Text(
                "本次得分 ${paper.scoreText() ?: "--"}，正确 ${paper.items.count { it.isCorrect == true }} / ${paper.items.size} 题。",
                style = MaterialTheme.typography.bodyMedium,
            )
            Button(onClick = onOpenStudy, modifier = Modifier.fillMaxWidth()) {
                Icon(Icons.Outlined.TipsAndUpdates, contentDescription = null, modifier = Modifier.size(16.dp))
                Spacer(modifier = Modifier.width(8.dp))
                Text("查看复习页")
            }
        }
    }
}

@Composable
private fun ExamQuestionCard(
    item: ExamPaperItemResponse,
    answer: String,
    readOnly: Boolean,
    showAnalysis: Boolean,
    onAnswerChange: (String) -> Unit,
) {
    val isChoice = item.isChoice()
    val isSupported = isSupportedExamQuestionType(item.questionType)
    val options = item.choiceOptions()
    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = MaterialTheme.colorScheme.surface,
        tonalElevation = 1.dp,
        shape = RoundedCornerShape(18.dp),
    ) {
        Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(
                    "第 ${item.itemOrder} 题",
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.SemiBold,
                )
                Text(
                    "${questionTypeLabel(item.questionType)} · ${difficultyLabel(item.difficulty)}",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(modifier = Modifier.weight(1f))
                item.scoreMax?.let {
                    Text("${formatScore(it)} 分", style = MaterialTheme.typography.bodySmall)
                }
            }

            MarkdownText(
                markdown = item.stem.ifBlank { "题干生成中..." },
                color = MaterialTheme.colorScheme.onSurface,
                linkColor = MaterialTheme.colorScheme.primary,
                textSizeSp = MaterialTheme.typography.bodyMedium.fontSize.value,
            )

            if (!isSupported) {
                Surface(
                    color = MaterialTheme.colorScheme.errorContainer,
                    shape = RoundedCornerShape(12.dp),
                ) {
                    Row(
                        modifier = Modifier.padding(12.dp),
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                        verticalAlignment = Alignment.Top,
                    ) {
                        Icon(Icons.Outlined.WarningAmber, contentDescription = null, modifier = Modifier.size(18.dp))
                        Text("当前版本不支持题型「${item.questionType.ifBlank { "未指定" }}」，无法作答或提交。")
                    }
                }
            } else if (isChoice) {
                ChoiceAnswerGroup(
                    item = item,
                    options = options,
                    answer = answer,
                    readOnly = readOnly,
                    showAnalysis = showAnalysis,
                    onAnswerChange = onAnswerChange,
                )
            } else {
                OutlinedTextField(
                    value = answer,
                    onValueChange = onAnswerChange,
                    enabled = !readOnly,
                    modifier = Modifier.fillMaxWidth(),
                    minLines = if (item.questionType == "fill_blank") 1 else 4,
                    maxLines = if (item.questionType == "fill_blank") 2 else 8,
                    placeholder = {
                        Text(if (item.questionType == "fill_blank") "填写答案" else "在此作答")
                    },
                )
            }

            if (showAnalysis) {
                QuestionAnalysisBlock(item)
            }
        }
    }
}

@Composable
private fun ChoiceAnswerGroup(
    item: ExamPaperItemResponse,
    options: List<String>,
    answer: String,
    readOnly: Boolean,
    showAnalysis: Boolean,
    onAnswerChange: (String) -> Unit,
) {
    val isMultiple = item.isMultipleChoice()
    val selected = splitMultiChoiceAnswer(answer)
    val correct = splitMultiChoiceAnswer(item.correctAnswer)
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        options.forEachIndexed { index, option ->
            val label = if (item.questionType == "true_false") trueFalseLabel(option) else optionLabel(index)
            val value = if (item.questionType == "true_false") option else optionLabel(index)
            val isSelected = if (isMultiple) selected.contains(value) else answer.trim() == value
            val isCorrect = correct.contains(value) || item.correctAnswer?.trim() == value
            val container = when {
                showAnalysis && isCorrect -> MaterialTheme.colorScheme.primaryContainer
                showAnalysis && isSelected && !isCorrect -> MaterialTheme.colorScheme.errorContainer
                isSelected -> MaterialTheme.colorScheme.secondaryContainer
                else -> MaterialTheme.colorScheme.surfaceContainer
            }
            Surface(
                modifier = Modifier
                    .fillMaxWidth()
                    .clickable(enabled = !readOnly) {
                        if (isMultiple) {
                            val next = selected.toMutableSet()
                            if (next.contains(value)) {
                                next.remove(value)
                            } else {
                                next.add(value)
                            }
                            onAnswerChange(next.sorted().joinToString(","))
                        } else {
                            onAnswerChange(if (isSelected) "" else value)
                        }
                    },
                color = container,
                shape = RoundedCornerShape(12.dp),
            ) {
                Row(
                    modifier = Modifier.padding(12.dp),
                    horizontalArrangement = Arrangement.spacedBy(10.dp),
                    verticalAlignment = Alignment.Top,
                ) {
                    ChoiceMark(label = label, selected = isSelected, multiple = isMultiple)
                    MarkdownText(
                        markdown = option,
                        modifier = Modifier.weight(1f),
                        color = MaterialTheme.colorScheme.onSurface,
                        linkColor = MaterialTheme.colorScheme.primary,
                        textSizeSp = MaterialTheme.typography.bodyMedium.fontSize.value,
                    )
                }
            }
        }
    }
}

@Composable
private fun ChoiceMark(label: String, selected: Boolean, multiple: Boolean) {
    Surface(
        modifier = Modifier.size(28.dp),
        color = if (selected) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.surface,
        contentColor = if (selected) MaterialTheme.colorScheme.onPrimary else MaterialTheme.colorScheme.onSurfaceVariant,
        shape = if (multiple) RoundedCornerShape(7.dp) else CircleShape,
    ) {
        Box(contentAlignment = Alignment.Center) {
            Text(label, style = MaterialTheme.typography.labelMedium, fontWeight = FontWeight.SemiBold)
        }
    }
}

@Composable
private fun QuestionAnalysisBlock(item: ExamPaperItemResponse) {
    val isCorrect = item.isCorrect == true
    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = if (isCorrect) Color(0xFFEAF7EF) else Color(0xFFFFF1F1),
        shape = RoundedCornerShape(14.dp),
    ) {
        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Icon(
                    imageVector = if (isCorrect) Icons.Outlined.CheckCircle else Icons.Outlined.WarningAmber,
                    contentDescription = null,
                    tint = if (isCorrect) Color(0xFF16864A) else MaterialTheme.colorScheme.error,
                )
                Text(if (isCorrect) "回答正确" else "需要订正", fontWeight = FontWeight.SemiBold)
            }
            AnalysisMarkdown(title = "你的答案", content = item.userAnswer.orEmpty().ifBlank { "未作答" })
            AnalysisMarkdown(title = "正确答案", content = item.correctAnswer.orEmpty().ifBlank { "无标准答案" })
            AnalysisMarkdown(title = "解析", content = item.explanation.ifBlank { "暂无解析" })
        }
    }
}

@Composable
private fun AnalysisMarkdown(title: String, content: String) {
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Text(title, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        MarkdownText(
            markdown = content,
            color = MaterialTheme.colorScheme.onSurface,
            linkColor = MaterialTheme.colorScheme.primary,
            textSizeSp = MaterialTheme.typography.bodySmall.fontSize.value,
            selectable = true,
        )
    }
}

@Composable
private fun StudyGuideCard(
    guide: ExamStudyGuideResponse,
    paper: ExamPaperDetailResponse,
    onBackToReview: () -> Unit,
) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = MaterialTheme.colorScheme.surface,
        shape = RoundedCornerShape(18.dp),
    ) {
        Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
            Row(horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.Top, modifier = Modifier.fillMaxWidth()) {
                Column(modifier = Modifier.weight(1f)) {
                    Text("复习页", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.SemiBold)
                    Text(
                        paper.title(),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        maxLines = 2,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
                FilledTonalButton(onClick = onBackToReview) {
                    Text("返回讲评")
                }
            }
            MarkdownText(
                markdown = guide.overallSummary.ifBlank { "暂无整体总结。" },
                color = MaterialTheme.colorScheme.onSurface,
                linkColor = MaterialTheme.colorScheme.primary,
                textSizeSp = MaterialTheme.typography.bodyMedium.fontSize.value,
            )
            StudyFocusUnits(guide.focusUnits)
            StudyGuideSection("优先补漏", guide.priorityGaps)
            StudyGuideSection("下一步怎么学", guide.actionSteps)
            StudyGuideSection("复习任务", guide.reviewTasks)
            StudyGuideSection("做得不错", guide.strengths)
        }
    }
}

@Composable
private fun StudyFocusUnits(units: List<ExamStudyGuideFocusUnit>) {
    if (units.isEmpty()) return
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text("重点知识点", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
        Text(
            "按本卷关联题目的得分表现排序",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        units.forEach { unit ->
            Surface(color = MaterialTheme.colorScheme.surfaceContainer, shape = RoundedCornerShape(12.dp)) {
                Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text(unit.knowledgeUnitName, fontWeight = FontWeight.SemiBold)
                    if (unit.paperAttempts > 0) {
                        Text(
                            "本卷答对 ${unit.paperCorrectAttempts.coerceIn(0, unit.paperAttempts)}/${unit.paperAttempts} 题",
                            style = MaterialTheme.typography.bodySmall,
                        )
                    }
                    unit.paperScoreRate?.let {
                        Text("本卷得分率 ${formatPercent(it)}", style = MaterialTheme.typography.bodySmall)
                    }
                    MarkdownText(
                        markdown = unit.reason,
                        textSizeSp = 13f,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        linkColor = MaterialTheme.colorScheme.primary,
                    )
                }
            }
        }
    }
}

@Composable
private fun StudyGuideSection(title: String, items: List<String>) {
    if (items.isEmpty()) return
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
        items.forEachIndexed { index, item ->
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                Text("${index + 1}.", color = MaterialTheme.colorScheme.primary)
                MarkdownText(
                    markdown = item,
                    modifier = Modifier.weight(1f),
                    textSizeSp = 15f,
                    color = MaterialTheme.colorScheme.onSurface,
                    linkColor = MaterialTheme.colorScheme.primary,
                )
            }
        }
    }
}

@Composable
private fun ExamPaperFeedback(error: String?, info: String?) {
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        error?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error) }
        info?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.primary) }
    }
}

@Composable
private fun ExamPaperLoading(text: String) {
    Box(modifier = Modifier.fillMaxWidth().height(180.dp), contentAlignment = Alignment.Center) {
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp), verticalAlignment = Alignment.CenterVertically) {
            CircularProgressIndicator(modifier = Modifier.size(22.dp), strokeWidth = 2.dp)
            Text(text)
        }
    }
}

@Composable
private fun ExamPaperEmpty(text: String) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = MaterialTheme.colorScheme.surfaceContainer,
        shape = RoundedCornerShape(16.dp),
    ) {
        Text(text, modifier = Modifier.padding(16.dp), color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

private fun ExamPaperDetailResponse.title(): String {
    return "${examModeLabel(examMode)} #$id"
}

private fun ExamPaperDetailResponse.canSubmit(): Boolean {
    return status.lowercase() in setOf("ready", "generated", "grading_failed") &&
        items.isNotEmpty() &&
        items.all { item -> isSupportedExamQuestionType(item.questionType) }
}

private fun ExamPaperDetailResponse.isGraded(): Boolean {
    return status.lowercase() == "graded"
}

private fun String.isGeneratingStatus(): Boolean {
    return lowercase() in setOf("accepted", "pending", "queued", "running", "generating", "preparing")
}

private fun ExamPaperItemResponse.isChoice(): Boolean {
    return normalizeExamQuestionType(questionType) in setOf("single_choice", "multiple_choice", "true_false")
}

private fun ExamPaperItemResponse.isMultipleChoice(): Boolean {
    return normalizeExamQuestionType(questionType) == "multiple_choice"
}

private fun ExamPaperItemResponse.choiceOptions(): List<String> {
    return if (questionType == "true_false" && options.isNullOrEmpty()) {
        listOf("True", "False")
    } else {
        options.orEmpty()
    }
}

private fun splitMultiChoiceAnswer(value: String?): Set<String> {
    return value.orEmpty()
        .replace("，", ",")
        .replace("、", ",")
        .replace("；", ",")
        .replace(";", ",")
        .split(",", " ")
        .map { it.trim().trimEnd('.', ')', '、').uppercase() }
        .filter { it.isNotBlank() }
        .toSet()
}

private fun optionLabel(index: Int): String {
    return ('A'.code + index).toChar().toString()
}

private fun trueFalseLabel(value: String): String {
    return when (value.lowercase()) {
        "true", "t", "yes", "y" -> "对"
        "false", "f", "no", "n" -> "错"
        else -> value
    }
}

private fun questionTypeLabel(type: String): String {
    return when (type) {
        "single_choice" -> "单选题"
        "multiple_choice", "multi_choice" -> "多选题"
        "fill_blank" -> "填空题"
        "true_false" -> "判断题"
        "short_answer" -> "简答题"
        else -> type.ifBlank { "未指定题型" }
    }
}

private fun difficultyLabel(value: String): String {
    return when (value.lowercase()) {
        "easy" -> "易"
        "medium" -> "中"
        "hard" -> "难"
        else -> value.ifBlank { "难度未知" }
    }
}

private fun examModeLabel(mode: String): String {
    return PracticeMode.fromApiValue(mode).label
}

private fun examStatusLabel(status: String): String {
    return when (status.lowercase()) {
        "accepted", "pending", "queued", "running", "generating", "preparing" -> "生成中"
        "ready", "generated" -> "可作答"
        "submitted" -> "已提交"
        "grading" -> "批改中"
        "grading_failed" -> "判卷失败"
        "graded", "completed" -> "已批改"
        "failed" -> "生成失败"
        else -> status.ifBlank { "未知状态" }
    }
}

private fun ExamPaperDetailResponse.scoreText(): String? {
    return scoreLabel(scoreObtained, totalScore)
}

private fun scoreLabel(score: Double?, total: Double?): String? {
    if (score == null) return null
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

private fun formatPercent(value: Double): String {
    val percent = if (value <= 1.0) value * 100.0 else value
    return "${formatScore(percent.coerceIn(0.0, 100.0))}%"
}
