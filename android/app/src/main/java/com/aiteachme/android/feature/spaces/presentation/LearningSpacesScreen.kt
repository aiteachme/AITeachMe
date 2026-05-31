package com.aiteachme.android.feature.spaces.presentation

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.combinedClickable
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
import androidx.compose.material.icons.automirrored.outlined.ArrowForward
import androidx.compose.material.icons.outlined.Add
import androidx.compose.material.icons.outlined.DeleteOutline
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material.icons.outlined.School
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.aiteachme.android.core.network.dto.CourseDeletePreviewData
import com.aiteachme.android.core.network.dto.CourseItem

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun LearningSpacesScreen(
    contentPadding: PaddingValues,
    onOpenCourse: (String) -> Unit,
    onOpenNewCourse: () -> Unit,
    viewModel: LearningSpacesViewModel = viewModel(),
) {
    val uiState by viewModel.uiState.collectAsState()
    var actionCourse by remember { mutableStateOf<CourseItem?>(null) }

    LaunchedEffect(Unit) {
        viewModel.loadCourses()
    }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(
                Brush.verticalGradient(
                    colors = listOf(
                        MaterialTheme.colorScheme.surface,
                        MaterialTheme.colorScheme.surfaceContainerLow,
                    ),
                ),
            ),
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(contentPadding)
                .padding(horizontal = 20.dp, vertical = 18.dp),
            verticalArrangement = Arrangement.spacedBy(18.dp),
        ) {
            LearningSpacesHeader(
                isLoading = uiState.isLoading,
                onRefresh = viewModel::loadCourses,
                onOpenNewCourse = onOpenNewCourse,
            )

            uiState.errorMessage?.let { error ->
                Surface(
                    modifier = Modifier.fillMaxWidth(),
                    color = MaterialTheme.colorScheme.errorContainer,
                    contentColor = MaterialTheme.colorScheme.onErrorContainer,
                    shape = RoundedCornerShape(14.dp),
                ) {
                    Text(
                        text = error,
                        modifier = Modifier.padding(horizontal = 14.dp, vertical = 10.dp),
                        style = MaterialTheme.typography.bodyMedium,
                    )
                }
            }

            if (uiState.courses.isEmpty() && uiState.isLoading) {
                LoadingState(modifier = Modifier.fillMaxSize())
            } else if (uiState.courses.isEmpty()) {
                EmptySpacesState(
                    onOpenNewCourse = onOpenNewCourse,
                    modifier = Modifier.fillMaxSize(),
                )
            } else {
                LazyColumn(
                    modifier = Modifier.fillMaxSize(),
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                    contentPadding = PaddingValues(bottom = 18.dp),
                ) {
                    items(uiState.courses, key = { it.courseId }) { course ->
                        LearningSpaceItem(
                            course = course,
                            selected = course.courseId == uiState.selectedCourseId,
                            isDeleting = uiState.deletingCourseIds.contains(course.courseId),
                            onClick = {
                                viewModel.openCourse(course.courseId, onOpenCourse)
                            },
                            onLongPress = {
                                actionCourse = course
                            },
                        )
                    }
                }
            }
        }
    }

    actionCourse?.let { course ->
        CourseActionSheet(
            course = course,
            isDeleting = uiState.deletingCourseIds.contains(course.courseId),
            isPreparingDelete = uiState.isLoadingDeletePreview,
            onDismiss = { actionCourse = null },
            onOpen = {
                actionCourse = null
                viewModel.openCourse(course.courseId, onOpenCourse)
            },
            onDelete = {
                actionCourse = null
                viewModel.previewDeleteCourse(course.courseId)
            },
        )
    }

    uiState.deletePreview?.let { preview ->
        DeleteCourseDialog(
            preview = preview,
            isDeleting = uiState.deletingCourseIds.contains(preview.courseId),
            onDismiss = viewModel::dismissDeletePreview,
            onConfirm = viewModel::confirmDeleteCourse,
        )
    }
}

