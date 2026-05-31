package com.aiteachme.android.feature.chat.presentation

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material.icons.automirrored.outlined.Send
import androidx.compose.material.icons.outlined.Add
import androidx.compose.material.icons.outlined.ChatBubbleOutline
import androidx.compose.material.icons.outlined.DeleteOutline
import androidx.compose.material.icons.outlined.FolderOpen
import androidx.compose.material.icons.outlined.StopCircle
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilledIconButton
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.FilledTonalIconButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.ListItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.aiteachme.android.core.data.repository.ChatConversationScope
import com.aiteachme.android.core.network.dto.ChatSessionItem

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ChatScreen(
    contentPadding: PaddingValues,
    scope: ChatConversationScope = ChatConversationScope.Global,
    courseId: String? = null,
    initialPrompt: String? = null,
    onBack: (() -> Unit)? = null,
    viewModel: ChatViewModel = viewModel(),
) {
    val uiState by viewModel.uiState.collectAsState()
    val listState = rememberLazyListState()
    val lastMessage = uiState.messages.lastOrNull()
    var showSessions by remember { mutableStateOf(false) }
    var initialPromptConsumed by remember(scope, courseId, initialPrompt) { mutableStateOf(false) }

    LaunchedEffect(scope, courseId, initialPrompt) {
        viewModel.activate(scope = scope, courseId = courseId)
        val question = initialPrompt?.trim().orEmpty()
        if (!initialPromptConsumed && question.isNotBlank()) {
            initialPromptConsumed = true
            viewModel.updateDraft(question)
            viewModel.send()
        }
    }

    LaunchedEffect(uiState.messages.size, lastMessage?.content?.length, lastMessage?.status) {
        if (uiState.messages.isNotEmpty()) {
            listState.animateScrollToItem(uiState.messages.lastIndex)
        }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(contentPadding),
    ) {
        ChatHeader(
            uiState = uiState,
            onBack = onBack,
            onClear = viewModel::clearMessages,
            onOpenSessions = { showSessions = true },
        )

        uiState.errorMessage?.let { error ->
            Text(
                text = error,
                modifier = Modifier.padding(horizontal = 20.dp, vertical = 6.dp),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.error,
            )
        }

        if (uiState.isLoadingMessages) {
            Box(
                modifier = Modifier
                    .weight(1f)
                    .fillMaxWidth(),
                contentAlignment = Alignment.Center,
            ) {
                CircularProgressIndicator()
            }
        } else if (uiState.messages.isEmpty()) {
            EmptyChat(
                uiState = uiState,
                modifier = Modifier.weight(1f),
            )
        } else {
            LazyColumn(
                state = listState,
                modifier = Modifier
                    .weight(1f)
                    .fillMaxWidth(),
                contentPadding = PaddingValues(horizontal = 16.dp, vertical = 12.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                items(
                    items = uiState.messages,
                    key = { it.id },
                ) { message ->
                    ChatMessageBubble(message = message)
                }
            }
        }

        ChatComposer(
            draft = uiState.draft,
            isStreaming = uiState.isStreaming,
            onDraftChange = viewModel::updateDraft,
            onSend = viewModel::send,
            onStop = viewModel::stop,
        )
    }

    if (showSessions) {
        ModalBottomSheet(onDismissRequest = { showSessions = false }) {
            SessionSheet(
                uiState = uiState,
                onRefresh = viewModel::loadSessions,
                onNewSession = viewModel::createSession,
                onSelect = {
                    viewModel.selectSession(it)
                    showSessions = false
                },
                onDelete = viewModel::deleteSession,
            )
        }
    }
}

@Composable
private fun ChatHeader(
    uiState: ChatUiState,
    onBack: (() -> Unit)?,
    onClear: () -> Unit,
    onOpenSessions: () -> Unit,
) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = MaterialTheme.colorScheme.background,
    ) {
        Column(
            modifier = Modifier.padding(horizontal = 20.dp, vertical = 14.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(12.dp),
                verticalAlignment = Alignment.CenterVertically,
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
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = if (uiState.scope == ChatConversationScope.Course) "学科内对话" else "全局助手",
                        style = MaterialTheme.typography.headlineSmall,
                        fontWeight = FontWeight.SemiBold,
                    )
                    Text(
                        text = headerSubtitle(uiState),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
                FilledTonalButton(onClick = onOpenSessions) {
                    Icon(
                        imageVector = Icons.Outlined.ChatBubbleOutline,
                        contentDescription = null,
                        modifier = Modifier.size(18.dp),
                    )
                    Spacer(modifier = Modifier.width(8.dp))
                    Text("会话")
                }
            }

            ScopeHint(uiState = uiState)

            FilledTonalButton(
                onClick = onClear,
                enabled = uiState.messages.isNotEmpty() && !uiState.isStreaming,
            ) {
                Icon(
                    imageVector = Icons.Outlined.DeleteOutline,
                    contentDescription = null,
                    modifier = Modifier.size(18.dp),
                )
                Spacer(modifier = Modifier.width(8.dp))
                Text("清空当前")
            }
        }
    }
}

