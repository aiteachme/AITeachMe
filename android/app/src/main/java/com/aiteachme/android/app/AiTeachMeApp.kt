package com.aiteachme.android.app

import android.net.Uri
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.asPaddingValues
import androidx.compose.foundation.layout.calculateEndPadding
import androidx.compose.foundation.layout.calculateStartPadding
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.Chat
import androidx.compose.material.icons.outlined.FolderOpen
import androidx.compose.material.icons.outlined.School
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalLayoutDirection
import androidx.compose.ui.unit.dp
import androidx.navigation.NavDestination
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import com.aiteachme.android.core.data.repository.ChatConversationScope
import com.aiteachme.android.core.di.AppServices
import com.aiteachme.android.feature.account.presentation.AccountScreen
import com.aiteachme.android.feature.chat.presentation.ChatScreen
import com.aiteachme.android.feature.chat.presentation.GlobalAssistantEntryScreen
import com.aiteachme.android.feature.course.presentation.CourseBuildScreen
import com.aiteachme.android.feature.course.presentation.CourseSettingsScreen
import com.aiteachme.android.feature.course.presentation.ExamPaperScreen
import com.aiteachme.android.feature.course.presentation.KnowledgeDocsScreen
import com.aiteachme.android.feature.course.presentation.MasteryDrillScreen
import com.aiteachme.android.feature.course.presentation.PracticeScreen
import com.aiteachme.android.feature.course.presentation.ProfileScreen
import com.aiteachme.android.feature.files.presentation.FileDetailScreen
import com.aiteachme.android.feature.files.presentation.FileLibraryScreen
import com.aiteachme.android.feature.home.presentation.HomeScreen
import com.aiteachme.android.feature.newcourse.presentation.NewCourseScreen
import com.aiteachme.android.feature.spaces.presentation.LearningSpacesScreen
import androidx.lifecycle.viewmodel.compose.viewModel

private enum class AppDestination(
    val route: String,
    val label: String,
    val icon: ImageVector,
) {
    Learn("learn", "学习空间", Icons.Outlined.School),
    Files("files", "资料库", Icons.Outlined.FolderOpen),
    Chat("chat", "全局助手", Icons.AutoMirrored.Outlined.Chat),
}

private object AppRoute {
    const val Startup = "startup"
    const val NewCourse = "new-course"
    const val Learn = "learn"
    const val Chat = "chat"
    const val GlobalChat = "chat/conversation?initialPrompt={initialPrompt}&sessionId={sessionId}"
    const val CourseSpace = "spaces/{courseId}"
    const val CourseChat = "courses/{courseId}/chat"
    const val Files = "files"
    const val FileDetail = "files/{fileId}"
    const val Mine = "mine"
    const val CourseBuild = "courses/{courseId}/build?initialPrompt={initialPrompt}"
    const val CourseDocs = "courses/{courseId}/docs"
    const val CoursePractice = "courses/{courseId}/practice"
    const val CourseMasteryDrill = "courses/{courseId}/mastery-drill"
    const val CourseExamPaper = "courses/{courseId}/exams/{examPaperId}"
    const val CourseProfile = "courses/{courseId}/profile"
    const val CourseSettings = "courses/{courseId}/settings"

    fun courseChat(courseId: String) = "courses/$courseId/chat"
    fun globalChat(initialPrompt: String? = null, sessionId: String? = null): String {
        val prompt = initialPrompt?.trim().orEmpty()
        val normalizedSessionId = sessionId?.trim().orEmpty()
        val params = buildList {
            if (prompt.isNotBlank()) {
                add("initialPrompt=${Uri.encode(prompt)}")
            } else if (normalizedSessionId.isNotBlank()) {
                add("initialPrompt=")
            }
            if (normalizedSessionId.isNotBlank()) {
                add("sessionId=${Uri.encode(normalizedSessionId)}")
            }
        }
        return if (params.isEmpty()) {
            "chat/conversation"
        } else {
            "chat/conversation?${params.joinToString("&")}"
        }
    }
    fun courseSpace(courseId: String) = "spaces/$courseId"
    fun courseBuild(courseId: String, initialPrompt: String? = null): String {
        val prompt = initialPrompt?.trim().orEmpty()
        return if (prompt.isBlank()) {
            "courses/$courseId/build"
        } else {
            "courses/$courseId/build?initialPrompt=${Uri.encode(prompt)}"
        }
    }
    fun courseDocs(courseId: String) = "courses/$courseId/docs"
    fun coursePractice(courseId: String) = "courses/$courseId/practice"
    fun courseMasteryDrill(courseId: String) = "courses/$courseId/mastery-drill"
    fun courseExamPaper(courseId: String, examPaperId: Int) = "courses/$courseId/exams/$examPaperId"
    fun courseProfile(courseId: String) = "courses/$courseId/profile"
    fun courseSettings(courseId: String) = "courses/$courseId/settings"
    fun fileDetail(fileId: String) = "files/$fileId"
}