@Composable
private fun LearningSpacesHeader(
    isLoading: Boolean,
    onRefresh: () -> Unit,
    onOpenNewCourse: () -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.Top,
    ) {
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = "学习空间",
                style = MaterialTheme.typography.headlineLarge,
                fontWeight = FontWeight.Black,
            )
            Spacer(modifier = Modifier.height(6.dp))
            Text(
                text = "选择一个学科，进入它自己的学习、资料和对话空间。",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            IconButton(
                onClick = onRefresh,
                enabled = !isLoading,
            ) {
                if (isLoading) {
                    CircularProgressIndicator(
                        modifier = Modifier.size(20.dp),
                        strokeWidth = 2.dp,
                    )
                } else {
                    Icon(imageVector = Icons.Outlined.Refresh, contentDescription = "刷新学习空间")
                }
            }
            IconButton(onClick = onOpenNewCourse) {
                Icon(imageVector = Icons.Outlined.Add, contentDescription = "新建学科")
            }
        }
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun LearningSpaceItem(
    course: CourseItem,
    selected: Boolean,
    isDeleting: Boolean,
    onClick: () -> Unit,
    onLongPress: () -> Unit,
) {
    val itemShape = RoundedCornerShape(18.dp)
    val itemColor = if (selected) {
        MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.58f)
    } else {
        MaterialTheme.colorScheme.surface
    }

    Box(
        modifier = Modifier
            .fillMaxWidth()
            .clip(itemShape)
            .background(itemColor)
            .combinedClickable(
                onClick = onClick,
                onLongClick = onLongPress,
            ),
    ) {
        Row(
            modifier = Modifier.padding(16.dp),
            horizontalArrangement = Arrangement.spacedBy(14.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Box(
                modifier = Modifier
                    .size(48.dp)
                    .clip(CircleShape)
                    .background(
                        if (selected) {
                            MaterialTheme.colorScheme.primary.copy(alpha = 0.16f)
                        } else {
                            MaterialTheme.colorScheme.surfaceContainerHighest
                        },
                    ),
                contentAlignment = Alignment.Center,
            ) {
                Icon(
                    imageVector = Icons.Outlined.School,
                    contentDescription = null,
                    tint = if (selected) {
                        MaterialTheme.colorScheme.primary
                    } else {
                        MaterialTheme.colorScheme.onSurfaceVariant
                    },
                )
            }

            Column(modifier = Modifier.weight(1f)) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(
                        text = course.name.ifBlank { "未命名学习空间" },
                        modifier = Modifier.weight(1f),
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.Bold,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                    if (selected) {
                        Text(
                            text = "当前",
                            style = MaterialTheme.typography.labelMedium,
                            color = MaterialTheme.colorScheme.primary,
                            fontWeight = FontWeight.Bold,
                        )
                    }
                }
                Spacer(modifier = Modifier.height(5.dp))
                Text(
                    text = course.description.ifBlank { course.userIntent }.ifBlank { "进入后管理文档、闯关测试和学科助手。" },
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )
            }

            if (isDeleting) {
                CircularProgressIndicator(
                    modifier = Modifier.size(22.dp),
                    strokeWidth = 2.dp,
                )
            } else {
                Icon(
                    imageVector = Icons.AutoMirrored.Outlined.ArrowForward,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun CourseActionSheet(
    course: CourseItem,
    isDeleting: Boolean,
    isPreparingDelete: Boolean,
    onDismiss: () -> Unit,
    onOpen: () -> Unit,
    onDelete: () -> Unit,
) {
    ModalBottomSheet(onDismissRequest = onDismiss) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(start = 20.dp, end = 20.dp, bottom = 28.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text(
                text = course.name.ifBlank { "未命名学习空间" },
                style = MaterialTheme.typography.titleLarge,
                fontWeight = FontWeight.Black,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Text(
                text = "选择要执行的操作",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            CourseActionRow(
                title = "进入学习空间",
                subtitle = "打开这个学科的学习主页",
                icon = Icons.AutoMirrored.Outlined.ArrowForward,
                onClick = onOpen,
            )
            CourseActionRow(
                title = if (isPreparingDelete) "正在准备删除" else "删除学习空间",
                subtitle = "先查看影响范围，再确认删除",
                icon = Icons.Outlined.DeleteOutline,
                danger = true,
                enabled = !isDeleting && !isPreparingDelete,
                trailingLoading = isDeleting || isPreparingDelete,
                onClick = onDelete,
            )
        }
    }
}

@Composable
private fun CourseActionRow(
    title: String,
    subtitle: String,
    icon: ImageVector,
    danger: Boolean = false,
    enabled: Boolean = true,
    trailingLoading: Boolean = false,
    onClick: () -> Unit,
) {
    val contentColor = when {
        !enabled -> MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.56f)
        danger -> MaterialTheme.colorScheme.error
        else -> MaterialTheme.colorScheme.onSurface
    }

    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(16.dp))
            .background(MaterialTheme.colorScheme.surfaceContainerLow)
            .clickable(enabled = enabled, onClick = onClick)
            .padding(horizontal = 16.dp, vertical = 14.dp),
        horizontalArrangement = Arrangement.spacedBy(14.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(
            imageVector = icon,
            contentDescription = null,
            tint = contentColor,
        )
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = title,
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Bold,
                color = contentColor,
            )
            Spacer(modifier = Modifier.height(3.dp))
            Text(
                text = subtitle,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        if (trailingLoading) {
            CircularProgressIndicator(
                modifier = Modifier.size(20.dp),
                strokeWidth = 2.dp,
            )
        }
    }
}

@Composable
private fun DeleteCourseDialog(
    preview: CourseDeletePreviewData,
    isDeleting: Boolean,
    onDismiss: () -> Unit,
    onConfirm: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = {
            if (!isDeleting) {
                onDismiss()
            }
        },
        title = {
            Text("删除学习空间")
        },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text(
                    text = "确定删除「${preview.courseName.ifBlank { "未命名学习空间" }}」吗？这个操作无法撤销。",
                    style = MaterialTheme.typography.bodyMedium,
                )
                if (preview.hasContent) {
                    Text(
                        text = "将同时删除 ${preview.totalRelatedRecords} 条关联内容：",
                        style = MaterialTheme.typography.bodyMedium,
                        fontWeight = FontWeight.SemiBold,
                    )
                    preview.impactItems
                        .filter { it.count > 0 }
                        .take(5)
                        .forEach { item ->
                            Text(
                                text = "${item.label}: ${item.count}",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                } else {
                    Text(
                        text = "这个学习空间还没有关联内容，可以直接删除。",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        },
        confirmButton = {
            Button(
                onClick = onConfirm,
                enabled = !isDeleting,
            ) {
                if (isDeleting) {
                    CircularProgressIndicator(
                        modifier = Modifier.size(16.dp),
                        strokeWidth = 2.dp,
                    )
                    Spacer(modifier = Modifier.width(8.dp))
                }
                Text("确认删除")
            }
        },
        dismissButton = {
            TextButton(
                onClick = onDismiss,
                enabled = !isDeleting,
            ) {
                Text("取消")
            }
        },
    )
}

@Composable
private fun LoadingState(modifier: Modifier = Modifier) {
    Box(modifier = modifier, contentAlignment = Alignment.Center) {
        CircularProgressIndicator()
    }
}

@Composable
private fun EmptySpacesState(
    onOpenNewCourse: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier.padding(horizontal = 18.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Text(
            text = "还没有学习空间",
            style = MaterialTheme.typography.titleLarge,
            fontWeight = FontWeight.Black,
        )
        Spacer(modifier = Modifier.height(8.dp))
        Text(
            text = "先通过新建学科对话生成一个学习空间，再进入内部学习。",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(modifier = Modifier.height(20.dp))
        Button(onClick = onOpenNewCourse) {
            Icon(imageVector = Icons.Outlined.Add, contentDescription = null)
            Spacer(modifier = Modifier.width(8.dp))
            Text("新建学科")
        }
    }
}
