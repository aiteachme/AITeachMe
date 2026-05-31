package com.aiteachme.android.feature.chat.presentation

import androidx.activity.compose.BackHandler
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInHorizontally
import androidx.compose.animation.slideOutHorizontally
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.calculateEndPadding
import androidx.compose.foundation.layout.calculateStartPadding
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material.icons.automirrored.outlined.Chat
import androidx.compose.material.icons.automirrored.outlined.Send
import androidx.compose.material.icons.outlined.Add
import androidx.compose.material.icons.outlined.Close
import androidx.compose.material.icons.outlined.DeleteOutline
import androidx.compose.material.icons.outlined.History
import androidx.compose.material.icons.outlined.StopCircle
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.ListItem
import androidx.compose.material3.MaterialTheme
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
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.platform.LocalLayoutDirection
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.aiteachme.android.core.data.repository.ChatConversationScope
import com.aiteachme.android.core.network.dto.ChatClientActionItem
import com.aiteachme.android.core.network.dto.ChatSessionItem
import com.aiteachme.android.core.ui.MarkdownText

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ChatScreen(
    contentPadding: PaddingValues,
    scope: ChatConversationScope = ChatConversationScope.Global,
    courseId: String? = null,
    initialPrompt: String? = null,
    initialSessionId: String? = null,
    sceneOverride: String? = null,
    sourceOverride: String? = null,
    titleOverride: String? = null,
    subtitleOverride: String? = null,
    onClientAction: ((ChatClientActionItem) -> Unit)? = null,
    onBack: (() -> Unit)? = null,
    viewModel: ChatViewModel = viewModel(),
) {
    val uiState by viewModel.uiState.collectAsState()
    val listState = rememberLazyListState()
    val lastMessage = uiState.messages.lastOrNull()
    val layoutDirection = LocalLayoutDirection.current
    val edgeToEdgeContentPadding = PaddingValues(
        start = contentPadding.calculateStartPadding(layoutDirection),
        top = 0.dp,
        end = contentPadding.calculateEndPadding(layoutDirection),
        bottom = contentPadding.calculateBottomPadding(),
    )
    var showSessions by remember { mutableStateOf(false) }
    var initialSessionConsumed by remember(scope, courseId, initialSessionId) {
        mutableStateOf(false)
    }
    var initialPromptConsumed by remember(scope, courseId, initialPrompt, sceneOverride, sourceOverride) {
        mutableStateOf(false)
    }

    LaunchedEffect(scope, courseId, initialPrompt, initialSessionId, sceneOverride, sourceOverride) {
        viewModel.activate(
            scope = scope,
            courseId = courseId,
            sceneOverride = sceneOverride,
            sourceOverride = sourceOverride,
        )
        val sessionId = initialSessionId?.trim().orEmpty()
        if (!initialSessionConsumed && sessionId.isNotBlank()) {
            initialSessionConsumed = true
            viewModel.openSession(sessionId)
            return@LaunchedEffect
        }
        val question = initialPrompt?.trim().orEmpty()
        if (!initialPromptConsumed && question.isNotBlank()) {
            initialPromptConsumed = true
            viewModel.updateDraft(question)
            viewModel.send()
        }
    }

    LaunchedEffect(uiState.clientActionVersion) {
        if (uiState.clientActionVersion > 0 && uiState.clientActions.isNotEmpty()) {
            uiState.clientActions.forEach { action ->
                onClientAction?.invoke(action)
            }
            viewModel.consumeClientActions()
        }
    }

    LaunchedEffect(uiState.messages.size, lastMessage?.content?.length, lastMessage?.status) {
        if (uiState.messages.isNotEmpty()) {
            listState.animateScrollToItem(uiState.messages.lastIndex)
        }
    }

    BackHandler(enabled = showSessions) {
        showSessions = false
    }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .padding(edgeToEdgeContentPadding)
            .background(Color.White),
    ) {
        Column(modifier = Modifier.fillMaxSize()) {
            ChatHeader(
                uiState = uiState,
                titleOverride = titleOverride,
                subtitleOverride = subtitleOverride,
                onBack = onBack,
                onOpenSessions = {
                    viewModel.loadSessions()
                    showSessions = true
                },
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
                    modifier = Modifier.weight(1f),
                )
            } else {
                LazyColumn(
                    state = listState,
                    modifier = Modifier
                        .weight(1f)
                        .fillMaxWidth(),
                    contentPadding = PaddingValues(start = 24.dp, top = 26.dp, end = 24.dp, bottom = 18.dp),
                    verticalArrangement = Arrangement.spacedBy(16.dp),
                ) {
                    items(
                        items = uiState.messages,
                        key = { it.id },
                    ) { message ->
                        ChatMessageBubble(message = message)
                    }
                }
            }

            ChatInputDock(
                draft = uiState.draft,
                isStreaming = uiState.isStreaming,
                onDraftChange = viewModel::updateDraft,
                onSend = viewModel::send,
                onStop = viewModel::stop,
            )
        }

        if (showSessions) {
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .background(Color.Black.copy(alpha = 0.28f))
                    .clickable { showSessions = false },
            )
        }

        AnimatedVisibility(
            visible = showSessions,
            enter = slideInHorizontally(initialOffsetX = { -it }) + fadeIn(),
            exit = slideOutHorizontally(targetOffsetX = { -it }) + fadeOut(),
            modifier = Modifier.align(Alignment.CenterStart),
        ) {
            SessionSidebar(
                uiState = uiState,
                onRefresh = viewModel::loadSessions,
                onNewSession = viewModel::createSession,
                onSelect = {
                    viewModel.selectSession(it)
                    showSessions = false
                },
                onDelete = viewModel::deleteSession,
                onClose = { showSessions = false },
            )
        }
    }
}

