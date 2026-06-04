package com.aiteachme.android.feature.newcourse.presentation

import androidx.compose.foundation.background
import androidx.compose.foundation.border
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
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material.icons.automirrored.outlined.Send
import androidx.compose.material.icons.outlined.FolderOpen
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import com.aiteachme.android.core.di.AppServices
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class NewCourseUiState(
    val prompt: String = "",
    val isCreating: Boolean = false,
    val errorMessage: String? = null,
)

class NewCourseViewModel : ViewModel() {
    private val coursesRepository = AppServices.courseRepository
    private val courseContext = AppServices.courseContextStore

    private val _uiState = MutableStateFlow(NewCourseUiState())
    val uiState: StateFlow<NewCourseUiState> = _uiState.asStateFlow()

    fun updatePrompt(value: String) {
        _uiState.update { it.copy(prompt = value, errorMessage = null) }
    }

    fun createCourse(onCreated: (courseId: String, prompt: String) -> Unit) {
        val current = _uiState.value
        val prompt = _uiState.value.prompt.trim()
        if (prompt.isBlank()) {
            _uiState.update { it.copy(errorMessage = "先输入你想创建的课程或学习目标。") }
            return
        }
        if (current.isCreating) {
            return
        }

        viewModelScope.launch {
            _uiState.update { it.copy(isCreating = true, errorMessage = null) }
            runCatching {
                coursesRepository.createDraftCourse()
            }.onSuccess { course ->
                courseContext.upsertCourse(course)
                _uiState.update { it.copy(isCreating = false, prompt = "") }
                onCreated(course.courseId, prompt)
            }.onFailure { throwable ->
                _uiState.update {
                    it.copy(
                        isCreating = false,
                        errorMessage = throwable.message ?: throwable::class.java.simpleName,
                    )
                }
            }
        }
    }
}

@Composable
fun NewCourseScreen(
    contentPadding: PaddingValues,
    onBack: (() -> Unit)? = null,
    onCourseCreated: (courseId: String, prompt: String) -> Unit,
    viewModel: NewCourseViewModel = viewModel(),
) {
    val uiState by viewModel.uiState.collectAsState()

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(Color.White),
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(contentPadding)
                .padding(horizontal = 24.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center,
        ) {
            Text(
                text = "想创建什么课程？",
                style = MaterialTheme.typography.headlineMedium,
                fontWeight = FontWeight.Black,
                color = Color.Black,
                textAlign = TextAlign.Center,
            )
            Spacer(modifier = Modifier.height(28.dp))
            NewCoursePromptCard(
                uiState = uiState,
                onPromptChange = viewModel::updatePrompt,
                onCreate = { viewModel.createCourse(onCourseCreated) },
            )
        }

        onBack?.let { handleBack ->
            IconButton(
                onClick = handleBack,
                modifier = Modifier
                    .align(Alignment.TopStart)
                    .padding(contentPadding)
                    .padding(start = 8.dp, top = 8.dp),
            ) {
                Icon(
                    imageVector = Icons.AutoMirrored.Outlined.ArrowBack,
                    contentDescription = "返回",
                    tint = Color.Black,
                )
            }
        }
    }
}

@Composable
private fun NewCoursePromptCard(
    uiState: NewCourseUiState,
    onPromptChange: (String) -> Unit,
    onCreate: () -> Unit,
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
                value = uiState.prompt,
                onValueChange = onPromptChange,
                modifier = Modifier
                    .fillMaxWidth()
                    .height(132.dp),
                enabled = !uiState.isCreating,
                textStyle = TextStyle(
                    color = Color(0xFF111827),
                    fontSize = MaterialTheme.typography.bodyLarge.fontSize,
                    lineHeight = MaterialTheme.typography.bodyLarge.lineHeight,
                ),
                cursorBrush = SolidColor(MaterialTheme.colorScheme.primary),
                decorationBox = { innerTextField ->
                    Box(modifier = Modifier.fillMaxSize()) {
                        if (uiState.prompt.isBlank()) {
                            Text(
                                text = "直接输入你想学习什么，也可以描述目标、基础、考试时间或希望生成的材料",
                                style = MaterialTheme.typography.bodyMedium,
                                color = Color(0xFF8A8F9C),
                            )
                        }
                        innerTextField()
                    }
                },
            )

            uiState.errorMessage?.let { error ->
                Text(
                    text = error,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.error,
                )
            }

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    Icon(
                        imageVector = Icons.Outlined.FolderOpen,
                        contentDescription = null,
                        tint = Color(0xFF4B5563),
                        modifier = Modifier.size(18.dp),
                    )
                    Text(
                        text = "资料库",
                        style = MaterialTheme.typography.bodySmall,
                        color = Color(0xFF374151),
                        fontWeight = FontWeight.SemiBold,
                    )
                }

                IconButton(
                    onClick = onCreate,
                    enabled = !uiState.isCreating && uiState.prompt.isNotBlank(),
                    modifier = Modifier
                        .size(46.dp)
                        .clip(CircleShape)
                        .background(
                            if (uiState.prompt.isBlank()) {
                                Color(0xFFF1F2F5)
                            } else {
                                MaterialTheme.colorScheme.primary
                            },
                        ),
                ) {
                    if (uiState.isCreating) {
                        CircularProgressIndicator(
                            modifier = Modifier.size(18.dp),
                            strokeWidth = 2.dp,
                        )
                    } else {
                        Icon(
                            imageVector = Icons.AutoMirrored.Outlined.Send,
                            contentDescription = "开始构建课程",
                            tint = if (uiState.prompt.isBlank()) {
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
