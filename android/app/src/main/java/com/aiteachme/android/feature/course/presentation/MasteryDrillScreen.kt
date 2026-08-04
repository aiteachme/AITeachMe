package com.aiteachme.android.feature.course.presentation

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
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material.icons.outlined.CheckCircle
import androidx.compose.material.icons.outlined.ErrorOutline
import androidx.compose.material.icons.outlined.Quiz
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
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
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.aiteachme.android.core.network.dto.QuestionTemplateItemResponse
import com.aiteachme.android.core.ui.MarkdownText

@Composable
fun MasteryDrillScreen(
    courseId: String,
    contentPadding: PaddingValues,
    onBack: () -> Unit,
    onOpenPractice: (String) -> Unit,
    viewModel: MasteryDrillViewModel = viewModel(),
) {
    val state by viewModel.uiState.collectAsState()

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
            MasteryDrillHeader(
                state = state,
                onBack = onBack,
                onRestart = viewModel::restart,
            )
        }

        state.errorMessage?.let { message ->
            item { DrillMessageCard(message = message, isError = true) }
        }

        when {
            state.isLoading -> {
                item { DrillLoadingCard() }
            }
            state.selectedTemplates.isEmpty() -> {
                item {
                    EmptyDrillCard(
                        onOpenPractice = { onOpenPractice(courseId) },
                    )
                }
            }
            state.currentTemplate == null -> {
                item {
                    DrillCompletedCard(
                        totalCount = state.selectedTemplates.size,
                        wrongAttemptCount = state.wrongAttemptCount,
                        onRestart = viewModel::restart,
                    )
                }
            }
            else -> {
                item {
                    DrillQuestionCard(
                        state = state,
                        template = state.currentTemplate!!,
                        answer = state.answers[state.currentTemplate!!.id].orEmpty(),
                        onAnswerChange = { value -> viewModel.updateAnswer(state.currentTemplate!!.id, value) },
                        onCheck = { viewModel.checkCurrentAnswer(courseId) },
                        onContinue = viewModel::continueAfterFeedback,
                    )
                }
            }
        }
    }
}

@Composable
private fun MasteryDrillHeader(
    state: MasteryDrillUiState,
    onBack: () -> Unit,
    onRestart: () -> Unit,
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
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.Top,
            ) {
                IconButton(onClick = onBack, modifier = Modifier.size(40.dp)) {
                    Icon(Icons.AutoMirrored.Outlined.ArrowBack, contentDescription = "返回")
                }
                OutlinedButton(
                    onClick = onRestart,
                    enabled = state.selectedTemplates.isNotEmpty() && !state.isLoading,
                ) {
                    Icon(Icons.Outlined.Refresh, contentDescription = null, modifier = Modifier.size(16.dp))
                    Spacer(modifier = Modifier.width(6.dp))
                    Text("重新抽题")
                }
            }

            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text(
                    text = "闯关测试",
                    style = MaterialTheme.typography.headlineSmall,
                    fontWeight = FontWeight.Black,
                )
                Text(
                    text = "从题库模板抽题，一题一判；每次作答都会自动保存，可跨设备恢复并进入训练历史。",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }

            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                DrillStatChip(label = "本轮", value = state.selectedTemplates.size.toString(), modifier = Modifier.weight(1f))
                DrillStatChip(label = "已通过", value = state.completedIds.size.toString(), modifier = Modifier.weight(1f))
                DrillStatChip(label = "回炉", value = state.wrongAttemptCount.toString(), modifier = Modifier.weight(1f))
            }
        }
    }
}

