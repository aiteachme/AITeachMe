package com.aiteachme.android.core.data.repository

import android.content.Context
import android.graphics.BitmapFactory
import com.aiteachme.android.BuildConfig
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.File
import java.time.LocalDate
import java.time.format.DateTimeFormatter
import java.util.UUID
import java.util.concurrent.TimeUnit

data class DailyWallpaper(
    val cacheKey: String,
    val filePath: String,
    val sourceUrl: String,
)

class DailyWallpaperRepository(
    context: Context,
    private val client: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .writeTimeout(30, TimeUnit.SECONDS)
        .followRedirects(true)
        .followSslRedirects(true)
        .build(),
) {
    private val appContext = context.applicationContext
    private val cacheDir = File(appContext.cacheDir, CACHE_DIR_NAME)
    private val prefs = appContext.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    suspend fun loadRandom(): DailyWallpaper? = withContext(Dispatchers.IO) {
        cacheDir.mkdirs()
        val today = LocalDate.now().format(DateTimeFormatter.ISO_LOCAL_DATE)
        val cacheKey = "$today-${System.currentTimeMillis()}-${UUID.randomUUID()}"
        val target = File(cacheDir, "learn-background-$cacheKey.jpg")
        val sourceUrl = sourceUrlFor(seed = cacheKey, date = today)

        runCatching {
            download(sourceUrl = sourceUrl, target = target)
            cleanupOldFiles(keepPath = target.absolutePath)
            remember(cacheKey, target.absolutePath, sourceUrl)
            DailyWallpaper(cacheKey, target.absolutePath, sourceUrl)
        }.getOrElse {
            loadLatestCachedWallpaper()
        }
    }

    private fun download(sourceUrl: String, target: File) {
        val request = Request.Builder()
            .url(sourceUrl)
            .header("Accept", "image/*")
            .build()
        val temp = File.createTempFile("learn-background-", ".download", cacheDir)

        try {
            client.newCall(request).execute().use { response ->
                if (!response.isSuccessful) {
                    error("Wallpaper request failed: HTTP ${response.code}")
                }
                val body = response.body ?: error("Wallpaper response has no body")
                body.byteStream().use { input ->
                    temp.outputStream().use { output ->
                        input.copyTo(output)
                    }
                }
            }

            if (!temp.isUsableImage()) {
                error("Wallpaper response is not a valid image")
            }

            if (target.exists()) {
                target.delete()
            }
            if (!temp.renameTo(target)) {
                temp.copyTo(target, overwrite = true)
                temp.delete()
            }
        } finally {
            if (temp.exists()) {
                temp.delete()
            }
        }
    }

    private fun sourceUrlFor(seed: String, date: String): String {
        val template = BuildConfig.WALLPAPER_URL_TEMPLATE
        return when {
            template.contains("{seed}") -> template.replace("{seed}", seed).replace("{date}", date)
            template.contains("{date}") -> template.replace("{date}", date)
            template.contains("%s") -> template.replace("%s", seed)
            template.contains("?") -> "$template&seed=$seed"
            else -> "$template?seed=$seed"
        }
    }

    private fun loadLatestCachedWallpaper(): DailyWallpaper? {
        val lastPath = prefs.getString(KEY_LAST_PATH, null).orEmpty()
        val lastCacheKey = prefs.getString(KEY_LAST_CACHE_KEY, null).orEmpty()
        val lastUrl = prefs.getString(KEY_LAST_URL, null).orEmpty()
        val file = File(lastPath)
        return if (lastCacheKey.isNotBlank() && lastUrl.isNotBlank() && file.isUsableImage()) {
            DailyWallpaper(lastCacheKey, file.absolutePath, lastUrl)
        } else {
            null
        }
    }

    private fun remember(cacheKey: String, path: String, sourceUrl: String) {
        prefs.edit()
            .putString(KEY_LAST_CACHE_KEY, cacheKey)
            .putString(KEY_LAST_PATH, path)
            .putString(KEY_LAST_URL, sourceUrl)
            .apply()
    }

    private fun cleanupOldFiles(keepPath: String) {
        cacheDir.listFiles()
            .orEmpty()
            .filter { file ->
                file.isFile &&
                    file.name.startsWith("learn-background-") &&
                    file.name.endsWith(".jpg") &&
                    file.absolutePath != keepPath
            }
            .forEach { it.delete() }
    }

    private fun File.isUsableImage(): Boolean {
        if (!isFile || length() < MIN_IMAGE_BYTES) {
            return false
        }
        val options = BitmapFactory.Options().apply {
            inJustDecodeBounds = true
        }
        BitmapFactory.decodeFile(absolutePath, options)
        return options.outWidth > 0 && options.outHeight > 0
    }

    private companion object {
        const val CACHE_DIR_NAME = "daily_wallpaper"
        const val PREFS_NAME = "aiteachme_daily_wallpaper"
        const val KEY_LAST_CACHE_KEY = "last_cache_key"
        const val KEY_LAST_PATH = "last_path"
        const val KEY_LAST_URL = "last_url"
        const val MIN_IMAGE_BYTES = 8 * 1024
    }
}
