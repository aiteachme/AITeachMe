package com.aiteachme.android.feature.course.presentation

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
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.Icon
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.aiteachme.android.core.network.dto.SettingEntry
import com.aiteachme.android.core.network.dto.SettingSection

@Composable
fun SettingsDashboardScreen(
    courseId: String,
    contentPadding: PaddingValues,
    onBack: () -> Unit,
    onOpenBuild: (String) -> Unit,
    viewModel: SettingsViewModel = viewModel(),
) {
    val state by viewModel.uiState.collectAsState()
    LaunchedEffect(Unit) {
        viewModel.load()
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
                    Text("设置与反馈", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.SemiBold)
                    Text(courseId, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                FilledTonalButton(onClick = viewModel::load, enabled = !state.isLoading) {
                    if (state.isLoading) {
                        CircularProgressIndicator(modifier = Modifier.size(16.dp), strokeWidth = 2.dp)
                    } else {
                        Icon(Icons.Outlined.Refresh, contentDescription = "刷新", modifier = Modifier.size(18.dp))
                    }
                }
            }
        }
        state.errorMessage?.let { item { SettingsMessage(it, true) } }
        state.infoMessage?.let { item { SettingsMessage(it, false) } }
        item {
            Surface(color = MaterialTheme.colorScheme.surfaceContainer, shape = MaterialTheme.shapes.large) {
                Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    Text("当前学习空间", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
                    Text(
                        "学科名称、学习目标和知识结构仍通过构建规划统一调整。",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Button(onClick = { onOpenBuild(courseId) }, modifier = Modifier.fillMaxWidth()) {
                        Text("打开构建规划")
                    }
                }
            }
        }
        state.settings?.sections.orEmpty().forEach { section ->
            item { SettingSectionCard(section) }
        }
        item {
            Surface(color = MaterialTheme.colorScheme.surface, shape = MaterialTheme.shapes.large, tonalElevation = 1.dp) {
                Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    Text("问题反馈", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
                    OutlinedTextField(
                        value = state.feedbackDraft,
                        onValueChange = viewModel::updateFeedbackDraft,
                        modifier = Modifier.fillMaxWidth(),
                        minLines = 3,
                        maxLines = 5,
                        placeholder = { Text("描述你在安卓端遇到的问题或功能建议") },
                    )
                    Button(
                        onClick = viewModel::submitFeedback,
                        enabled = state.feedbackDraft.isNotBlank() && !state.isSubmittingFeedback,
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        if (state.isSubmittingFeedback) {
                            CircularProgressIndicator(modifier = Modifier.size(16.dp), strokeWidth = 2.dp)
                        }
                        Text(if (state.isSubmittingFeedback) "提交中" else "提交反馈")
                    }
                }
            }
        }
    }
}

@Composable
private fun SettingSectionCard(section: SettingSection) {
    Surface(color = MaterialTheme.colorScheme.surface, shape = MaterialTheme.shapes.large, tonalElevation = 1.dp) {
        Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text(section.title.ifBlank { section.key }, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
            if (section.entries.isEmpty()) {
                Text("暂无可显示配置。", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            } else {
                section.entries.take(8).forEach { entry ->
                    SettingEntryRow(entry)
                }
            }
        }
    }
}

@Composable
private fun SettingEntryRow(entry: SettingEntry) {
    Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        Column(modifier = Modifier.weight(1f)) {
            Text(entry.label.ifBlank { entry.key }, style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.Medium)
            Text(
                entry.description.ifBlank { entry.source },
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
        Text(
            formatSettingValue(entry),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

@Composable
private fun SettingsMessage(message: String, isError: Boolean) {
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

private fun formatSettingValue(entry: SettingEntry): String {
    if (entry.sensitive) return "******"
    return entry.value?.toString()?.takeIf { it.isNotBlank() } ?: "--"
}
