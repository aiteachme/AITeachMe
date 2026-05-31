package com.aiteachme.android.feature.chat.presentation

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.aiteachme.android.core.data.repository.ChatConversationScope
import com.aiteachme.android.core.di.AppServices
import com.aiteachme.android.core.network.dto.ChatClientActionItem
import com.aiteachme.android.core.network.dto.ChatDoneData
import com.aiteachme.android.core.network.dto.ChatMessageItem
import com.aiteachme.android.core.network.dto.ChatSendRequest
import com.aiteachme.android.core.network.dto.ChatSessionItem
import com.aiteachme.android.core.network.dto.ChatStatusData
import com.aiteachme.android.core.network.dto.CourseItem
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

enum class ChatMessageRole {
    User,
    Assistant,
}

enum class ChatMessageStatus {
    Ready,
    Streaming,
    Error,
    Interrupted,
}

data class ChatMessageUi(
    val id: String,
    val role: ChatMessageRole,
    val content: String,
    val status: ChatMessageStatus,
    val turnId: String? = null,
    val statusDetail: String? = null,
    val errorDetail: String? = null,
    val createdAtMillis: Long = System.currentTimeMillis(),
)

data class ChatUiState(
    val scope: ChatConversationScope = ChatConversationScope.Global,
    val courseId: String? = null,
    val course: CourseItem? = null,
    val sceneOverride: String? = null,
    val sourceOverride: String? = null,
    val sessions: List<ChatSessionItem> = emptyList(),
    val messages: List<ChatMessageUi> = emptyList(),
    val draft: String = "",
    val sessionId: String? = null,
    val sessionTitle: String? = null,
    val isLoadingSessions: Boolean = false,
    val isLoadingMessages: Boolean = false,
    val isStreaming: Boolean = false,
    val streamStatus: String? = null,
    val errorMessage: String? = null,
    val clientActions: List<ChatClientActionItem> = emptyList(),
    val clientActionVersion: Long = 0L,
)

class ChatViewModel : ViewModel() {
    private val chatRepository = AppServices.chatRepository
    private val courseContext = AppServices.courseContextStore
    private var streamJob: Job? = null

    private val _uiState = MutableStateFlow(ChatUiState())
    val uiState: StateFlow<ChatUiState> = _uiState.asStateFlow()

    init {
        viewModelScope.launch {
            courseContext.state.collect { context ->
                _uiState.update { current ->
                    current.copy(
                        course = current.courseId?.let { courseId ->
                            context.courses.firstOrNull { it.courseId == courseId }
                        },
                    )
                }
            }
        }
    }

    fun activate(
        scope: ChatConversationScope,
        courseId: String? = null,
        sceneOverride: String? = null,
        sourceOverride: String? = null,
    ) {
        if (_uiState.value.isStreaming) {
            return
        }
        val normalizedCourseId = courseId?.takeIf { it.isNotBlank() }
        val normalizedScene = sceneOverride?.trim()?.takeIf { it.isNotBlank() }
        val normalizedSource = sourceOverride?.trim()?.takeIf { it.isNotBlank() }
        if (scope == ChatConversationScope.Course && normalizedCourseId == null) {
            _uiState.update { it.copy(errorMessage = "缺少学科 ID，无法进入学科对话。") }
            return
        }

        val context = courseContext.state.value
        val nextCourse = normalizedCourseId?.let { id ->
            context.courses.firstOrNull { it.courseId == id }
        }
        val state = _uiState.value
        val changed = state.scope != scope ||
            state.courseId != normalizedCourseId ||
            state.sceneOverride != normalizedScene ||
            state.sourceOverride != normalizedSource

        _uiState.update {
            it.copy(
                scope = scope,
                courseId = if (scope == ChatConversationScope.Course) normalizedCourseId else null,
                course = if (scope == ChatConversationScope.Course) nextCourse else null,
                sceneOverride = normalizedScene,
                sourceOverride = normalizedSource,
                errorMessage = null,
            )
        }

        if (changed) {
            resetCurrentSession()
        }
        loadSessions()
    }

