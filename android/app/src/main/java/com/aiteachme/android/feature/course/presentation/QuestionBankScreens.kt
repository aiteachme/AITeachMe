package com.aiteachme.android.feature.course.presentation

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material.icons.outlined.Bookmark
import androidx.compose.material.icons.outlined.BookmarkBorder
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material3.AssistChip
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.Icon
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.aiteachme.android.core.network.dto.QuestionTemplateAnswerHistoryItem
import com.aiteachme.android.core.network.dto.QuestionTemplateItemResponse
import com.aiteachme.android.core.network.dto.QuestionTypeRegistryItemResponse
import com.aiteachme.android.core.ui.MarkdownText

@Composable
fun QuestionTemplatesScreen(
    courseId: String,
    contentPadding: PaddingValues,
    onBack: () -> Unit,
    onOpenPaper: (String, Int) -> Unit,
    viewModel: QuestionBankViewModel = viewModel(),
) {
    val state by viewModel.uiState.collectAsState()
    LaunchedEffect(courseId) {
        viewModel.loadTemplates(courseId)
    }
    val selected = state.templates.firstOrNull { it.id == state.selectedTemplateId }

    LazyColumn(
        modifier = Modifier.padding(contentPadding),
        contentPadding = PaddingValues(horizontal = 20.dp, vertical = 18.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        item {
            QuestionBankHeader(
                title = "题库模板",
                subtitle = "${state.templates.size} 道题 · ${state.questionTypes.size} 类题型",
                isLoading = state.isLoading,
                onBack = onBack,
                onRefresh = { viewModel.loadTemplates(courseId) },
            )
        }
        state.errorMessage?.let { item { BankMessage(it, true) } }
        state.infoMessage?.let { item { BankMessage(it, false) } }
        if (state.templates.isEmpty() && !state.isLoading) {
            item { BankMessage("当前课程还没有题库模板。先完成知识构建或生成一次练习试卷后再回来查看。", false) }
        }
        items(state.templates, key = { it.id }) { template ->
            QuestionTemplateCard(
                template = template,
                isSelected = template.id == state.selectedTemplateId,
                isMarking = state.isMarkingTemplateId == template.id,
                onSelect = { viewModel.selectTemplate(courseId, template.id) },
                onToggleMark = { viewModel.toggleMark(courseId, template) },
            )
        }
        selected?.let { template ->
            item {
                SectionTitle("答题历史", template.stem.take(28))
            }
            if (state.history.isEmpty()) {
                item { BankMessage("这道题还没有答题记录。", false) }
            } else {
                items(state.history, key = { "${it.examPaperId}-${it.examPaperItemId}-${it.createdAt}" }) { history ->
                    AnswerHistoryCard(history = history, onOpenPaper = { onOpenPaper(courseId, history.examPaperId) })
                }
            }
        }
    }
}

@Composable
fun QuestionTypesScreen(
    courseId: String,
    contentPadding: PaddingValues,
    onBack: () -> Unit,
    viewModel: QuestionBankViewModel = viewModel(),
) {
    val state by viewModel.uiState.collectAsState()
    LaunchedEffect(courseId) {
        viewModel.loadQuestionTypes(courseId)
    }

    LazyColumn(
        modifier = Modifier.padding(contentPadding),
        contentPadding = PaddingValues(horizontal = 20.dp, vertical = 18.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        item {
            QuestionBankHeader(
                title = "题型注册表",
                subtitle = "${state.questionTypes.size} 类题型",
                isLoading = state.isLoading,
                onBack = onBack,
                onRefresh = { viewModel.loadQuestionTypes(courseId) },
            )
        }
        state.errorMessage?.let { item { BankMessage(it, true) } }
        if (state.questionTypes.isEmpty() && !state.isLoading) {
            item { BankMessage("当前课程还没有题型注册信息。", false) }
        }
        items(state.questionTypes, key = { it.id }) { item ->
            QuestionTypeCard(item)
        }
    }
}

@Composable
private fun QuestionBankHeader(
    title: String,
    subtitle: String,
    isLoading: Boolean,
    onBack: () -> Unit,
    onRefresh: () -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        OutlinedButton(onClick = onBack) {
            Icon(Icons.AutoMirrored.Outlined.ArrowBack, contentDescription = "返回", modifier = Modifier.size(18.dp))
        }
        Column(modifier = Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.SemiBold)
            Text(subtitle, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        FilledTonalButton(onClick = onRefresh, enabled = !isLoading) {
            if (isLoading) {
                CircularProgressIndicator(modifier = Modifier.size(16.dp), strokeWidth = 2.dp)
            } else {
                Icon(Icons.Outlined.Refresh, contentDescription = "刷新", modifier = Modifier.size(18.dp))
            }
        }
    }
}

@Composable
private fun QuestionTemplateCard(
    template: QuestionTemplateItemResponse,
    isSelected: Boolean,
    isMarking: Boolean,
    onSelect: () -> Unit,
    onToggleMark: () -> Unit,
) {
    Surface(
        color = if (isSelected) MaterialTheme.colorScheme.secondaryContainer else MaterialTheme.colorScheme.surface,
        shape = MaterialTheme.shapes.large,
        tonalElevation = 1.dp,
        modifier = Modifier.clickable(onClick = onSelect),
    ) {
        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp), verticalAlignment = Alignment.CenterVertically) {
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        "${template.questionType.ifBlank { "题目" }} · ${template.difficulty.ifBlank { "默认难度" }}",
                        style = MaterialTheme.typography.labelLarge,
                        color = MaterialTheme.colorScheme.primary,
                    )
                    Text(
                        template.stem.ifBlank { "暂无题干" },
                        style = MaterialTheme.typography.titleSmall,
                        fontWeight = FontWeight.SemiBold,
                        maxLines = 2,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
                FilledTonalButton(onClick = onToggleMark, enabled = !isMarking) {
                    if (isMarking) {
                        CircularProgressIndicator(modifier = Modifier.size(16.dp), strokeWidth = 2.dp)
                    } else {
                        Icon(
                            if (template.isMarked) Icons.Outlined.Bookmark else Icons.Outlined.BookmarkBorder,
                            contentDescription = "标记",
                            modifier = Modifier.size(18.dp),
                        )
                    }
                }
            }
            if (template.hasWrongAttempt) {
                AssistChip(onClick = {}, label = { Text("有错题记录") })
            }
            MarkdownText(
                markdown = template.explanation.ifBlank { template.answer },
                maxLines = 4,
                textSizeSp = MaterialTheme.typography.bodySmall.fontSize.value,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun AnswerHistoryCard(history: QuestionTemplateAnswerHistoryItem, onOpenPaper: () -> Unit) {
    Surface(color = MaterialTheme.colorScheme.surface, shape = MaterialTheme.shapes.large, tonalElevation = 1.dp) {
        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Text(
                    if (history.isCorrect == true) "答对" else if (history.isCorrect == false) "答错" else "未判定",
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.SemiBold,
                )
                Text(compactDate(history.answeredAt ?: history.gradedAt ?: history.createdAt), style = MaterialTheme.typography.bodySmall)
            }
            Text("你的答案：${history.userAnswer.ifBlank { "--" }}", style = MaterialTheme.typography.bodyMedium)
            Text("正确答案：${history.correctAnswer.ifBlank { "--" }}", style = MaterialTheme.typography.bodyMedium)
            history.feedbackText?.takeIf { it.isNotBlank() }?.let {
                MarkdownText(markdown = it, textSizeSp = MaterialTheme.typography.bodySmall.fontSize.value)
            }
            OutlinedButton(onClick = onOpenPaper, modifier = Modifier.fillMaxWidth()) {
                Text("打开原试卷")
            }
        }
    }
}

@Composable
private fun QuestionTypeCard(item: QuestionTypeRegistryItemResponse) {
    Surface(color = MaterialTheme.colorScheme.surface, shape = MaterialTheme.shapes.large, tonalElevation = 1.dp) {
        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                Column(modifier = Modifier.weight(1f)) {
                    Text(item.displayName.ifBlank { item.typeKey }, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
                    Text(
                        listOf(item.typeKey, item.scope, item.source).filter { it.isNotBlank() }.joinToString(" · "),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                AssistChip(onClick = {}, label = { Text(if (item.isActive) "启用" else "停用") })
            }
            Text(item.description.ifBlank { "暂无说明" }, style = MaterialTheme.typography.bodyMedium)
            Text("作答格式：${item.answerFormat.ifBlank { "--" }}", style = MaterialTheme.typography.bodySmall)
            Text("判题方式：${item.gradingMethod.ifBlank { "--" }}", style = MaterialTheme.typography.bodySmall)
        }
    }
}

@Composable
private fun SectionTitle(title: String, subtitle: String) {
    Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
        Text(title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
        Text(subtitle, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
private fun BankMessage(message: String, isError: Boolean) {
    Surface(
        color = if (isError) MaterialTheme.colorScheme.errorContainer else MaterialTheme.colorScheme.secondaryContainer,
        shape = MaterialTheme.shapes.large,
    ) {
        Text(
            message,
            modifier = Modifier.padding(14.dp),
            color = if (isError) MaterialTheme.colorScheme.onErrorContainer else MaterialTheme.colorScheme.onSecondaryContainer,
            style = MaterialTheme.typography.bodyMedium,
        )
    }
}

private fun compactDate(value: String): String {
    return value.replace("T", " ").take(16).ifBlank { "--" }
}
