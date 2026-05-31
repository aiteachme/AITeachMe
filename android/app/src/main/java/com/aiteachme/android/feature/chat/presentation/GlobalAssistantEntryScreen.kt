package com.aiteachme.android.feature.chat.presentation

import androidx.activity.compose.BackHandler
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInHorizontally
import androidx.compose.animation.slideOutHorizontally
import androidx.compose.foundation.background
import androidx.compose.foundation.border
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
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.Send
import androidx.compose.material.icons.outlined.FolderOpen
import androidx.compose.material.icons.outlined.History
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.aiteachme.android.core.data.repository.ChatConversationScope

@Composable
fun GlobalAssistantEntryScreen(
    contentPadding: PaddingValues,
    onStartChat: (String) -> Unit,
    onOpenSession: (String) -> Unit,
    onOpenFiles: () -> Unit,
    viewModel: ChatViewModel = viewModel(),
) {
    var prompt by rememberSaveable { mutableStateOf("") }
    var showSessions by rememberSaveable { mutableStateOf(false) }
    val uiState by viewModel.uiState.collectAsState()

    LaunchedEffect(Unit) {
        viewModel.activate(scope = ChatConversationScope.Global)
    }

    BackHandler(enabled = showSessions) {
        showSessions = false
    }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(Color.White),
    ) {
        IconButton(
            onClick = {
                viewModel.loadSessions()
                showSessions = true
            },
            modifier = Modifier
                .align(Alignment.TopEnd)
                .padding(contentPadding)
                .padding(top = 16.dp, end = 18.dp),
        ) {
            Icon(
                imageVector = Icons.Outlined.History,
                contentDescription = "历史对话",
                tint = Color.Black,
                modifier = Modifier.size(28.dp),
            )
        }

        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(contentPadding)
                .padding(horizontal = 24.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center,
        ) {
            Text(
                text = "今天想讨论什么？",
                style = MaterialTheme.typography.headlineMedium,
                fontWeight = FontWeight.Black,
                color = Color.Black,
                textAlign = TextAlign.Center,
            )
            Spacer(modifier = Modifier.height(28.dp))
            GlobalAssistantPromptCard(
                prompt = prompt,
                onPromptChange = { prompt = it },
                onOpenFiles = onOpenFiles,
                onSend = {
                    val question = prompt.trim()
                    if (question.isNotBlank()) {
                        prompt = ""
                        onStartChat(question)
                    }
                },
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
                onSelect = { session ->
                    showSessions = false
                    onOpenSession(session.id)
                },
                onDelete = viewModel::deleteSession,
                onClose = { showSessions = false },
            )
        }
    }
}

@Composable
private fun GlobalAssistantPromptCard(
    prompt: String,
    onPromptChange: (String) -> Unit,
    onOpenFiles: () -> Unit,
    onSend: () -> Unit,
) {
    Surface(
        modifier = Modifier
            .fillMaxWidth()
            .border(1.dp, Color(0xFFE5E7EB), RoundedCornerShape(30.dp)),
        color = Color.White,
        shape = RoundedCornerShape(30.dp),
        shadowElevation = 10.dp,
    ) {
        Column(
            modifier = Modifier.padding(18.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            BasicTextField(
                value = prompt,
                onValueChange = onPromptChange,
                modifier = Modifier
                    .fillMaxWidth()
                    .height(132.dp),
                textStyle = TextStyle(
                    color = Color(0xFF111827),
                    fontSize = MaterialTheme.typography.bodyLarge.fontSize,
                    lineHeight = MaterialTheme.typography.bodyLarge.lineHeight,
                ),
                cursorBrush = SolidColor(MaterialTheme.colorScheme.primary),
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Send),
                keyboardActions = KeyboardActions(
                    onSend = {
                        if (prompt.trim().isNotBlank()) {
                            onSend()
                        }
                    },
                ),
                decorationBox = { innerTextField ->
                    Box(modifier = Modifier.fillMaxSize()) {
                        if (prompt.isBlank()) {
                            Text(
                                text = "直接输入问题，也可以先从资料库选择材料一起讨论",
                                style = MaterialTheme.typography.bodyMedium,
                                color = Color(0xFF8A8F9C),
                            )
                        }
                        innerTextField()
                    }
                },
            )

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Row(
                    modifier = Modifier
                        .clip(RoundedCornerShape(999.dp))
                        .padding(horizontal = 2.dp, vertical = 2.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    IconButton(
                        onClick = onOpenFiles,
                        modifier = Modifier.size(32.dp),
                    ) {
                        Icon(
                            imageVector = Icons.Outlined.FolderOpen,
                            contentDescription = "打开资料库",
                            tint = Color(0xFF4B5563),
                            modifier = Modifier.size(18.dp),
                        )
                    }
                    Text(
                        text = "资料库",
                        style = MaterialTheme.typography.bodySmall,
                        color = Color(0xFF374151),
                        fontWeight = FontWeight.SemiBold,
                    )
                }

                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    Text(
                        text = "默认",
                        style = MaterialTheme.typography.bodySmall,
                        color = Color(0xFF4B5563),
                        fontWeight = FontWeight.SemiBold,
                    )
                    IconButton(
                        onClick = onSend,
                        enabled = prompt.trim().isNotBlank(),
                        modifier = Modifier
                            .size(46.dp)
                            .clip(CircleShape)
                            .background(
                                if (prompt.trim().isBlank()) {
                                    Color(0xFFF1F2F5)
                                } else {
                                    MaterialTheme.colorScheme.primary
                                },
                            ),
                    ) {
                        Icon(
                            imageVector = Icons.AutoMirrored.Outlined.Send,
                            contentDescription = "发送问题",
                            tint = if (prompt.trim().isBlank()) {
                                Color(0xFFB8BDC7)
                            } else {
                                MaterialTheme.colorScheme.onPrimary
                            },
                        )
                    }
                }
            }
        }
    }
}