@Composable
fun AiTeachMeApp() {
    val navController = rememberNavController()
    val navBackStackEntry by navController.currentBackStackEntryAsState()
    val currentDestination = navBackStackEntry?.destination
    val layoutDirection = LocalLayoutDirection.current
    val safePadding = WindowInsets.safeDrawing.asPaddingValues()
    val pageContentPadding = PaddingValues(
        start = safePadding.calculateStartPadding(layoutDirection),
        top = 0.dp,
        end = safePadding.calculateEndPadding(layoutDirection),
        bottom = safePadding.calculateBottomPadding() + 94.dp,
    )
    val childContentPadding = PaddingValues(
        start = safePadding.calculateStartPadding(layoutDirection),
        top = 0.dp,
        end = safePadding.calculateEndPadding(layoutDirection),
        bottom = safePadding.calculateBottomPadding(),
    )
    val showBottomNavigation = AppDestination.entries.any { it.route == currentDestination?.route }

    fun navigateBackToLearn() {
        if (!navController.popBackStack()) {
            navController.navigate(AppRoute.Learn) {
                launchSingleTop = true
            }
        }
    }

    Box(modifier = Modifier.fillMaxSize()) {
        NavHost(
            navController = navController,
            startDestination = AppRoute.Startup,
            modifier = Modifier.fillMaxSize(),
        ) {
            composable(AppRoute.Startup) {
                val startupViewModel: AppStartupViewModel = viewModel()
                val startupUiState by startupViewModel.uiState.collectAsState()

                LaunchedEffect(startupUiState.isReady, startupUiState.targetCourseId) {
                    if (startupUiState.isReady) {
                        navController.navigate(AppRoute.Learn) {
                            popUpTo(AppRoute.Startup) {
                                inclusive = true
                            }
                            launchSingleTop = true
                        }
                        startupUiState.targetCourseId?.takeIf { it.isNotBlank() }?.let { courseId ->
                            navController.navigate(AppRoute.courseSpace(courseId)) {
                                launchSingleTop = true
                            }
                        }
                    }
                }

                StartupScreen()
            }
            composable(AppRoute.NewCourse) {
                NewCourseScreen(
                    contentPadding = childContentPadding,
                    onBack = { navController.popBackStack() },
                    onCourseCreated = { courseId, prompt ->
                        navController.navigate(AppRoute.courseBuild(courseId, prompt)) {
                            launchSingleTop = true
                            popUpTo(AppRoute.Learn)
                        }
                    },
                )
            }
            composable(AppRoute.Learn) {
                LearningSpacesScreen(
                    contentPadding = pageContentPadding,
                    onOpenCourse = { courseId ->
                        navController.navigate(AppRoute.courseSpace(courseId)) {
                            launchSingleTop = true
                        }
                    },
                    onOpenNewCourse = {
                        navController.navigate(AppRoute.NewCourse) {
                            launchSingleTop = true
                        }
                    },
                )
            }
            composable(
                route = AppRoute.CourseSpace,
                arguments = listOf(navArgument("courseId") { type = NavType.StringType }),
            ) { entry ->
                val courseId = entry.arguments?.getString("courseId").orEmpty()
                TrackCurrentCourse(courseId)
                HomeScreen(
                    contentPadding = PaddingValues(0.dp),
                    focusedCourseId = courseId,
                    onBack = { navigateBackToLearn() },
                    onSwitchCourse = { nextCourseId ->
                        navController.navigate(AppRoute.courseSpace(nextCourseId)) {
                            popUpTo(AppRoute.Learn)
                            launchSingleTop = true
                        }
                    },
                    onOpenBuild = { courseId -> navController.navigate(AppRoute.courseBuild(courseId)) },
                    onOpenDocs = { courseId -> navController.navigate(AppRoute.courseDocs(courseId)) },
                    onOpenPractice = { courseId -> navController.navigate(AppRoute.coursePractice(courseId)) },
                    onOpenMasteryDrill = { courseId -> navController.navigate(AppRoute.courseMasteryDrill(courseId)) },
                    onOpenProfile = { courseId -> navController.navigate(AppRoute.courseProfile(courseId)) },
                    onOpenSettings = { courseId -> navController.navigate(AppRoute.courseSettings(courseId)) },
                    onOpenAccount = { navController.navigate(AppRoute.Mine) },
                )
            }
            composable(AppRoute.Chat) {
                GlobalAssistantEntryScreen(
                    contentPadding = pageContentPadding,
                    onStartChat = { prompt -> navController.navigate(AppRoute.globalChat(prompt)) },
                    onOpenSession = { sessionId -> navController.navigate(AppRoute.globalChat(sessionId = sessionId)) },
                    onOpenFiles = {
                        navController.navigate(AppRoute.Files) {
                            launchSingleTop = true
                        }
                    },
                )
            }
            composable(
                route = AppRoute.GlobalChat,
                arguments = listOf(
                    navArgument("initialPrompt") {
                        type = NavType.StringType
                        nullable = true
                        defaultValue = null
                    },
                    navArgument("sessionId") {
                        type = NavType.StringType
                        nullable = true
                        defaultValue = null
                    },
                ),
            ) { entry ->
                ChatScreen(
                    contentPadding = childContentPadding,
                    scope = ChatConversationScope.Global,
                    initialPrompt = entry.arguments?.getString("initialPrompt"),
                    initialSessionId = entry.arguments?.getString("sessionId"),
                    onBack = { navController.popBackStack() },
                )
            }
            composable(
                route = AppRoute.CourseChat,
                arguments = listOf(navArgument("courseId") { type = NavType.StringType }),
            ) { entry ->
                val courseId = entry.arguments?.getString("courseId").orEmpty()
                TrackCurrentCourse(courseId)
                ChatScreen(
                    contentPadding = childContentPadding,
                    scope = ChatConversationScope.Course,
                    courseId = courseId,
                    onBack = { navigateBackToLearn() },
                )
            }
            composable(AppRoute.Files) {
                FileLibraryScreen(
                    contentPadding = pageContentPadding,
                    onOpenFile = { fileId -> navController.navigate(AppRoute.fileDetail(fileId)) },
                )
            }
            composable(
                route = AppRoute.FileDetail,
                arguments = listOf(navArgument("fileId") { type = NavType.StringType }),
            ) { entry ->
                FileDetailScreen(
                    fileId = entry.arguments?.getString("fileId").orEmpty(),
                    contentPadding = childContentPadding,
                    onBack = { navController.popBackStack() },
                )
            }
            composable(AppRoute.Mine) {
                AccountScreen(
                    contentPadding = childContentPadding,
                    onBack = { navController.popBackStack() },
                )
            }
            composable(
                route = AppRoute.CourseBuild,
                arguments = listOf(
                    navArgument("courseId") { type = NavType.StringType },
                    navArgument("initialPrompt") {
                        type = NavType.StringType
                        nullable = true
                        defaultValue = null
                    },
                ),
            ) { entry ->
                val courseId = entry.arguments?.getString("courseId").orEmpty()
                TrackCurrentCourse(courseId)
                CourseBuildScreen(
                    courseId = courseId,
                    initialPrompt = entry.arguments?.getString("initialPrompt"),
                    contentPadding = childContentPadding,
                    onBack = { navigateBackToLearn() },
                    onOpenFiles = { navController.navigate(AppRoute.Files) },
                    onOpenDocs = { targetCourseId -> navController.navigate(AppRoute.courseDocs(targetCourseId)) },
                )
            }
            composable(
                route = AppRoute.CourseDocs,
                arguments = listOf(navArgument("courseId") { type = NavType.StringType }),
            ) { entry ->
                val courseId = entry.arguments?.getString("courseId").orEmpty()
                TrackCurrentCourse(courseId)
                KnowledgeDocsScreen(
                    courseId = courseId,
                    contentPadding = childContentPadding,
                    onBack = { navigateBackToLearn() },
                    onOpenBuild = { targetCourseId -> navController.navigate(AppRoute.courseBuild(targetCourseId)) },
                )
            }
            composable(
                route = AppRoute.CoursePractice,
                arguments = listOf(navArgument("courseId") { type = NavType.StringType }),
            ) { entry ->
                val courseId = entry.arguments?.getString("courseId").orEmpty()
                TrackCurrentCourse(courseId)
                PracticeScreen(
                    courseId = courseId,
                    contentPadding = childContentPadding,
                    onBack = { navigateBackToLearn() },
                    onOpenDocs = { targetCourseId -> navController.navigate(AppRoute.courseDocs(targetCourseId)) },
                    onOpenPaper = { targetCourseId, paperId ->
                        navController.navigate(AppRoute.courseExamPaper(targetCourseId, paperId))
                    },
                )
            }
            composable(
                route = AppRoute.CourseMasteryDrill,
                arguments = listOf(navArgument("courseId") { type = NavType.StringType }),
            ) { entry ->
                val courseId = entry.arguments?.getString("courseId").orEmpty()
                TrackCurrentCourse(courseId)
                MasteryDrillScreen(
                    courseId = courseId,
                    contentPadding = childContentPadding,
                    onBack = { navigateBackToLearn() },
                    onOpenPractice = { targetCourseId ->
                        navController.navigate(AppRoute.coursePractice(targetCourseId))
                    },
                )
            }
            composable(
                route = AppRoute.CourseExamPaper,
                arguments = listOf(
                    navArgument("courseId") { type = NavType.StringType },
                    navArgument("examPaperId") { type = NavType.IntType },
                ),
            ) { entry ->
                val courseId = entry.arguments?.getString("courseId").orEmpty()
                val examPaperId = entry.arguments?.getInt("examPaperId") ?: 0
                TrackCurrentCourse(courseId)
                ExamPaperScreen(
                    courseId = courseId,
                    examPaperId = examPaperId,
                    contentPadding = childContentPadding,
                    onBack = { navController.popBackStack() },
                )
            }
            composable(
                route = AppRoute.CourseProfile,
                arguments = listOf(navArgument("courseId") { type = NavType.StringType }),
            ) { entry ->
                val courseId = entry.arguments?.getString("courseId").orEmpty()
                TrackCurrentCourse(courseId)
                ProfileScreen(
                    courseId = courseId,
                    contentPadding = childContentPadding,
                    onBack = { navigateBackToLearn() },
                    onOpenPractice = { targetCourseId -> navController.navigate(AppRoute.coursePractice(targetCourseId)) },
                )
            }
            composable(
                route = AppRoute.CourseSettings,
                arguments = listOf(navArgument("courseId") { type = NavType.StringType }),
            ) { entry ->
                val courseId = entry.arguments?.getString("courseId").orEmpty()
                TrackCurrentCourse(courseId)
                CourseSettingsScreen(
                    courseId = courseId,
                    contentPadding = childContentPadding,
                    onBack = { navigateBackToLearn() },
                    onOpenBuild = { targetCourseId -> navController.navigate(AppRoute.courseBuild(targetCourseId)) },
                )
            }
        }
        if (showBottomNavigation) {
            FloatingBottomNavigation(
                currentDestination = currentDestination,
                onNavigate = { destination ->
                    navController.navigate(destination.route) {
                        popUpTo(AppRoute.Learn) {
                            saveState = true
                        }
                        launchSingleTop = true
                        restoreState = true
                    }
                },
                modifier = Modifier
                    .align(Alignment.BottomCenter)
                    .navigationBarsPadding()
                    .padding(bottom = 12.dp),
            )
        }
    }
}

