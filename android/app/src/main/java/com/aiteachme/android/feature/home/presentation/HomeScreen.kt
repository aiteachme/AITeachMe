package com.aiteachme.android.feature.home.presentation

import androidx.activity.compose.BackHandler
import android.graphics.BitmapFactory
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInHorizontally
import androidx.compose.animation.slideOutHorizontally
import androidx.compose.foundation.Canvas
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
import androidx.compose.foundation.layout.offset
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
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material.icons.automirrored.outlined.Chat
import androidx.compose.material.icons.outlined.Add
import androidx.compose.material.icons.outlined.Close
import androidx.compose.material.icons.outlined.Insights
import androidx.compose.material.icons.outlined.Psychology
import androidx.compose.material.icons.outlined.Quiz
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material.icons.outlined.Settings
import androidx.compose.material.icons.outlined.SwapHoriz
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.ListItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
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
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.drawscope.withTransform
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.layout.positionInRoot
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.aiteachme.android.R
import com.aiteachme.android.core.data.repository.ChatConversationScope
import com.aiteachme.android.core.network.dto.CourseItem
import com.aiteachme.android.feature.chat.presentation.ChatScreen
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlin.math.max

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun HomeScreen(
    contentPadding: PaddingValues,
    focusedCourseId: String? = null,
    onBack: (() -> Unit)? = null,
    onSwitchCourse: ((String) -> Unit)? = null,
    onOpenBuild: (String) -> Unit,
    onOpenDocs: (String) -> Unit,
    onOpenPractice: (String) -> Unit,
    onOpenMasteryDrill: (String) -> Unit,
    onOpenProfile: (String) -> Unit,
    onOpenSettings: (String) -> Unit,
    onOpenAccount: () -> Unit,
    viewModel: HomeViewModel = viewModel(),
) {
    val uiState by viewModel.uiState.collectAsState()
    var showCoursePicker by remember { mutableStateOf(false) }
    var showChatPanel by remember { mutableStateOf(false) }
    var showMorePanel by remember { mutableStateOf(false) }

    LaunchedEffect(Unit) {
        viewModel.refresh()
    }

    LaunchedEffect(focusedCourseId, uiState.courses) {
        if (!focusedCourseId.isNullOrBlank() &&
            uiState.selectedCourseId != focusedCourseId &&
            uiState.courses.any { it.courseId == focusedCourseId }
        ) {
            viewModel.selectCourse(focusedCourseId)
        }
    }

    val selectedCourse = focusedCourseId
        ?.let { courseId -> uiState.courses.firstOrNull { it.courseId == courseId } }
        ?: uiState.selectedCourse
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
            selectedCourse = selectedCourse,
            modifier = Modifier
                .fillMaxSize()
                .then(if (panelVisible) Modifier.blur(18.dp) else Modifier),
            onBack = onBack,
            onPickCourse = { showCoursePicker = true },
            onOpenAccount = onOpenAccount,
            onOpenDocs = {
                selectedCourse?.courseId?.let(onOpenDocs) ?: run { showCoursePicker = true }
            },
            onOpenPractice = {
                selectedCourse?.courseId?.let(onOpenPractice) ?: run { showCoursePicker = true }
            },
            onOpenMasteryDrill = {
                selectedCourse?.courseId?.let(onOpenMasteryDrill) ?: run { showCoursePicker = true }
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
                onOpenMasteryDrill = {
                    showMorePanel = false
                    onOpenMasteryDrill(selectedCourse.courseId)
                },
                onOpenProfile = {
                    showMorePanel = false
                    onOpenProfile(selectedCourse.courseId)
                },
                onOpenSettings = {
                    showMorePanel = false
                    onOpenSettings(selectedCourse.courseId)
                },
            )
        }
    }

    if (showCoursePicker) {
        ModalBottomSheet(onDismissRequest = { showCoursePicker = false }) {
            CoursePickerSheet(
                courses = uiState.courses,
                selectedCourseId = focusedCourseId ?: uiState.selectedCourseId,
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
                    onSwitchCourse?.invoke(courseId)
                },
            )
        }
    }

}