@Composable
private fun ScopeHint(uiState: ChatUiState) {
    val isCourse = uiState.scope == ChatConversationScope.Course
    Surface(
        color = if (isCourse) {
            MaterialTheme.colorScheme.primaryContainer
        } else {
            MaterialTheme.colorScheme.surfaceContainer
        },
        contentColor = if (isCourse) {
            MaterialTheme.colorScheme.onPrimaryContainer
        } else {
            MaterialTheme.colorScheme.onSurface
        },
        shape = MaterialTheme.shapes.medium,
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 10.dp, vertical = 7.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Icon(
                imageVector = Icons.Outlined.FolderOpen,
                contentDescription = null,
                modifier = Modifier.size(16.dp),
            )
            Text(
                text = if (isCourse) {
                    "绑定当前学习空间：${uiState.course?.name ?: uiState.courseId ?: "未知学科"}"
                } else {
                    "不绑定学科。要问某个学科的问题，请从学习空间左滑进入学科内对话。"
                },
                style = MaterialTheme.typography.bodySmall,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
            )
        }
    }
}

@Composable
private fun EmptyChat(
    uiState: ChatUiState,
    modifier: Modifier = Modifier,
) {
    Box(
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = 28.dp),
        contentAlignment = Alignment.Center,
    ) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Text(
                text = if (uiState.scope == ChatConversationScope.Course) "问当前学科的问题" else "问一个通用学习问题",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold,
            )
            Text(
                text = if (uiState.scope == ChatConversationScope.Course) {
                    "这个入口只服务当前学习空间，不会切到全局会话。"
                } else {
                    "全局助手负责跨学科规划和通用问题，不会混入某个学科的会话。"
                },
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun SessionSheet(
    uiState: ChatUiState,
    onRefresh: () -> Unit,
    onNewSession: () -> Unit,
    onSelect: (ChatSessionItem) -> Unit,
    onDelete: (String) -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(start = 20.dp, end = 20.dp, bottom = 24.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text("会话管理", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.SemiBold)
                Text(
                    if (uiState.scope == ChatConversationScope.Course) "只显示当前学习空间会话" else "只显示全局会话",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                FilledTonalButton(onClick = onRefresh, enabled = !uiState.isLoadingSessions) {
                    Text("刷新")
                }
                Button(onClick = onNewSession, enabled = !uiState.isLoadingSessions) {
                    Icon(imageVector = Icons.Outlined.Add, contentDescription = null, modifier = Modifier.size(18.dp))
                    Spacer(modifier = Modifier.width(6.dp))
                    Text("新建")
                }
            }
        }

        if (uiState.isLoadingSessions) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                CircularProgressIndicator(modifier = Modifier.size(18.dp), strokeWidth = 2.dp)
                Text("正在加载会话...")
            }
        } else if (uiState.sessions.isEmpty()) {
            Text("暂无会话。发送第一条消息后也会自动创建。", color = MaterialTheme.colorScheme.onSurfaceVariant)
        } else {
            uiState.sessions.forEach { session ->
                ListItem(
                    headlineContent = {
                        Text(session.title.ifBlank { "未命名会话" }, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    },
                    supportingContent = {
                        Text(
                            "${session.messageCount} 条消息 · ${session.lastMessageAt.ifBlank { session.updatedAt }}",
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                        )
                    },
                    trailingContent = {
                        IconButton(onClick = { onDelete(session.id) }) {
                            Icon(imageVector = Icons.Outlined.DeleteOutline, contentDescription = "删除会话")
                        }
                    },
                    modifier = Modifier.fillMaxWidth(),
                    leadingContent = {
                        if (session.id == uiState.sessionId) {
                            Text("当前", color = MaterialTheme.colorScheme.primary)
                        }
                    },
                )
                Button(
                    onClick = { onSelect(session) },
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Text(if (session.id == uiState.sessionId) "继续当前会话" else "打开会话")
                }
            }
        }
    }
}