@Composable
private fun StartupScreen() {
    Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        CircularProgressIndicator()
    }
}

@Composable
private fun TrackCurrentCourse(courseId: String) {
    LaunchedEffect(courseId) {
        AppServices.courseContextStore.selectCourse(courseId)
    }
}

@Composable
private fun FloatingBottomNavigation(
    currentDestination: NavDestination?,
    onNavigate: (AppDestination) -> Unit,
    modifier: Modifier = Modifier,
) {
    Surface(
        modifier = modifier,
        color = MaterialTheme.colorScheme.surface.copy(alpha = 0.58f),
        contentColor = MaterialTheme.colorScheme.onSurface,
        shape = RoundedCornerShape(34.dp),
        shadowElevation = 12.dp,
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 10.dp, vertical = 8.dp),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            AppDestination.entries.forEach { destination ->
                val selected = isDestinationSelected(currentDestination, destination)
                Box(
                    modifier = Modifier
                        .size(50.dp)
                        .clip(CircleShape)
                        .background(
                            if (selected) {
                                MaterialTheme.colorScheme.primary.copy(alpha = 0.18f)
                            } else {
                                Color.Transparent
                            },
                        )
                        .clickable { onNavigate(destination) },
                    contentAlignment = Alignment.Center,
                ) {
                    Icon(
                        imageVector = destination.icon,
                        contentDescription = destination.label,
                        tint = if (selected) {
                            MaterialTheme.colorScheme.primary
                        } else {
                            MaterialTheme.colorScheme.onSurface.copy(alpha = 0.76f)
                        },
                    )
                }
            }
        }
    }
}

private fun isDestinationSelected(
    currentDestination: NavDestination?,
    destination: AppDestination,
): Boolean {
    val route = currentDestination?.route ?: return false
    return when (destination) {
        AppDestination.Learn -> route == AppRoute.Learn
        AppDestination.Files -> route.startsWith(AppRoute.Files)
        AppDestination.Chat -> route == AppRoute.Chat
    }
}
