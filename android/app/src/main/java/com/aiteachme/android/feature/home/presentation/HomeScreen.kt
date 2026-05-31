package com.aiteachme.android.feature.home.presentation

import androidx.activity.compose.BackHandler
import android.graphics.BitmapFactory
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInHorizontally
import androidx.compose.animation.slideOutHorizontally
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectHorizontalDragGestures
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Add
import androidx.compose.material.icons.outlined.AutoStories
import androidx.compose.material.icons.outlined.Close
import androidx.compose.material.icons.outlined.FolderOpen
import androidx.compose.material.icons.outlined.Insights
import androidx.compose.material.icons.outlined.Psychology
import androidx.compose.material.icons.outlined.Quiz
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material.icons.outlined.SwapHoriz
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
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
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.blur
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.viewmodel.compose.viewModel
import com.aiteachme.android.R
import com.aiteachme.android.core.data.repository.ChatConversationScope
import com.aiteachme.android.core.network.dto.CourseItem
import com.aiteachme.android.feature.chat.presentation.ChatScreen
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun HomeScreen(
    contentPadding: PaddingValues,
    onOpenBuild: (String) -> Unit,
    onOpenDocs: (String) -> Unit,
    onOpenPractice: (String) -> Unit,
    onOpenProfile: (String) -> Unit,
    onOpenCourseChat: (String) -> Unit,
    onOpenFiles: () -> Unit,
    viewModel: HomeViewModel = viewModel(),
) {
    val uiState by viewModel.uiState.collectAsState()
    var showCoursePicker by remember { mutableStateOf(false) }
    var showChatPanel by remember { mutableStateOf(false) }
    var showMorePanel by remember { mutableStateOf(false) }
    val lifecycleOwner = LocalLifecycleOwner.current

    LaunchedEffect(Unit) {
        viewModel.refresh()
    }

    DisposableEffect(lifecycleOwner) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_RESUME) {
                viewModel.loadRandomWallpaper()
            }
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose {
            lifecycleOwner.lifecycle.removeObserver(observer)
        }
    }

    val selectedCourse = uiState.selectedCourse
    val panelVisible = showChatPanel || showMorePanel

    BackHandler(enabled = panelVisible) {
        showChatPanel = false
        showMorePanel = false
    }

    fun openNewCourseBuild() {
        viewModel.createDraftCourse { courseId ->
            onOpenBuild(courseId)
        }
    }

    Box(
        modifier = Modifier
            .fillMaxSize(),
    ) {
        SubjectHomeSurface(
            uiState = uiState,
            backgroundImagePath = uiState.backgroundImagePath,
            modifier = Modifier
                .fillMaxSize()
                .then(if (panelVisible) Modifier.blur(18.dp) else Modifier),
            onPickCourse = { showCoursePicker = true },
            onCreateCourse = ::openNewCourseBuild,
            onOpenDocs = {
                selectedCourse?.courseId?.let(onOpenDocs) ?: run { showCoursePicker = true }
            },
            onOpenPractice = {
                selectedCourse?.courseId?.let(onOpenPractice) ?: run { showCoursePicker = true }
            },
            onOpenChatPanel = {
                if (selectedCourse != null) {
                    showMorePanel = false
                    showChatPanel = true
                } else {
                    showCoursePicker = true
                }
            },
            onOpenMorePanel = {
                if (selectedCourse != null) {
                    showChatPanel = false
                    showMorePanel = true
                } else {
                    showCoursePicker = true
                }
            },
        )

        if (panelVisible) {
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .background(Color.Black.copy(alpha = 0.18f))
                    .clickable {
                        showChatPanel = false
                        showMorePanel = false
                    },
            )
        }

        if (selectedCourse != null) {
            CourseChatPanel(
                visible = showChatPanel,
                course = selectedCourse,
                onClose = { showChatPanel = false },
            )
            MoreFunctionsPanel(
                visible = showMorePanel,
                course = selectedCourse,
                onClose = { showMorePanel = false },
                onOpenBuild = {
                    showMorePanel = false
                    onOpenBuild(selectedCourse.courseId)
                },
                onOpenPractice = {
                    showMorePanel = false
                    onOpenPractice(selectedCourse.courseId)
                },
                onOpenProfile = {
                    showMorePanel = false
                    onOpenProfile(selectedCourse.courseId)
                },
                onOpenFiles = {
                    showMorePanel = false
                    onOpenFiles()
                },
                onOpenCourseChat = {
                    showMorePanel = false
                    onOpenCourseChat(selectedCourse.courseId)
                },
            )
        }
    }

    if (showCoursePicker) {
        ModalBottomSheet(onDismissRequest = { showCoursePicker = false }) {
            CoursePickerSheet(
                courses = uiState.courses,
                selectedCourseId = uiState.selectedCourseId,
                isLoading = uiState.isLoadingCourses,
                isCreatingCourse = uiState.isCreatingCourse,
                onRefresh = viewModel::loadCourses,
                onCreateCourse = {
                    showCoursePicker = false
                    openNewCourseBuild()
                },
                onSelectCourse = { courseId ->
                    viewModel.selectCourse(courseId)
                    showCoursePicker = false
                },
            )
        }
    }

}