@Composable
private fun ChatHeader(
    uiState: ChatUiState,
    titleOverride: String?,
    subtitleOverride: String?,
    onBack: (() -> Unit)?,
    onOpenSessions: () -> Unit,
) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = Color.White,
        shadowElevation = 0.dp,
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(start = 18.dp, top = 18.dp, end = 18.dp, bottom = 12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Row(
                modifier = Modifier.width(96.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                if (onBack != null) {
                    IconButton(onClick = onBack, modifier = Modifier.size(40.dp)) {
                        Icon(
                            imageVector = Icons.AutoMirrored.Outlined.ArrowBack,
                            contentDescription = "返回",
                            tint = Color.Black,
                            modifier = Modifier.size(24.dp),
                        )
                    }
                }
            }

            Column(
                modifier = Modifier.weight(1f),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Text(
                    text = chatTitle(uiState = uiState, titleOverride = titleOverride),
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold,
                    color = Color.Black,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                Text(
                    text = subtitleOverride ?: "内容由 AI 生成",
                    style = MaterialTheme.typography.bodySmall,
                    color = Color(0xFF9A9A9A),
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }

            Row(
                modifier = Modifier.width(96.dp),
                horizontalArrangement = Arrangement.End,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                IconButton(onClick = onOpenSessions) {
                    Icon(
                        imageVector = Icons.Outlined.History,
                        contentDescription = "历史对话",
                        tint = Color.Black,
                        modifier = Modifier.size(28.dp),
                    )
                }
            }
        }
    }
}

@Composable
private fun EmptyChat(
    modifier: Modifier = Modifier,
) {
    Box(
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = 28.dp),
    )
}

