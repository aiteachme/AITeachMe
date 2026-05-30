package com.aiteachme.android.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable

private val LightColors = lightColorScheme(
    primary = Teal700,
    onPrimary = White,
    primaryContainer = Teal100,
    onPrimaryContainer = Teal900,
    secondary = Blue700,
    onSecondary = White,
    surface = Neutral50,
    onSurface = Neutral950,
    surfaceContainer = Neutral100,
    onSurfaceVariant = Neutral600,
    error = Red700,
)

private val DarkColors = darkColorScheme(
    primary = Teal300,
    onPrimary = Teal950,
    primaryContainer = Teal800,
    onPrimaryContainer = Teal50,
    secondary = Blue300,
    onSecondary = Blue950,
    surface = Neutral950,
    onSurface = Neutral50,
    surfaceContainer = Neutral900,
    onSurfaceVariant = Neutral300,
    error = Red300,
)

@Composable
fun AiTeachMeTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    content: @Composable () -> Unit,
) {
    MaterialTheme(
        colorScheme = if (darkTheme) DarkColors else LightColors,
        typography = AppTypography,
        content = content,
    )
}