@Composable
private fun DrillStatChip(
    label: String,
    value: String,
    modifier: Modifier = Modifier,
) {
    Surface(
        modifier = modifier,
        color = MaterialTheme.colorScheme.surface,
        shape = MaterialTheme.shapes.medium,
    ) {
        Column(
            modifier = Modifier.padding(horizontal = 12.dp, vertical = 10.dp),
            verticalArrangement = Arrangement.spacedBy(2.dp),
        ) {
            Text(value, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
            Text(label, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

@Composable
private fun DrillQuestionCard(
    state: MasteryDrillUiState,
    template: QuestionTemplateItemResponse,
    answer: String,
    onAnswerChange: (String) -> Unit,
    onCheck: () -> Unit,
    onContinue: () -> Unit,
) {
    val feedback = state.feedback?.takeIf { it.templateId == template.id }
    val isSupported = isSupportedExamQuestionType(template.questionType)
    val choices = template.drillChoices()
    val isMultipleChoice = template.questionType.lowercase() in setOf("multiple_choice", "multi_choice")
    val currentNumber = state.selectedTemplates.indexOfFirst { it.id == template.id }.takeIf { it >= 0 }?.plus(1) ?: 1

    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = MaterialTheme.colorScheme.surface,
        shape = MaterialTheme.shapes.large,
        tonalElevation = 1.dp,
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp), verticalAlignment = Alignment.CenterVertically) {
                    Surface(
                        modifier = Modifier
                            .size(36.dp)
                            .clip(CircleShape),
                        color = MaterialTheme.colorScheme.primary,
                        shape = CircleShape,
                    ) {
                        Box(contentAlignment = Alignment.Center) {
                            Text(
                                text = currentNumber.toString(),
                                color = MaterialTheme.colorScheme.onPrimary,
                                style = MaterialTheme.typography.titleSmall,
                                fontWeight = FontWeight.Bold,
                            )
                        }
                    }
                    Column {
                        Text("当前题目", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
                        Text(
                            text = questionTypeLabel(template.questionType),
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
                Text(
                    text = template.difficulty.ifBlank { "默认难度" },
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }

            MarkdownText(
                markdown = template.stem,
                textSizeSp = 17f,
                color = MaterialTheme.colorScheme.onSurface,
                linkColor = MaterialTheme.colorScheme.primary,
            )

            if (!isSupported) {
                Surface(
                    color = MaterialTheme.colorScheme.errorContainer,
                    shape = MaterialTheme.shapes.medium,
                ) {
                    Row(
                        modifier = Modifier.padding(12.dp),
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                        verticalAlignment = Alignment.Top,
                    ) {
                        Icon(Icons.Outlined.ErrorOutline, contentDescription = null, modifier = Modifier.size(18.dp))
                        Text("该题型尚未在当前客户端发布，已停止本题作答和判分。")
                    }
                }
            } else if (choices.isNotEmpty()) {
                Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    choices.forEach { choice ->
                        DrillChoiceRow(
                            choice = choice,
                            template = template,
                            answer = answer,
                            isMultipleChoice = isMultipleChoice,
                            feedback = feedback,
                            isCheckingAnswer = state.isCheckingAnswer,
                            onAnswerChange = onAnswerChange,
                        )
                    }
                }
            } else {
                OutlinedTextField(
                    value = answer,
                    onValueChange = onAnswerChange,
                    enabled = feedback == null && !state.isCheckingAnswer,
                    modifier = Modifier.fillMaxWidth(),
                    minLines = 3,
                    maxLines = 6,
                    placeholder = { Text("输入你的作答") },
                )
            }

            feedback?.let {
                DrillFeedbackBlock(template = template, feedback = it)
            }

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.End,
            ) {
                if (feedback == null) {
                    Button(
                        onClick = onCheck,
                        enabled = isSupported && answer.trim().isNotEmpty() && !state.isCheckingAnswer,
                    ) {
                        if (state.isCheckingAnswer) {
                            CircularProgressIndicator(modifier = Modifier.size(18.dp), strokeWidth = 2.dp)
                        } else {
                            Icon(Icons.Outlined.Quiz, contentDescription = null, modifier = Modifier.size(18.dp))
                        }
                        Spacer(modifier = Modifier.width(8.dp))
                        Text(
                            if (!state.isCheckingAnswer) {
                                "检查答案"
                            } else if (isAiGradedExamQuestionType(template.questionType)) {
                                "AI 判题中"
                            } else {
                                "判题中"
                            }
                        )
                    }
                } else {
                    FilledTonalButton(onClick = onContinue) {
                        Icon(
                            imageVector = if (feedback.isCorrect) Icons.Outlined.CheckCircle else Icons.Outlined.Refresh,
                            contentDescription = null,
                            modifier = Modifier.size(18.dp),
                        )
                        Spacer(modifier = Modifier.width(8.dp))
                        Text(if (feedback.isCorrect) "继续" else "重新入队")
                    }
                }
            }
        }
    }
}

@Composable
private fun DrillChoiceRow(
    choice: DrillChoice,
    template: QuestionTemplateItemResponse,
    answer: String,
    isMultipleChoice: Boolean,
    feedback: MasteryDrillFeedback?,
    isCheckingAnswer: Boolean,
    onAnswerChange: (String) -> Unit,
) {
    val selectedAnswers = drillSplitMultiChoiceAnswer(answer)
    val isSelected = if (isMultipleChoice) {
        selectedAnswers.contains(choice.value)
    } else {
        answer == choice.value
    }
    val isCorrectChoice = isChoiceCorrect(template, choice.value)
    val showCorrect = feedback != null && isCorrectChoice
    val showWrong = feedback != null && isSelected && !isCorrectChoice
    val containerColor = when {
        showCorrect -> Color(0xFFE8F7EF)
        showWrong -> Color(0xFFFDECEC)
        isSelected -> MaterialTheme.colorScheme.primaryContainer
        else -> MaterialTheme.colorScheme.surfaceContainer
    }
    val contentColor = when {
        showCorrect -> Color(0xFF146C43)
        showWrong -> MaterialTheme.colorScheme.error
        isSelected -> MaterialTheme.colorScheme.onPrimaryContainer
        else -> MaterialTheme.colorScheme.onSurface
    }

    Surface(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(enabled = feedback == null && !isCheckingAnswer) {
                if (isMultipleChoice) {
                    val next = selectedAnswers.toMutableSet()
                    if (!next.add(choice.value)) {
                        next.remove(choice.value)
                    }
                    onAnswerChange(next.sorted().joinToString(","))
                } else {
                    onAnswerChange(if (isSelected) "" else choice.value)
                }
            },
        color = containerColor,
        contentColor = contentColor,
        shape = MaterialTheme.shapes.medium,
    ) {
        Row(
            modifier = Modifier.padding(12.dp),
            horizontalArrangement = Arrangement.spacedBy(10.dp),
            verticalAlignment = Alignment.Top,
        ) {
            Text(
                text = choice.label,
                style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.Bold,
                modifier = Modifier.width(28.dp),
            )
            MarkdownText(
                markdown = choice.content,
                modifier = Modifier.weight(1f),
                textSizeSp = 15f,
                color = contentColor,
                linkColor = MaterialTheme.colorScheme.primary,
            )
        }
    }
}

@Composable
private fun DrillFeedbackBlock(
    template: QuestionTemplateItemResponse,
    feedback: MasteryDrillFeedback,
) {
    val color = if (feedback.isCorrect) Color(0xFF146C43) else MaterialTheme.colorScheme.error
    val background = if (feedback.isCorrect) Color(0xFFE8F7EF) else Color(0xFFFDECEC)

    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = background,
        shape = MaterialTheme.shapes.medium,
    ) {
        Column(
            modifier = Modifier.padding(14.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                Icon(
                    imageVector = if (feedback.isCorrect) Icons.Outlined.CheckCircle else Icons.Outlined.ErrorOutline,
                    contentDescription = null,
                    tint = color,
                    modifier = Modifier.size(20.dp),
                )
                Text(
                    text = if (feedback.isCorrect) "答对了" else "答错了，稍后会重新出现",
                    style = MaterialTheme.typography.titleSmall,
                    color = color,
                    fontWeight = FontWeight.SemiBold,
                )
            }
            DrillAnswerLine(title = "你的答案", content = feedback.answer)
            DrillAnswerLine(title = "正确答案", content = template.answer)
            feedback.feedbackText?.takeIf { it.isNotBlank() }?.let { content ->
                DrillAnswerLine(title = "判题反馈", content = content)
            }
            DrillAnswerLine(title = "解析", content = template.explanation.ifBlank { "暂无解析" })
        }
    }
}

@Composable
private fun DrillAnswerLine(
    title: String,
    content: String,
) {
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Text(title, style = MaterialTheme.typography.labelMedium, fontWeight = FontWeight.SemiBold)
        MarkdownText(
            markdown = content.ifBlank { "未作答" },
            textSizeSp = 14f,
            color = MaterialTheme.colorScheme.onSurface,
            linkColor = MaterialTheme.colorScheme.primary,
        )
    }
}

@Composable
private fun DrillCompletedCard(
    totalCount: Int,
    wrongAttemptCount: Int,
    onRestart: () -> Unit,
) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = Color(0xFFE8F7EF),
        shape = MaterialTheme.shapes.large,
    ) {
        Column(
            modifier = Modifier.padding(24.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Icon(Icons.Outlined.CheckCircle, contentDescription = null, tint = Color(0xFF146C43), modifier = Modifier.size(44.dp))
            Text("$totalCount 题全部通过", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
            Text(
                "本轮回炉 $wrongAttemptCount 次；结果只保留在当前闯关会话，不生成试卷历史。",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Button(onClick = onRestart) {
                Icon(Icons.Outlined.Refresh, contentDescription = null, modifier = Modifier.size(18.dp))
                Spacer(modifier = Modifier.width(8.dp))
                Text("再来一轮")
            }
        }
    }
}

@Composable
private fun EmptyDrillCard(
    onOpenPractice: () -> Unit,
) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = MaterialTheme.colorScheme.surfaceContainer,
        shape = MaterialTheme.shapes.large,
    ) {
        Column(
            modifier = Modifier.padding(22.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text("还没有可用于闯关的题目", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
            Text(
                "闯关只使用已经沉淀到题库的模板。先生成一次专项练习或整卷测试，题目进入题库后再来闯关。",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Button(onClick = onOpenPractice) {
                Text("去练习考试页")
            }
        }
    }
}

@Composable
private fun DrillLoadingCard() {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = MaterialTheme.colorScheme.surfaceContainer,
        shape = MaterialTheme.shapes.large,
    ) {
        Row(
            modifier = Modifier.padding(20.dp),
            horizontalArrangement = Arrangement.spacedBy(10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            CircularProgressIndicator(modifier = Modifier.size(18.dp), strokeWidth = 2.dp)
            Text("正在加载题库模板...")
        }
    }
}

@Composable
private fun DrillMessageCard(
    message: String,
    isError: Boolean,
) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = if (isError) MaterialTheme.colorScheme.errorContainer else MaterialTheme.colorScheme.primaryContainer,
        shape = MaterialTheme.shapes.medium,
    ) {
        Text(
            text = message,
            modifier = Modifier.padding(12.dp),
            style = MaterialTheme.typography.bodySmall,
            color = if (isError) MaterialTheme.colorScheme.onErrorContainer else MaterialTheme.colorScheme.onPrimaryContainer,
        )
    }
}

private data class DrillChoice(
    val label: String,
    val value: String,
    val content: String,
)

private fun QuestionTemplateItemResponse.drillChoices(): List<DrillChoice> {
    val type = questionType.lowercase()
    if (type == "true_false" && options.isNullOrEmpty()) {
        return listOf(
            DrillChoice(label = "T", value = "true", content = "正确"),
            DrillChoice(label = "F", value = "false", content = "错误"),
        )
    }
    return options.orEmpty().mapIndexed { index, option ->
        val label = ('A'.code + index).toChar().toString()
        DrillChoice(label = label, value = label, content = option)
    }
}

private fun isChoiceCorrect(
    template: QuestionTemplateItemResponse,
    choiceValue: String,
): Boolean {
    return when (template.questionType.lowercase()) {
        "multiple_choice", "multi_choice" -> drillSplitMultiChoiceAnswer(template.answer).contains(choiceValue)
        "true_false" -> normalizeTrueFalseForDisplay(template.answer) == normalizeTrueFalseForDisplay(choiceValue)
        else -> drillNormalizeTextAnswer(template.answer) == drillNormalizeTextAnswer(choiceValue)
    }
}

private fun normalizeTrueFalseForDisplay(value: String?): String {
    return when (drillNormalizeTextAnswer(value)) {
        "true", "t", "yes", "y", "正确", "对", "是" -> "true"
        "false", "f", "no", "n", "错误", "错", "否" -> "false"
        else -> drillNormalizeTextAnswer(value)
    }
}

private fun questionTypeLabel(type: String): String {
    return when (type.lowercase()) {
        "single_choice" -> "单选题"
        "multiple_choice", "multi_choice" -> "多选题"
        "true_false" -> "判断题"
        "fill_blank" -> "填空题"
        "short_answer" -> "简答题"
        "essay" -> "论述题"
        else -> type.ifBlank { "题目" }
    }
}