@Composable
fun SessionSidebar(
    uiState: ChatUiState,
    onRefresh: () -> Unit,
    onNewSession: () -> Unit,
    onSelect: (ChatSessionItem) -> Unit,
    onDelete: (String) -> Unit,
    onClose: () -> Unit,
) {
    Surface(
        modifier = Modifier
            .fillMaxHeight()
            .fillMaxWidth(0.86f)
            .widthIn(max = 360.dp),
        color = MaterialTheme.colorScheme.surface,
        shadowElevation = 16.dp,
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(horizontal = 18.dp, vertical = 18.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.Top,
            ) {
                Column(modifier = Modifier.weight(1f)) {
                    Text("历史对话", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
                    Text(
                        if (uiState.scope == ChatConversationScope.Course) "当前学习空间" else "全局助手",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                IconButton(onClick = onClose) {
                    Icon(imageVector = Icons.Outlined.Close, contentDescription = "关闭历史对话")
                }
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

            if (uiState.isLoadingSessions) {
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    CircularProgressIndicator(modifier = Modifier.size(18.dp), strokeWidth = 2.dp)
                    Text("正在加载会话...")
                }
            } else if (uiState.sessions.isEmpty()) {
                Text("暂无会话。发送第一条消息后也会自动创建。", color = MaterialTheme.colorScheme.onSurfaceVariant)
            } else {
                LazyColumn(
                    modifier = Modifier
                        .weight(1f)
                        .fillMaxWidth(),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                    contentPadding = PaddingValues(bottom = 8.dp),
                ) {
                    items(
                        items = uiState.sessions,
                        key = { it.id },
                    ) { session ->
                        SessionRow(
                            session = session,
                            isCurrent = session.id == uiState.sessionId,
                            onSelect = { onSelect(session) },
                            onDelete = { onDelete(session.id) },
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun SessionRow(
    session: ChatSessionItem,
    isCurrent: Boolean,
    onSelect: () -> Unit,
    onDelete: () -> Unit,
) {
    Surface(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onSelect),
        color = if (isCurrent) {
            MaterialTheme.colorScheme.primaryContainer
        } else {
            MaterialTheme.colorScheme.surfaceContainerLow
        },
        contentColor = if (isCurrent) {
            MaterialTheme.colorScheme.onPrimaryContainer
        } else {
            MaterialTheme.colorScheme.onSurface
        },
        shape = MaterialTheme.shapes.medium,
    ) {
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
            leadingContent = {
                Icon(imageVector = Icons.AutoMirrored.Outlined.Chat, contentDescription = null)
            },
            trailingContent = {
                IconButton(onClick = onDelete) {
                    Icon(imageVector = Icons.Outlined.DeleteOutline, contentDescription = "删除会话")
                }
            },
            colors = androidx.compose.material3.ListItemDefaults.colors(
                containerColor = Color.Transparent,
            ),
        )
    }
}

@Composable
private fun ChatMessageBubble(message: ChatMessageUi) {
    val isUser = message.role == ChatMessageRole.User
    val containerColor = if (isUser) {
        Color(0xFF0B72FF)
    } else {
        Color(0xFFF5F6F8)
    }
    val contentColor = if (isUser) {
        Color.White
    } else {
        Color.Black
    }

    Box(modifier = Modifier.fillMaxWidth()) {
        Surface(
            modifier = Modifier
                .align(if (isUser) Alignment.CenterEnd else Alignment.CenterStart)
                .widthIn(max = 680.dp),
            color = containerColor,
            contentColor = contentColor,
            shape = if (isUser) {
                RoundedCornerShape(topStart = 20.dp, topEnd = 20.dp, bottomStart = 20.dp, bottomEnd = 8.dp)
            } else {
                RoundedCornerShape(topStart = 20.dp, topEnd = 20.dp, bottomStart = 8.dp, bottomEnd = 20.dp)
            },
        ) {
            Column(
                modifier = Modifier.padding(horizontal = 16.dp, vertical = 12.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                if (message.content.isNotBlank()) {
                    MarkdownText(
                        markdown = message.content,
                        color = contentColor,
                        linkColor = if (isUser) Color.White else Color(0xFF0B72FF),
                        textSizeSp = MaterialTheme.typography.bodyLarge.fontSize.value,
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
private fun ChatInputDock(
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
        color = Color.White,
        shadowElevation = 0.dp,
    ) {
        Surface(
            modifier = Modifier
                .fillMaxWidth()
                .padding(start = 14.dp, end = 14.dp, top = 8.dp, bottom = 12.dp),
            color = Color.White,
            shape = RoundedCornerShape(22.dp),
            shadowElevation = 6.dp,
        ) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .heightIn(min = 54.dp)
                    .padding(start = 18.dp, end = 8.dp, top = 8.dp, bottom = 8.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                Box(
                    modifier = Modifier
                        .weight(1f)
                        .heightIn(min = 38.dp),
                    contentAlignment = Alignment.CenterStart,
                ) {
                    BasicTextField(
                        value = draft,
                        onValueChange = onDraftChange,
                        modifier = Modifier.fillMaxWidth(),
                        enabled = !isStreaming,
                        textStyle = MaterialTheme.typography.bodyLarge.copy(color = Color.Black),
                        cursorBrush = SolidColor(Color(0xFF0B72FF)),
                        keyboardOptions = KeyboardOptions(imeAction = ImeAction.Send),
                        keyboardActions = KeyboardActions(
                            onSend = {
                                if (draft.trim().isNotEmpty() && !isStreaming) {
                                    onSend()
                                }
                            },
                        ),
                    )
                    if (draft.isBlank()) {
                        Text(
                            text = "输入消息...",
                            style = MaterialTheme.typography.bodyLarge,
                            color = Color(0xFFA8A8A8),
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                        )
                    }
                }

                if (isStreaming || draft.trim().isNotEmpty()) {
                    IconButton(
                        onClick = {
                            if (isStreaming) {
                                onStop()
                            } else {
                                onSend()
                            }
                        },
                    ) {
                        Icon(
                            imageVector = if (isStreaming) {
                                Icons.Outlined.StopCircle
                            } else {
                                Icons.AutoMirrored.Outlined.Send
                            },
                            contentDescription = if (isStreaming) "停止生成" else "发送",
                            tint = Color(0xFF0B72FF),
                            modifier = Modifier.size(22.dp),
                        )
                    }
                }
            }
        }
    }
}

private fun chatTitle(
    uiState: ChatUiState,
    titleOverride: String?,
): String {
    return titleOverride
        ?: uiState.sessionTitle?.takeIf { it.isNotBlank() }
        ?: if (uiState.scope == ChatConversationScope.Course) {
            uiState.course?.name ?: uiState.courseId ?: "学科内对话"
        } else {
            "全局助手"
        }
}