    fun loadSessions() {
        val state = _uiState.value
        if (!state.hasValidScope()) {
            _uiState.update { it.copy(sessions = emptyList()) }
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(isLoadingSessions = true, errorMessage = null) }
            runCatching {
                chatRepository.listSessions(
                    scope = state.scope,
                    courseId = state.courseId,
                )
            }.onSuccess { sessions ->
                _uiState.update {
                    it.copy(
                        sessions = sessions,
                        isLoadingSessions = false,
                    )
                }
            }.onFailure { throwable ->
                _uiState.update {
                    it.copy(
                        isLoadingSessions = false,
                        errorMessage = throwable.message ?: throwable::class.java.simpleName,
                    )
                }
            }
        }
    }

    fun createSession() {
        val state = _uiState.value
        if (state.isStreaming || !state.hasValidScope()) {
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(isLoadingSessions = true, errorMessage = null) }
            runCatching {
                chatRepository.createSession(
                    scope = state.scope,
                    courseId = state.courseId,
                    title = if (state.scope == ChatConversationScope.Course) {
                        "${state.course?.name ?: "学科"}对话"
                    } else {
                        "新的全局对话"
                    },
                    source = state.requestSource(),
                )
            }.onSuccess { session ->
                _uiState.update {
                    it.copy(
                        sessionId = session.id,
                        sessionTitle = session.title,
                        messages = emptyList(),
                        sessions = listOf(session) + it.sessions.filterNot { item -> item.id == session.id },
                        isLoadingSessions = false,
                    )
                }
            }.onFailure { throwable ->
                _uiState.update {
                    it.copy(
                        isLoadingSessions = false,
                        errorMessage = throwable.message ?: throwable::class.java.simpleName,
                    )
                }
            }
        }
    }

    fun selectSession(session: ChatSessionItem) {
        openSession(session.id, session.title)
    }

    fun openSession(sessionId: String, title: String? = null) {
        if (_uiState.value.isStreaming) {
            return
        }
        val normalizedSessionId = sessionId.trim().takeIf { it.isNotBlank() } ?: return
        val normalizedTitle = title?.trim()?.takeIf { it.isNotBlank() }
        _uiState.update {
            it.copy(
                sessionId = normalizedSessionId,
                sessionTitle = normalizedTitle,
                messages = emptyList(),
                errorMessage = null,
            )
        }
        loadMessages(normalizedSessionId)
    }

    fun deleteSession(sessionId: String) {
        val state = _uiState.value
        if (state.isStreaming || !state.hasValidScope()) {
            return
        }
        viewModelScope.launch {
            runCatching {
                chatRepository.deleteSession(
                    scope = state.scope,
                    courseId = state.courseId,
                    sessionId = sessionId,
                )
            }.onSuccess {
                _uiState.update { current ->
                    current.copy(
                        sessions = current.sessions.filterNot { it.id == sessionId },
                        sessionId = current.sessionId.takeIf { it != sessionId },
                        sessionTitle = current.sessionTitle.takeIf { current.sessionId != sessionId },
                        messages = if (current.sessionId == sessionId) emptyList() else current.messages,
                    )
                }
            }.onFailure { throwable ->
                _uiState.update {
                    it.copy(errorMessage = throwable.message ?: throwable::class.java.simpleName)
                }
            }
        }
    }

    fun updateDraft(value: String) {
        _uiState.update {
            it.copy(
                draft = value,
                errorMessage = null,
            )
        }
    }

    fun send() {
        val state = _uiState.value
        val question = state.draft.trim()
        if (question.isBlank() || state.isStreaming) {
            return
        }
        if (!state.hasValidScope()) {
            _uiState.update { it.copy(errorMessage = "缺少学科 ID，无法发送学科消息。") }
            return
        }

        val userMessage = ChatMessageUi(
            id = buildLocalId("user"),
            role = ChatMessageRole.User,
            content = question,
            status = ChatMessageStatus.Ready,
        )
        val assistantId = buildLocalId("assistant")
        val assistantMessage = ChatMessageUi(
            id = assistantId,
            role = ChatMessageRole.Assistant,
            content = "",
            status = ChatMessageStatus.Streaming,
            statusDetail = "正在连接",
        )
        val requestSessionId = state.sessionId

        _uiState.update {
            it.copy(
                messages = it.messages + userMessage + assistantMessage,
                draft = "",
                isStreaming = true,
                streamStatus = "正在连接",
                errorMessage = null,
            )
        }

        streamJob = viewModelScope.launch {
            try {
                val result = chatRepository.sendMessage(
                    scope = state.scope,
                    courseId = state.courseId,
                    request = ChatSendRequest(
                        question = question,
                        sessionId = requestSessionId,
                        scene = state.requestScene(),
                        source = state.requestSource(),
                    ),
                    onToken = { token ->
                        _uiState.update { current ->
                            current.copy(
                                streamStatus = null,
                                messages = updateMessage(current.messages, assistantId) { message ->
                                    message.copy(
                                        content = message.content + token,
                                        status = ChatMessageStatus.Streaming,
                                        statusDetail = null,
                                        errorDetail = null,
                                    )
                                },
                            )
                        }
                    },
                    onStatus = { status ->
                        applyStreamStatus(assistantId = assistantId, status = status)
                    },
                    onDone = { done ->
                        applyStreamDone(assistantId = assistantId, done = done)
                    },
                )

                if (!result.sawDone) {
                    markAssistantError(
                        assistantId = assistantId,
                        detail = if (result.receivedToken) {
                            "服务端连接已结束，但没有返回完成事件。"
                        } else {
                            "服务端没有返回流式内容。"
                        },
                    )
                }
            } catch (error: CancellationException) {
                markAssistantInterrupted(assistantId = assistantId)
            } catch (error: Throwable) {
                markAssistantError(
                    assistantId = assistantId,
                    detail = error.message ?: error::class.java.simpleName,
                )
            } finally {
                streamJob = null
                _uiState.update {
                    it.copy(
                        isStreaming = false,
                        streamStatus = null,
                    )
                }
                loadSessions()
            }
        }
    }

    fun stop() {
        streamJob?.cancel()
    }

    fun clearMessages() {
        if (_uiState.value.isStreaming) {
            return
        }
        resetCurrentSession()
    }

    fun consumeClientActions() {
        _uiState.update { it.copy(clientActions = emptyList()) }
    }

    private fun loadMessages(sessionId: String) {
        val state = _uiState.value
        if (!state.hasValidScope()) {
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(isLoadingMessages = true, errorMessage = null) }
            runCatching {
                chatRepository.listMessages(
                    scope = state.scope,
                    courseId = state.courseId,
                    sessionId = sessionId,
                )
            }.onSuccess { items ->
                _uiState.update {
                    it.copy(
                        messages = items.map(::mapMessageItem),
                        isLoadingMessages = false,
                    )
                }
            }.onFailure { throwable ->
                _uiState.update {
                    it.copy(
                        isLoadingMessages = false,
                        errorMessage = throwable.message ?: throwable::class.java.simpleName,
                    )
                }
            }
        }
    }

    private fun resetCurrentSession() {
        _uiState.update {
            it.copy(
                messages = emptyList(),
                sessionId = null,
                sessionTitle = null,
                streamStatus = null,
                errorMessage = null,
            )
        }
    }

    private fun applyStreamStatus(
        assistantId: String,
        status: ChatStatusData,
    ) {
        val detail = status.detail?.trim()
            ?: status.step?.trim()
            ?: status.stage?.trim()
        val nextSessionId = status.sessionId?.trim().takeUnless { it.isNullOrBlank() }
        val nextSessionTitle = status.sessionTitle?.trim().takeUnless { it.isNullOrBlank() }

        _uiState.update { current ->
            current.copy(
                sessionId = nextSessionId ?: current.sessionId,
                sessionTitle = nextSessionTitle ?: current.sessionTitle,
                streamStatus = detail ?: current.streamStatus,
                messages = updateMessage(current.messages, assistantId) { message ->
                    message.copy(statusDetail = detail ?: message.statusDetail)
                },
            )
        }
    }

    private fun applyStreamDone(
        assistantId: String,
        done: ChatDoneData,
    ) {
        val clientActions = done.clientActions.orEmpty()
        _uiState.update { current ->
            current.copy(
                sessionId = done.sessionId ?: current.sessionId,
                sessionTitle = done.sessionTitle ?: current.sessionTitle,
                streamStatus = null,
                clientActions = clientActions,
                clientActionVersion = if (clientActions.isNotEmpty()) {
                    current.clientActionVersion + 1
                } else {
                    current.clientActionVersion
                },
                messages = updateMessage(current.messages, assistantId) { message ->
                    message.copy(
                        status = ChatMessageStatus.Ready,
                        statusDetail = null,
                        errorDetail = null,
                        turnId = done.turnId,
                    )
                },
            )
        }
    }

    private fun markAssistantError(
        assistantId: String,
        detail: String,
    ) {
        val safeDetail = sanitizeErrorDetail(detail)
        _uiState.update { current ->
            current.copy(
                errorMessage = safeDetail,
                messages = updateMessage(current.messages, assistantId) { message ->
                    message.copy(
                        status = ChatMessageStatus.Error,
                        statusDetail = null,
                        errorDetail = safeDetail,
                    )
                },
            )
        }
    }

    private fun markAssistantInterrupted(assistantId: String) {
        _uiState.update { current ->
            current.copy(
                messages = updateMessage(current.messages, assistantId) { message ->
                    message.copy(
                        status = ChatMessageStatus.Interrupted,
                        statusDetail = null,
                        errorDetail = "已停止生成",
                    )
                },
            )
        }
    }

    private fun ChatUiState.hasValidScope(): Boolean {
        return scope == ChatConversationScope.Global ||
            (scope == ChatConversationScope.Course && !courseId.isNullOrBlank())
    }

    private fun ChatUiState.requestScene(): String {
        return sceneOverride ?: if (scope == ChatConversationScope.Course) {
            "course_chat"
        } else {
            "global_assistant"
        }
    }

    private fun ChatUiState.requestSource(): String {
        return sourceOverride ?: if (scope == ChatConversationScope.Course) {
            "android_course_chat"
        } else {
            "android_global_chat"
        }
    }

    private fun updateMessage(
        messages: List<ChatMessageUi>,
        messageId: String,
        updater: (ChatMessageUi) -> ChatMessageUi,
    ): List<ChatMessageUi> {
        return messages.map { message ->
            if (message.id == messageId) updater(message) else message
        }
    }

    private fun mapMessageItem(item: ChatMessageItem): ChatMessageUi {
        return ChatMessageUi(
            id = item.id.toString(),
            role = if (item.role == "user") ChatMessageRole.User else ChatMessageRole.Assistant,
            content = item.content,
            status = ChatMessageStatus.Ready,
            turnId = item.turnId,
        )
    }

    private fun buildLocalId(prefix: String): String {
        return "$prefix-${System.currentTimeMillis()}-${(1000..9999).random()}"
    }

    private fun sanitizeErrorDetail(detail: String): String {
        return SECRET_VALUE_RE.replace(detail) { match ->
            val prefix = match.groupValues[1]
            val value = match.groupValues[2]
            val masked = if (value.length <= 12) {
                "***"
            } else {
                "${value.take(4)}...${value.takeLast(4)}"
            }
            "$prefix$masked"
        }
    }

    private companion object {
        val SECRET_VALUE_RE = Regex(
            pattern = "((?:invalid key|api[_ -]?key|secret|token)\\s*[:=]\\s*)([A-Za-z0-9._-]{12,})",
            option = RegexOption.IGNORE_CASE,
        )
    }
}