@Composable
private fun SubjectHomeSurface(
    uiState: HomeUiState,
    backgroundImagePath: String?,
    modifier: Modifier,
    onPickCourse: () -> Unit,
    onCreateCourse: () -> Unit,
    onOpenDocs: () -> Unit,
    onOpenPractice: () -> Unit,
    onOpenChatPanel: () -> Unit,
    onOpenMorePanel: () -> Unit,
) {
    var horizontalDrag by remember { mutableFloatStateOf(0f) }
    val course = uiState.selectedCourse

    Box(
        modifier = modifier.pointerInput(course?.courseId) {
            detectHorizontalDragGestures(
                onDragStart = { horizontalDrag = 0f },
                onHorizontalDrag = { _, dragAmount ->
                    horizontalDrag += dragAmount
                },
                onDragEnd = {
                    when {
                        horizontalDrag < -90f -> onOpenChatPanel()
                        horizontalDrag > 90f -> onOpenMorePanel()
                    }
                    horizontalDrag = 0f
                },
                onDragCancel = { horizontalDrag = 0f },
            )
        },
    ) {
        DailyWallpaperBackground(backgroundImagePath = backgroundImagePath)
        Box(
            modifier = Modifier
                .fillMaxSize()
                .background(
                    Brush.verticalGradient(
                        colors = listOf(
                            Color.White.copy(alpha = 0.08f),
                            Color.Transparent,
                            Color.Black.copy(alpha = 0.18f),
                        ),
                    ),
                ),
        )

        CourseChip(
            course = course,
            courseCount = uiState.courses.size,
            isLoading = uiState.isLoadingCourses,
            onClick = onPickCourse,
            modifier = Modifier
                .align(Alignment.TopStart)
                .statusBarsPadding()
                .padding(start = 24.dp, top = 16.dp),
        )

        IconButton(
            onClick = onCreateCourse,
            modifier = Modifier
                .align(Alignment.TopEnd)
                .statusBarsPadding()
                .padding(top = 18.dp, end = 22.dp)
                .clip(CircleShape)
                .background(Color.White.copy(alpha = 0.42f)),
        ) {
            Icon(
                imageVector = Icons.Outlined.Add,
                contentDescription = "新建学科",
                tint = Color.Black,
            )
        }

        Text(
            text = course?.name?.ifBlank { "未命名学科" } ?: "选择学科",
            modifier = Modifier
                .align(Alignment.Center)
                .padding(horizontal = 24.dp),
            style = MaterialTheme.typography.displayMedium,
            fontWeight = FontWeight.Black,
            color = Color.Black,
            maxLines = 2,
            overflow = TextOverflow.Ellipsis,
            textAlign = TextAlign.Center,
        )

        StatusBanner(
            uiState = uiState,
            modifier = Modifier
                .align(Alignment.TopStart)
                .statusBarsPadding()
                .padding(start = 24.dp, top = 84.dp, end = 24.dp),
        )

        Row(
            modifier = Modifier
                .align(Alignment.BottomCenter)
                .navigationBarsPadding()
                .padding(horizontal = 22.dp)
                .padding(bottom = 96.dp)
                .fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            PrimarySubjectAction(
                title = "文档查看",
                value = "Learn",
                backgroundImagePath = backgroundImagePath,
                modifier = Modifier.weight(1f),
                onClick = onOpenDocs,
            )
            PrimarySubjectAction(
                title = "闯关测试",
                value = "Review",
                backgroundImagePath = backgroundImagePath,
                modifier = Modifier.weight(1f),
                onClick = onOpenPractice,
            )
        }
    }
}

