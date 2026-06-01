package com.aiteachme.android.feature.course.presentation

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material.icons.outlined.CheckCircle
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material.icons.outlined.School
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
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
import com.aiteachme.android.core.network.dto.MasteryStateResponse
import com.aiteachme.android.core.network.dto.ReviewTaskResponse
import com.aiteachme.android.core.network.dto.StudyPlanStepResponse

@Composable
fun ProfileDashboardScreen(
    courseId: String,
    contentPadding: PaddingValues,
    onBack: () -> Unit,
    onOpenPractice: (String) -> Unit,
    viewModel: ProfileViewModel = viewModel(),
) {
    val state by viewModel.uiState.collectAsState()

    LaunchedEffect(courseId) {
        viewModel.load(courseId)
    }

    LazyColumn(
        modifier = Modifier.padding(contentPadding),
        contentPadding = PaddingValues(horizontal = 20.dp, vertical = 18.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        item {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(12.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                OutlinedButton(onClick = onBack) {
                    Icon(Icons.AutoMirrored.Outlined.ArrowBack, contentDescription = "返回", modifier = Modifier.size(18.dp))
                }
                Column(modifier = Modifier.weight(1f)) {
                    Text("学习画像", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.SemiBold)
                    Text(courseId, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                FilledTonalButton(onClick = { viewModel.load(courseId) }, enabled = !state.isLoading) {
                    if (state.isLoading) {
                        CircularProgressIndicator(modifier = Modifier.size(16.dp), strokeWidth = 2.dp)
                    } else {
                        Icon(Icons.Outlined.Refresh, contentDescription = "刷新", modifier = Modifier.size(18.dp))
                    }
                }
            }
        }
        state.errorMessage?.let { message ->
            item { MessagePanel(message = message, isError = true) }
        }
        state.infoMessage?.let { message ->
            item { MessagePanel(message = message, isError = false) }
        }
        item {
            val profile = state.mastery?.courseProfile
            SummaryPanel(
                avgMastery = profile?.avgMastery,
                weakCount = state.mastery?.weakKnowledgeUnitCount ?: profile?.weakKnowledgeUnitCount ?: 0,
                dueReviews = profile?.dueReviewCount ?: state.reviews.count { it.status != "completed" },
                pendingReviews = profile?.pendingReviewCount ?: state.reviews.size,
                onOpenPractice = { onOpenPractice(courseId) },
            )
        }
        if (state.studyPlan.isNotEmpty()) {
            item { SectionLabel("学习计划", "${state.studyPlan.size} 个建议动作") }
            items(state.studyPlan, key = { it.key.ifBlank { it.title } }) { item ->
                StudyPlanCard(item)
            }
        }
        if (state.reviews.isNotEmpty()) {
            item { SectionLabel("复习任务", "${state.reviews.size} 个待处理任务") }
            items(state.reviews, key = { it.id }) { task ->
                ReviewTaskCard(
                    task = task,
                    isCompleting = state.isCompletingReviewId == task.id,
                    onComplete = { viewModel.completeReview(courseId, task.id) },
                )
            }
        }
        val masteryStates = state.mastery?.knowledgeUnitStates.orEmpty()
        if (masteryStates.isNotEmpty()) {
            item { SectionLabel("知识点掌握", "${masteryStates.size} 个知识点状态") }
            items(masteryStates.sortedBy { it.masteryScore }.take(30), key = { it.id }) { item ->
                MasteryStateCard(item)
            }
        }
        if (!state.isLoading && state.mastery == null && state.reviews.isEmpty() && state.studyPlan.isEmpty()) {
            item {
                MessagePanel(
                    message = "还没有可用画像。完成一次练习、整卷测试或闯关后，这里会显示掌握度和复习任务。",
                    isError = false,
                )
            }
        }
    }
}

@Composable
private fun SummaryPanel(
    avgMastery: Double?,
    weakCount: Int,
    dueReviews: Int,
    pendingReviews: Int,
    onOpenPractice: () -> Unit,
) {
    Surface(
        color = MaterialTheme.colorScheme.surfaceContainer,
        shape = MaterialTheme.shapes.large,
    ) {
        Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp), verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Outlined.School, contentDescription = null, tint = MaterialTheme.colorScheme.primary)
                Column(modifier = Modifier.weight(1f)) {
                    Text("当前掌握概览", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
                    Text(
                        "根据练习、组卷批改和复习记录动态更新。",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                MetricChip("平均掌握", avgMastery?.let { formatPercent(it) } ?: "--")
                MetricChip("薄弱点", weakCount.toString())
                MetricChip("到期复习", dueReviews.toString())
                MetricChip("待复习", pendingReviews.toString())
            }
            Button(onClick = onOpenPractice, modifier = Modifier.fillMaxWidth()) {
                Text("进入练习考试")
            }
        }
    }
}

@Composable
private fun SectionLabel(title: String, subtitle: String) {
    Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
        Text(title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
        Text(subtitle, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
private fun StudyPlanCard(item: StudyPlanStepResponse) {
    Surface(color = MaterialTheme.colorScheme.surface, shape = MaterialTheme.shapes.large, tonalElevation = 1.dp) {
        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(item.title.ifBlank { item.key }, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
            Text(item.detail, style = MaterialTheme.typography.bodyMedium)
            if (item.action.isNotBlank()) {
                AssistChip(onClick = {}, label = { Text(item.action, maxLines = 1, overflow = TextOverflow.Ellipsis) })
            }
        }
    }
}

@Composable
private fun ReviewTaskCard(
    task: ReviewTaskResponse,
    isCompleting: Boolean,
    onComplete: () -> Unit,
) {
    Surface(color = MaterialTheme.colorScheme.surface, shape = MaterialTheme.shapes.large, tonalElevation = 1.dp) {
        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp), verticalAlignment = Alignment.CenterVertically) {
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        task.knowledgeUnitName ?: "知识点 ${task.knowledgeUnitId}",
                        style = MaterialTheme.typography.titleSmall,
                        fontWeight = FontWeight.SemiBold,
                    )
                    Text(
                        listOfNotNull(task.knowledgeUnitType, task.scheduledAt?.let { "计划 ${compactDate(it)}" })
                            .joinToString(" · "),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                FilledTonalButton(onClick = onComplete, enabled = !isCompleting) {
                    if (isCompleting) {
                        CircularProgressIndicator(modifier = Modifier.size(16.dp), strokeWidth = 2.dp)
                    } else {
                        Icon(Icons.Outlined.CheckCircle, contentDescription = null, modifier = Modifier.size(18.dp))
                    }
                }
            }
            task.reason?.takeIf { it.isNotBlank() }?.let {
                Text(it, style = MaterialTheme.typography.bodyMedium)
            }
        }
    }
}

@Composable
private fun MasteryStateCard(item: MasteryStateResponse) {
    Surface(color = MaterialTheme.colorScheme.surface, shape = MaterialTheme.shapes.large, tonalElevation = 1.dp) {
        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(horizontalArrangement = Arrangement.SpaceBetween, modifier = Modifier.fillMaxWidth()) {
                Text(
                    item.knowledgeUnitName ?: "知识点 ${item.knowledgeUnitId}",
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.SemiBold,
                    modifier = Modifier.weight(1f),
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                Text(formatPercent(item.masteryScore), style = MaterialTheme.typography.labelLarge)
            }
            LinearProgressIndicator(
                progress = { item.masteryScore.coerceIn(0.0, 1.0).toFloat() },
                modifier = Modifier.fillMaxWidth(),
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                MetricChip("尝试", item.totalAttempts.toString())
                MetricChip("正确", item.correctAttempts.toString())
                MetricChip("优先级", "%.1f".format(item.reviewPriority))
            }
        }
    }
}

@Composable
private fun MetricChip(label: String, value: String) {
    Surface(color = MaterialTheme.colorScheme.primaryContainer, shape = MaterialTheme.shapes.medium) {
        Column(modifier = Modifier.padding(horizontal = 10.dp, vertical = 8.dp)) {
            Text(label, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onPrimaryContainer)
            Spacer(modifier = Modifier.height(2.dp))
            Text(value, style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.onPrimaryContainer)
        }
    }
}

@Composable
private fun MessagePanel(message: String, isError: Boolean) {
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

private fun formatPercent(value: Double): String {
    return "${(value.coerceIn(0.0, 1.0) * 100).toInt()}%"
}

private fun compactDate(value: String): String {
    return value.replace("T", " ").take(16).ifBlank { "--" }
}