@Composable
private fun SubjectHomeSurface(
    uiState: HomeUiState,
    backgroundImagePath: String?,
    selectedCourse: CourseItem?,
    modifier: Modifier,
    onBack: (() -> Unit)?,
    onPickCourse: () -> Unit,
    onOpenAccount: () -> Unit,
    onOpenDocs: () -> Unit,
    onOpenPractice: () -> Unit,
    onOpenMasteryDrill: () -> Unit,
    onOpenChatPanel: () -> Unit,
    onOpenMorePanel: () -> Unit,
) {
    var horizontalDrag by remember { mutableFloatStateOf(0f) }
    val course = selectedCourse
    val wallpaperBitmap = rememberDailyWallpaperBitmap(backgroundImagePath)
    var wallpaperSize by remember { mutableStateOf(IntSize.Zero) }
    var wallpaperOriginInRoot by remember { mutableStateOf(Offset.Zero) }

    Box(
        modifier = modifier
            .onGloballyPositioned { coordinates ->
                wallpaperSize = coordinates.size
                wallpaperOriginInRoot = coordinates.positionInRoot()
            }
            .pointerInput(course?.courseId) {
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
        DailyWallpaperBackground(bitmap = wallpaperBitmap)
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

        onBack?.let { handleBack ->
            IconButton(
                onClick = handleBack,
                modifier = Modifier
                    .align(Alignment.TopStart)
                    .statusBarsPadding()
                    .padding(start = 12.dp, top = 12.dp)
                    .size(44.dp),
            ) {
                Icon(
                    imageVector = Icons.AutoMirrored.Outlined.ArrowBack,
                    contentDescription = "返回",
                    tint = Color.Black,
                )
            }
        }

        CourseChip(
            course = course,
            courseCount = uiState.courses.size,
            isLoading = uiState.isLoadingCourses,
            onClick = onPickCourse,
            modifier = Modifier
                .align(Alignment.TopStart)
                .statusBarsPadding()
                .padding(start = if (onBack == null) 24.dp else 68.dp, top = 22.dp),
        )

        Box(
            modifier = Modifier
                .align(Alignment.TopEnd)
                .statusBarsPadding()
                .padding(top = 18.dp, end = 22.dp)
                .size(38.dp)
                .clip(CircleShape)
                .border(1.5.dp, Color.White.copy(alpha = 0.82f), CircleShape)
                .clickable(onClick = onOpenAccount),
            contentAlignment = Alignment.Center,
        ) {
            Image(
                painter = painterResource(id = R.drawable.default_user_avatar),
                contentDescription = "用户头像",
                modifier = Modifier.fillMaxSize(),
                contentScale = ContentScale.Crop,
            )
        }

        Text(
            text = course?.name?.ifBlank { "未命名学习空间" } ?: "选择学习空间",
            modifier = Modifier
                .align(Alignment.Center)
                .offset(y = (-86).dp)
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

        Column(
            modifier = Modifier
                .align(Alignment.BottomCenter)
                .navigationBarsPadding()
                .padding(horizontal = 22.dp)
                .padding(bottom = 96.dp)
                .fillMaxWidth(),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(14.dp),
            ) {
                PrimarySubjectAction(
                    title = "文档查看",
                    value = "Learn",
                    wallpaperBitmap = wallpaperBitmap,
                    wallpaperContainerSize = wallpaperSize,
                    wallpaperOriginInRoot = wallpaperOriginInRoot,
                    modifier = Modifier.weight(1f),
                    onClick = onOpenDocs,
                )
                PrimarySubjectAction(
                    title = "闯关测试",
                    value = "Review",
                    wallpaperBitmap = wallpaperBitmap,
                    wallpaperContainerSize = wallpaperSize,
                    wallpaperOriginInRoot = wallpaperOriginInRoot,
                    modifier = Modifier.weight(1f),
                    onClick = onOpenMasteryDrill,
                )
            }
        }
    }
}

@Composable
private fun rememberDailyWallpaperBitmap(backgroundImagePath: String?): ImageBitmap? {
    var remoteBitmap by remember(backgroundImagePath) { mutableStateOf<ImageBitmap?>(null) }

    LaunchedEffect(backgroundImagePath) {
        remoteBitmap = null
        val path = backgroundImagePath ?: return@LaunchedEffect
        remoteBitmap = withContext(Dispatchers.IO) {
            BitmapFactory.decodeFile(path)?.asImageBitmap()
        }
    }

    return remoteBitmap
}

@Composable
private fun DailyWallpaperBackground(
    bitmap: ImageBitmap?,
    modifier: Modifier = Modifier.fillMaxSize(),
) {
    if (bitmap != null) {
        Image(
            bitmap = bitmap,
            contentDescription = null,
            modifier = modifier,
            contentScale = ContentScale.Crop,
        )
    } else {
        Box(
            modifier = modifier.background(
                Brush.verticalGradient(
                    colors = listOf(
                        Color(0xFFEFF5F3),
                        Color(0xFFC9D8D4),
                    ),
                ),
            ),
        )
    }
}

@Composable
private fun AlignedWallpaperBlur(
    bitmap: ImageBitmap,
    containerSize: IntSize,
    containerOriginInRoot: Offset,
    blurRadius: Dp,
    modifier: Modifier = Modifier,
) {
    var itemOriginInRoot by remember { mutableStateOf(Offset.Zero) }

    Canvas(
        modifier = modifier
            .onGloballyPositioned { coordinates ->
                itemOriginInRoot = coordinates.positionInRoot()
            }
            .blur(blurRadius),
    ) {
        if (containerSize.width <= 0 || containerSize.height <= 0) return@Canvas

        val containerWidth = containerSize.width.toFloat()
        val containerHeight = containerSize.height.toFloat()
        val scale = max(containerWidth / bitmap.width.toFloat(), containerHeight / bitmap.height.toFloat())
        val scaledWidth = bitmap.width * scale
        val scaledHeight = bitmap.height * scale
        val itemOffset = itemOriginInRoot - containerOriginInRoot

        withTransform(
            {
                translate(
                    left = (containerWidth - scaledWidth) / 2f - itemOffset.x,
                    top = (containerHeight - scaledHeight) / 2f - itemOffset.y,
                )
                scale(scaleX = scale, scaleY = scale, pivot = Offset.Zero)
            },
        ) {
            drawImage(bitmap)
        }
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
    Row(
        modifier = modifier.clickable(onClick = onClick),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        if (isLoading) {
            CircularProgressIndicator(
                modifier = Modifier.size(16.dp),
                strokeWidth = 2.dp,
                color = Color.Black,
            )
        }
        Text(
            text = course?.name?.ifBlank { "未命名学习空间" } ?: "选择学习空间",
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.Black,
            color = Color.Black,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.widthIn(max = 210.dp),
        )
        Icon(
            imageVector = Icons.Outlined.SwapHoriz,
            contentDescription = null,
            tint = Color.Black.copy(alpha = 0.80f),
            modifier = Modifier.size(18.dp),
        )
    }
}

@Composable
private fun PrimarySubjectAction(
    title: String,
    value: String,
    wallpaperBitmap: ImageBitmap?,
    wallpaperContainerSize: IntSize,
    wallpaperOriginInRoot: Offset,
    modifier: Modifier = Modifier,
    onClick: () -> Unit,
) {
    val shape = RoundedCornerShape(16.dp)

    Box(
        modifier = modifier
            .height(92.dp)
            .clip(shape)
            .clickable(
                interactionSource = remember { MutableInteractionSource() },
                indication = null,
                onClick = onClick,
            ),
        contentAlignment = Alignment.CenterStart,
    ) {
        if (wallpaperBitmap != null) {
            AlignedWallpaperBlur(
                bitmap = wallpaperBitmap,
                containerSize = wallpaperContainerSize,
                containerOriginInRoot = wallpaperOriginInRoot,
                blurRadius = 10.dp,
                modifier = Modifier.matchParentSize(),
            )
        }
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
private fun SpaceAgentAction(
    wallpaperBitmap: ImageBitmap?,
    wallpaperContainerSize: IntSize,
    wallpaperOriginInRoot: Offset,
    onClick: () -> Unit,
) {
    val shape = RoundedCornerShape(999.dp)

    Box(
        modifier = Modifier
            .fillMaxWidth()
            .height(50.dp)
            .clip(shape)
            .clickable(
                interactionSource = remember { MutableInteractionSource() },
                indication = null,
                onClick = onClick,
            ),
        contentAlignment = Alignment.Center,
    ) {
        if (wallpaperBitmap != null) {
            AlignedWallpaperBlur(
                bitmap = wallpaperBitmap,
                containerSize = wallpaperContainerSize,
                containerOriginInRoot = wallpaperOriginInRoot,
                blurRadius = 8.dp,
                modifier = Modifier.matchParentSize(),
            )
        }
        Box(
            modifier = Modifier
                .matchParentSize()
                .background(Color.White.copy(alpha = 0.30f)),
        )
        Row(
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(
                imageVector = Icons.AutoMirrored.Outlined.Chat,
                contentDescription = null,
                tint = Color.Black,
                modifier = Modifier.size(18.dp),
            )
            Text(
                text = "空间助手",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Black,
                color = Color.Black,
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
                    .fillMaxWidth(),
                color = MaterialTheme.colorScheme.surface,
                shape = RoundedCornerShape(0.dp),
                shadowElevation = 0.dp,
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
    onOpenMasteryDrill: () -> Unit,
    onOpenProfile: () -> Unit,
    onOpenSettings: () -> Unit,
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
                    .fillMaxWidth(),
                color = MaterialTheme.colorScheme.surface,
                shape = RoundedCornerShape(0.dp),
                shadowElevation = 0.dp,
            ) {
                Column(
                    modifier = Modifier
                        .fillMaxSize()
                        .statusBarsPadding()
                        .navigationBarsPadding()
                        .padding(horizontal = 20.dp, vertical = 22.dp),
                    verticalArrangement = Arrangement.spacedBy(14.dp),
                ) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.Top,
                    ) {
                        Column(modifier = Modifier.weight(1f)) {
                            Text(
                                text = course.name.ifBlank { "未命名学习空间" },
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
                        title = "闯关测试",
                        subtitle = "从题库模板抽题即时闯关，不生成试卷记录",
                        icon = Icons.Outlined.SwapHoriz,
                        onClick = onOpenMasteryDrill,
                    )
                    MoreFunctionItem(
                        title = "学习画像",
                        subtitle = "掌握度、薄弱点和复习任务",
                        icon = Icons.Outlined.Insights,
                        onClick = onOpenProfile,
                    )
                    MoreFunctionItem(
                        title = "学科设置",
                        subtitle = "管理当前学习空间的名称、目标和后续偏好",
                        icon = Icons.Outlined.Settings,
                        onClick = onOpenSettings,
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
                text = text ?: "正在同步学习空间...",
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
            Text(text = "切换学习空间", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
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
                    Text("新建空间")
                }
            }
        }
        if (courses.isEmpty()) {
            Text(
                text = if (isLoading) "正在加载学习空间..." else "暂无学习空间，先新建一个。",
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
                            Text(course.name.ifBlank { "未命名学习空间" }, maxLines = 1, overflow = TextOverflow.Ellipsis)
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