@Composable
private fun DailyWallpaperBackground(
    backgroundImagePath: String?,
    modifier: Modifier = Modifier.fillMaxSize(),
) {
    var remoteBitmap by remember(backgroundImagePath) { mutableStateOf<ImageBitmap?>(null) }

    LaunchedEffect(backgroundImagePath) {
        remoteBitmap = null
        val path = backgroundImagePath ?: return@LaunchedEffect
        remoteBitmap = withContext(Dispatchers.IO) {
            BitmapFactory.decodeFile(path)?.asImageBitmap()
        }
    }

    val bitmap = remoteBitmap
    if (bitmap != null) {
        Image(
            bitmap = bitmap,
            contentDescription = null,
            modifier = modifier,
            contentScale = ContentScale.Crop,
        )
    } else {
        Image(
            painter = painterResource(id = R.drawable.learn_mountain_bg),
            contentDescription = null,
            modifier = modifier,
            contentScale = ContentScale.Crop,
        )
    }
}

@Composable
private fun CourseChip(
    course: CourseItem?,
    courseCount: Int,
    isLoading: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Surface(
        modifier = modifier.clickable(onClick = onClick),
        color = Color.White.copy(alpha = 0.46f),
        contentColor = Color.Black,
        shape = RoundedCornerShape(28.dp),
        shadowElevation = 2.dp,
    ) {
        Row(
            modifier = Modifier.padding(start = 8.dp, top = 7.dp, end = 12.dp, bottom = 7.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(9.dp),
        ) {
            Box(
                modifier = Modifier
                    .size(46.dp)
                    .clip(CircleShape)
                    .background(
                        Brush.linearGradient(
                            listOf(
                                Color(0xFFEFFAFF),
                                Color(0xFFFFE7F0),
                            ),
                        ),
                    ),
                contentAlignment = Alignment.Center,
            ) {
                if (isLoading) {
                    CircularProgressIndicator(
                        modifier = Modifier.size(20.dp),
                        strokeWidth = 2.dp,
                        color = Color.Black,
                    )
                } else {
                    Text(
                        text = course?.name?.trim()?.take(1)?.ifBlank { "学" } ?: "学",
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.Black,
                        color = Color.Black,
                    )
                }
            }
            Column(modifier = Modifier.widthIn(max = 170.dp)) {
                Text(
                    text = course?.name?.ifBlank { "未命名学科" } ?: "选择学科",
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.Bold,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                Text(
                    text = if (courseCount == 0) "点击创建或切换" else "$courseCount 个学科 · 点击切换",
                    style = MaterialTheme.typography.bodySmall,
                    color = Color.Black.copy(alpha = 0.68f),
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            Icon(
                imageVector = Icons.Outlined.SwapHoriz,
                contentDescription = null,
                modifier = Modifier.size(18.dp),
            )
        }
    }
}

@Composable
private fun PrimarySubjectAction(
    title: String,
    value: String,
    backgroundImagePath: String?,
    modifier: Modifier = Modifier,
    onClick: () -> Unit,
) {
    val shape = RoundedCornerShape(16.dp)

    Box(
        modifier = modifier
            .height(92.dp)
            .clip(shape)
            .border(1.dp, Color.White.copy(alpha = 0.48f), shape)
            .clickable(
                interactionSource = remember { MutableInteractionSource() },
                indication = null,
                onClick = onClick,
            ),
        contentAlignment = Alignment.CenterStart,
    ) {
        DailyWallpaperBackground(
            backgroundImagePath = backgroundImagePath,
            modifier = Modifier
                .matchParentSize()
                .blur(10.dp),
        )
        Box(
            modifier = Modifier
                .matchParentSize()
                .background(
                    Brush.linearGradient(
                        colors = listOf(
                            Color.White.copy(alpha = 0.40f),
                            Color.White.copy(alpha = 0.18f),
                            Color.White.copy(alpha = 0.30f),
                        ),
                    ),
                ),
        )
        Column(
            modifier = Modifier.padding(horizontal = 18.dp, vertical = 14.dp),
            verticalArrangement = Arrangement.Center,
        ) {
            Text(
                text = title,
                style = MaterialTheme.typography.titleLarge,
                fontWeight = FontWeight.Black,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Text(
                text = value,
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold,
                color = Color(0xFFE67E22),
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
    }
}

@Composable
private fun CourseChatPanel(
    visible: Boolean,
    course: CourseItem,
    onClose: () -> Unit,
) {
    AnimatedVisibility(
        visible = visible,
        enter = slideInHorizontally(initialOffsetX = { it }) + fadeIn(),
        exit = slideOutHorizontally(targetOffsetX = { it }) + fadeOut(),
        modifier = Modifier.fillMaxSize(),
    ) {
        Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.CenterEnd) {
            Surface(
                modifier = Modifier
                    .fillMaxHeight()
                    .fillMaxWidth(0.88f)
                    .statusBarsPadding()
                    .navigationBarsPadding()
                    .padding(top = 12.dp, bottom = 92.dp, end = 10.dp),
                color = MaterialTheme.colorScheme.surface.copy(alpha = 0.96f),
                shape = RoundedCornerShape(topStart = 30.dp, bottomStart = 30.dp),
                shadowElevation = 18.dp,
            ) {
                ChatScreen(
                    contentPadding = PaddingValues(0.dp),
                    scope = ChatConversationScope.Course,
                    courseId = course.courseId,
                    onBack = onClose,
                )
            }
        }
    }
}

@Composable
private fun MoreFunctionsPanel(
    visible: Boolean,
    course: CourseItem,
    onClose: () -> Unit,
    onOpenBuild: () -> Unit,
    onOpenPractice: () -> Unit,
    onOpenProfile: () -> Unit,
    onOpenFiles: () -> Unit,
    onOpenCourseChat: () -> Unit,
) {
    AnimatedVisibility(
        visible = visible,
        enter = slideInHorizontally(initialOffsetX = { -it }) + fadeIn(),
        exit = slideOutHorizontally(targetOffsetX = { -it }) + fadeOut(),
        modifier = Modifier.fillMaxSize(),
    ) {
        Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.CenterStart) {
            Surface(
                modifier = Modifier
                    .fillMaxHeight()
                    .fillMaxWidth(0.82f)
                    .statusBarsPadding()
                    .navigationBarsPadding()
                    .padding(top = 12.dp, bottom = 92.dp, start = 10.dp),
                color = MaterialTheme.colorScheme.surface.copy(alpha = 0.96f),
                shape = RoundedCornerShape(topEnd = 30.dp, bottomEnd = 30.dp),
                shadowElevation = 18.dp,
            ) {
                Column(
                    modifier = Modifier.padding(horizontal = 20.dp, vertical = 22.dp),
                    verticalArrangement = Arrangement.spacedBy(14.dp),
                ) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.Top,
                    ) {
                        Column(modifier = Modifier.weight(1f)) {
                            Text(
                                text = course.name.ifBlank { "未命名学科" },
                                style = MaterialTheme.typography.headlineSmall,
                                fontWeight = FontWeight.Black,
                                maxLines = 2,
                                overflow = TextOverflow.Ellipsis,
                            )
                            Text(
                                text = "更多功能",
                                style = MaterialTheme.typography.bodyMedium,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                        IconButton(onClick = onClose) {
                            Icon(imageVector = Icons.Outlined.Close, contentDescription = "关闭")
                        }
                    }

                    MoreFunctionItem(
                        title = "资料构建",
                        subtitle = "上传、整理资料并生成知识文档",
                        icon = Icons.Outlined.Psychology,
                        onClick = onOpenBuild,
                    )
                    MoreFunctionItem(
                        title = "考试",
                        subtitle = "生成试卷、查看训练记录",
                        icon = Icons.Outlined.Quiz,
                        onClick = onOpenPractice,
                    )
                    MoreFunctionItem(
                        title = "学习画像",
                        subtitle = "掌握度、薄弱点和复习任务",
                        icon = Icons.Outlined.Insights,
                        onClick = onOpenProfile,
                    )
                    MoreFunctionItem(
                        title = "资料库",
                        subtitle = "管理全局资料并供学科使用",
                        icon = Icons.Outlined.FolderOpen,
                        onClick = onOpenFiles,
                    )
                    MoreFunctionItem(
                        title = "学科对话",
                        subtitle = "打开完整学科对话页",
                        icon = Icons.Outlined.AutoStories,
                        onClick = onOpenCourseChat,
                    )
                }
            }
        }
    }
}

@Composable
private fun MoreFunctionItem(
    title: String,
    subtitle: String,
    icon: ImageVector,
    onClick: () -> Unit,
) {
    Surface(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick),
        color = MaterialTheme.colorScheme.surfaceContainer,
        shape = RoundedCornerShape(18.dp),
    ) {
        Row(
            modifier = Modifier.padding(16.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            Icon(
                imageVector = icon,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.primary,
                modifier = Modifier.size(28.dp),
            )
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = title,
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Bold,
                )
                Text(
                    text = subtitle,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
    }
}

@Composable
private fun StatusBanner(
    uiState: HomeUiState,
    modifier: Modifier = Modifier,
) {
    val text = uiState.errorMessage ?: uiState.infoMessage
    if (text == null && !uiState.isCheckingHealth && !uiState.isLoadingCourses) {
        return
    }
    Surface(
        modifier = modifier.widthIn(max = 320.dp),
        color = Color.White.copy(alpha = 0.46f),
        contentColor = Color.Black,
        shape = RoundedCornerShape(16.dp),
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 12.dp, vertical = 9.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            if (uiState.isCheckingHealth || uiState.isLoadingCourses) {
                CircularProgressIndicator(
                    modifier = Modifier.size(14.dp),
                    strokeWidth = 2.dp,
                    color = Color.Black,
                )
            }
            Text(
                text = text ?: "正在同步学科...",
                style = MaterialTheme.typography.bodySmall,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
            )
        }
    }
}

@Composable
private fun CoursePickerSheet(
    courses: List<CourseItem>,
    selectedCourseId: String?,
    isLoading: Boolean,
    isCreatingCourse: Boolean,
    onRefresh: () -> Unit,
    onCreateCourse: () -> Unit,
    onSelectCourse: (String) -> Unit,
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
            Text(text = "切换学科", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(onClick = onRefresh, enabled = !isLoading) {
                    Icon(imageVector = Icons.Outlined.Refresh, contentDescription = null, modifier = Modifier.size(18.dp))
                    Spacer(modifier = Modifier.width(6.dp))
                    Text("刷新")
                }
                Button(onClick = onCreateCourse, enabled = !isCreatingCourse) {
                    if (isCreatingCourse) {
                        CircularProgressIndicator(modifier = Modifier.size(16.dp), strokeWidth = 2.dp)
                    } else {
                        Icon(imageVector = Icons.Outlined.Add, contentDescription = null, modifier = Modifier.size(18.dp))
                    }
                    Spacer(modifier = Modifier.width(6.dp))
                    Text("新建")
                }
            }
        }
        if (courses.isEmpty()) {
            Text(
                text = if (isLoading) "正在加载学科..." else "暂无学科，先新建一个。",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        } else {
            LazyColumn(
                modifier = Modifier.fillMaxWidth(),
                verticalArrangement = Arrangement.spacedBy(4.dp),
            ) {
                items(courses, key = { it.courseId }) { course ->
                    ListItem(
                        headlineContent = {
                            Text(course.name.ifBlank { "未命名学科" }, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        },
                        supportingContent = {
                            val summary = course.description.ifBlank { course.userIntent }.ifBlank { course.courseId }
                            Text(summary, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        },
                        trailingContent = {
                            if (course.courseId == selectedCourseId) {
                                Text("当前", color = MaterialTheme.colorScheme.primary)
                            }
                        },
                        modifier = Modifier.clickable { onSelectCourse(course.courseId) },
                    )
                }
            }
        }
    }
}

@Composable
private fun CreateCourseDialog(
    uiState: HomeUiState,
    onNameChange: (String) -> Unit,
    onGoalChange: (String) -> Unit,
    onDismiss: () -> Unit,
    onConfirm: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("新建学科") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                OutlinedTextField(
                    value = "",
                    onValueChange = onNameChange,
                    label = { Text("学科名称") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                OutlinedTextField(
                    value = "",
                    onValueChange = onGoalChange,
                    label = { Text("学习目标，可选") },
                    minLines = 2,
                    maxLines = 4,
                    modifier = Modifier.fillMaxWidth(),
                )
            }
        },
        confirmButton = {
            Button(
                onClick = onConfirm,
                enabled = !uiState.isCreatingCourse,
            ) {
                if (uiState.isCreatingCourse) {
                    CircularProgressIndicator(modifier = Modifier.size(16.dp), strokeWidth = 2.dp)
                    Spacer(modifier = Modifier.width(8.dp))
                }
                Text("创建")
            }
        },
        dismissButton = {
            OutlinedButton(onClick = onDismiss, enabled = !uiState.isCreatingCourse) {
                Text("取消")
            }
        },
    )
}
