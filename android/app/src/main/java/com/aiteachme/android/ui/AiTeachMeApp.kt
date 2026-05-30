package com.aiteachme.android.ui

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.AccountCircle
import androidx.compose.material.icons.outlined.ChatBubbleOutline
import androidx.compose.material.icons.outlined.FolderOpen
import androidx.compose.material.icons.outlined.School
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.navigation.NavDestination.Companion.hierarchy
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import com.aiteachme.android.feature.home.HomeScreen
import com.aiteachme.android.feature.placeholder.PlaceholderScreen

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

@Composable
fun AiTeachMeApp() {
    val navController = rememberNavController()
    val navBackStackEntry by navController.currentBackStackEntryAsState()
    val currentDestination = navBackStackEntry?.destination

    Scaffold(
        bottomBar = {
            NavigationBar {
                AppDestination.entries.forEach { destination ->
                    NavigationBarItem(
                        selected = currentDestination?.hierarchy?.any {
                            it.route == destination.route
                        } == true,
                        onClick = {
                            navController.navigate(destination.route) {
                                popUpTo(navController.graph.startDestinationId) {
                                    saveState = true
                                }
                                launchSingleTop = true
                                restoreState = true
                            }
                        },
                        icon = {
                            Icon(
                                imageVector = destination.icon,
                                contentDescription = destination.label,
                            )
                        },
                        label = { Text(destination.label) },
                    )
                }
            }
        },
    ) { contentPadding ->
        NavHost(
            navController = navController,
            startDestination = AppDestination.Learn.route,
        ) {
            composable(AppDestination.Learn.route) {
                HomeScreen(contentPadding = contentPadding)
            }
            composable(AppDestination.Chat.route) {
                PlaceholderScreen(
                    title = "对话",
                    description = "下一步接入课程上下文、SSE 流式回复和附件选择。",
                    contentPadding = contentPadding,
                )
            }
            composable(AppDestination.Files.route) {
                PlaceholderScreen(
                    title = "资料",
                    description = "下一步接入文件选择、上传进度、课程资料列表和解析状态。",
                    contentPadding = contentPadding,
                )
            }
            composable(AppDestination.Mine.route) {
                PlaceholderScreen(
                    title = "我的",
                    description = "下一步接入登录状态、API 地址配置、模型设置和账户信息。",
                    contentPadding = contentPadding,
                )
            }
        }
    }
}