@Composable
private fun ChatMessageBubble(message: ChatMessageUi) {
    val isUser = message.role == ChatMessageRole.User
    val containerColor = if (isUser) {
        MaterialTheme.colorScheme.primary
    } else {
        MaterialTheme.colorScheme.surfaceContainer
    }
    val contentColor = if (isUser) {
        MaterialTheme.colorScheme.onPrimary
    } else {
        MaterialTheme.colorScheme.onSurface
    }

    Box(modifier = Modifier.fillMaxWidth()) {
        Surface(
            modifier = Modifier
                .align(if (isUser) Alignment.CenterEnd else Alignment.CenterStart)
                .widthIn(max = 640.dp),
            color = containerColor,
            contentColor = contentColor,
            shape = MaterialTheme.shapes.large,
        ) {
            Column(
                modifier = Modifier.padding(horizontal = 14.dp, vertical = 12.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                if (message.content.isNotBlank()) {
                    Text(
                        text = message.content,
                        style = MaterialTheme.typography.bodyMedium,
                        color = contentColor,
                    )
                }
                if (message.status == ChatMessageStatus.Streaming) {
                    StreamingStatus(
                        detail = message.statusDetail ?: "正在生成",
                        color = contentColor,
                    )
                }
                if (message.status == ChatMessageStatus.Error || message.status == ChatMessageStatus.Interrupted) {
                    Text(
                        text = message.errorDetail ?: "发送失败",
                        style = MaterialTheme.typography.bodySmall,
                        color = if (isUser) contentColor else MaterialTheme.colorScheme.error,
                    )
                }
            }
        }
    }
}

@Composable
private fun StreamingStatus(
    detail: String,
    color: Color,
) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        CircularProgressIndicator(
            modifier = Modifier.size(14.dp),
            strokeWidth = 2.dp,
            color = color,
        )
        Text(
            text = detail,
            style = MaterialTheme.typography.bodySmall,
            color = color,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

@Composable
private fun ChatComposer(
    draft: String,
    isStreaming: Boolean,
    onDraftChange: (String) -> Unit,
    onSend: () -> Unit,
    onStop: () -> Unit,
) {
    Surface(
        modifier = Modifier
            .fillMaxWidth()
            .imePadding(),
        color = MaterialTheme.colorScheme.surface,
        shadowElevation = 3.dp,
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 14.dp, vertical = 10.dp),
            verticalAlignment = Alignment.Bottom,
            horizontalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            OutlinedTextField(
                value = draft,
                onValueChange = onDraftChange,
                modifier = Modifier.weight(1f),
                placeholder = { Text("输入问题") },
                minLines = 1,
                maxLines = 4,
                enabled = !isStreaming,
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Send),
                keyboardActions = KeyboardActions(
                    onSend = {
                        if (draft.trim().isNotEmpty() && !isStreaming) {
                            onSend()
                        }
                    },
                ),
            )

            if (isStreaming) {
                FilledTonalIconButton(onClick = onStop) {
                    Icon(
                        imageVector = Icons.Outlined.StopCircle,
                        contentDescription = "停止生成",
                    )
                }
            } else {
                FilledIconButton(
                    onClick = onSend,
                    enabled = draft.trim().isNotEmpty(),
                ) {
                    Icon(
                        imageVector = Icons.AutoMirrored.Outlined.Send,
                        contentDescription = "发送",
                    )
                }
            }
        }
    }
}

private fun headerSubtitle(uiState: ChatUiState): String {
    uiState.streamStatus?.let { status -> return status }
    uiState.sessionTitle?.let { title -> return title }
    uiState.sessionId?.let { sessionId -> return "会话 ${sessionId.takeLast(8)}" }
    return if (uiState.scope == ChatConversationScope.Course) {
        uiState.course?.name ?: uiState.courseId ?: "学科内对话"
    } else {
        "不绑定学科"
    }
}
