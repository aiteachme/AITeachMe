package com.aiteachme.android.app

import androidx.compose.foundation.background
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
import androidx.compose.material.icons.outlined.AccountCircle
import androidx.compose.material.icons.outlined.ChatBubbleOutline
import androidx.compose.material.icons.outlined.FolderOpen
import androidx.compose.material.icons.outlined.School
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
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
import com.aiteachme.android.feature.account.presentation.AccountScreen
import com.aiteachme.android.feature.chat.presentation.ChatScreen
import com.aiteachme.android.feature.course.presentation.CourseBuildScreen
import com.aiteachme.android.feature.course.presentation.KnowledgeDocsScreen
import com.aiteachme.android.feature.course.presentation.PracticeScreen
import com.aiteachme.android.feature.course.presentation.ProfileScreen
import com.aiteachme.android.feature.files.presentation.FileDetailScreen
import com.aiteachme.android.feature.files.presentation.FileLibraryScreen
import com.aiteachme.android.feature.home.presentation.HomeScreen

private enum class AppDestination(
    val route: String,
    val label: String,
    val icon: ImageVector,
) {
    Learn("learn", "学习", Icons.Outlined.School),
    Chat("chat", "对话", Icons.Outlined.ChatBubbleOutline),
    Files("files", "资料", Icons.Outlined.FolderOpen),
    Mine("mine", "我的", Icons.Outlined.AccountCircle),
}

private object AppRoute {
    const val Learn = "learn"
    const val Chat = "chat"
    const val CourseChat = "courses/{courseId}/chat"
    const val Files = "files"
    const val FileDetail = "files/{fileId}"
    const val Mine = "mine"
    const val CourseBuild = "courses/{courseId}/build"
    const val CourseDocs = "courses/{courseId}/docs"
    const val CoursePractice = "courses/{courseId}/practice"
    const val CourseProfile = "courses/{courseId}/profile"

    fun courseChat(courseId: String) = "courses/$courseId/chat"
    fun courseBuild(courseId: String) = "courses/$courseId/build"
    fun courseDocs(courseId: String) = "courses/$courseId/docs"
    fun coursePractice(courseId: String) = "courses/$courseId/practice"
    fun courseProfile(courseId: String) = "courses/$courseId/profile"
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
        top = safePadding.calculateTopPadding(),
        end = safePadding.calculateEndPadding(layoutDirection),
        bottom = safePadding.calculateBottomPadding() + 94.dp,
    )

    Box(modifier = Modifier.fillMaxSize()) {
        NavHost(
            navController = navController,
            startDestination = AppRoute.Learn,
            modifier = Modifier.fillMaxSize(),
        ) {
            composable(AppRoute.Learn) {
                HomeScreen(
                    contentPadding = PaddingValues(0.dp),
                    onOpenBuild = { courseId -> navController.navigate(AppRoute.courseBuild(courseId)) },
                    onOpenDocs = { courseId -> navController.navigate(AppRoute.courseDocs(courseId)) },
                    onOpenPractice = { courseId -> navController.navigate(AppRoute.coursePractice(courseId)) },
                    onOpenProfile = { courseId -> navController.navigate(AppRoute.courseProfile(courseId)) },
                    onOpenCourseChat = { courseId -> navController.navigate(AppRoute.courseChat(courseId)) },
                    onOpenFiles = { navController.navigate(AppRoute.Files) },
                )
            }
            composable(AppRoute.Chat) {
                ChatScreen(
                    contentPadding = pageContentPadding,
                    scope = ChatConversationScope.Global,
                )
            }
            composable(
                route = AppRoute.CourseChat,
                arguments = listOf(navArgument("courseId") { type = NavType.StringType }),
            ) { entry ->
                ChatScreen(
                    contentPadding = pageContentPadding,
                    scope = ChatConversationScope.Course,
                    courseId = entry.arguments?.getString("courseId").orEmpty(),
                    onBack = { navController.popBackStack() },
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
                    contentPadding = pageContentPadding,
                    onBack = { navController.popBackStack() },
                )
            }
            composable(AppRoute.Mine) {
                AccountScreen(contentPadding = pageContentPadding)
            }
            composable(
                route = AppRoute.CourseBuild,
                arguments = listOf(navArgument("courseId") { type = NavType.StringType }),
            ) { entry ->
                val courseId = entry.arguments?.getString("courseId").orEmpty()
                CourseBuildScreen(
                    courseId = courseId,
                    contentPadding = pageContentPadding,
                    onBack = { navController.popBackStack() },
                    onOpenFiles = { navController.navigate(AppRoute.Files) },
                    onOpenDocs = { navController.navigate(AppRoute.courseDocs(it)) },
                )
            }
            composable(
                route = AppRoute.CourseDocs,
                arguments = listOf(navArgument("courseId") { type = NavType.StringType }),
            ) { entry ->
                val courseId = entry.arguments?.getString("courseId").orEmpty()
                KnowledgeDocsScreen(
                    courseId = courseId,
                    contentPadding = pageContentPadding,
                    onBack = { navController.popBackStack() },
                    onOpenBuild = { navController.navigate(AppRoute.courseBuild(it)) },
                )
            }
            composable(
                route = AppRoute.CoursePractice,
                arguments = listOf(navArgument("courseId") { type = NavType.StringType }),
            ) { entry ->
                val courseId = entry.arguments?.getString("courseId").orEmpty()
                PracticeScreen(
                    courseId = courseId,
                    contentPadding = pageContentPadding,
                    onBack = { navController.popBackStack() },
                    onOpenDocs = { navController.navigate(AppRoute.courseDocs(it)) },
                )
            }
            composable(
                route = AppRoute.CourseProfile,
                arguments = listOf(navArgument("courseId") { type = NavType.StringType }),
            ) { entry ->
                val courseId = entry.arguments?.getString("courseId").orEmpty()
                ProfileScreen(
                    courseId = courseId,
                    contentPadding = pageContentPadding,
                    onBack = { navController.popBackStack() },
                    onOpenPractice = { navController.navigate(AppRoute.coursePractice(it)) },
                )
            }
        }
        FloatingBottomNavigation(
            currentDestination = currentDestination,
            onNavigate = { destination ->
                navController.navigate(destination.route) {
                    popUpTo(navController.graph.startDestinationId) {
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
                IconButton(
                    onClick = { onNavigate(destination) },
                    modifier = Modifier
                        .size(50.dp)
                        .clip(CircleShape)
                        .background(
                            if (selected) {
                                MaterialTheme.colorScheme.primary.copy(alpha = 0.18f)
                            } else {
                                Color.Transparent
                            },
                        ),
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
        AppDestination.Learn -> route == AppRoute.Learn || route.startsWith("courses/")
        AppDestination.Chat -> route == AppRoute.Chat
        AppDestination.Files -> route.startsWith(AppRoute.Files)
        AppDestination.Mine -> route == AppRoute.Mine
    }
}
