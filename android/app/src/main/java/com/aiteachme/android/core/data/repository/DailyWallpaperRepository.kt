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

    fun loadWallpaperForDisplay(): DailyWallpaper? {
        cacheDir.mkdirs()
        val prepared = loadCachedWallpaper(
            cacheKeyPref = KEY_NEXT_CACHE_KEY,
            pathPref = KEY_NEXT_PATH,
            urlPref = KEY_NEXT_URL,
        )
        if (prepared != null) {
            rememberCurrent(prepared)
            clearNext()
            cleanupOldFiles(keepPaths = setOf(prepared.filePath))
            return prepared
        }

        val current = loadCachedWallpaper(
            cacheKeyPref = KEY_CURRENT_CACHE_KEY,
            pathPref = KEY_CURRENT_PATH,
            urlPref = KEY_CURRENT_URL,
        ) ?: loadLatestCachedWallpaper()

        if (current != null) {
            rememberCurrent(current)
        }
        return current
    }

    suspend fun prepareNextWallpaper(): DailyWallpaper? = withContext(Dispatchers.IO) {
        cacheDir.mkdirs()
        val today = LocalDate.now().format(DateTimeFormatter.ISO_LOCAL_DATE)
        val cacheKey = "$today-${System.currentTimeMillis()}-${UUID.randomUUID()}"
        val target = File(cacheDir, "learn-background-$cacheKey.jpg")
        val sourceUrl = sourceUrlFor(seed = cacheKey, date = today)

        runCatching {
            download(sourceUrl = sourceUrl, target = target)
            rememberNext(DailyWallpaper(cacheKey, target.absolutePath, sourceUrl))
            val currentPath = loadCachedWallpaper(
                cacheKeyPref = KEY_CURRENT_CACHE_KEY,
                pathPref = KEY_CURRENT_PATH,
                urlPref = KEY_CURRENT_URL,
            )?.filePath
            cleanupOldFiles(keepPaths = setOfNotNull(currentPath, target.absolutePath))
            DailyWallpaper(cacheKey, target.absolutePath, sourceUrl)
        }.getOrElse {
            null
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
        return loadCachedWallpaper(
            cacheKeyPref = KEY_LAST_CACHE_KEY,
            pathPref = KEY_LAST_PATH,
            urlPref = KEY_LAST_URL,
        )
    }

    private fun loadCachedWallpaper(
        cacheKeyPref: String,
        pathPref: String,
        urlPref: String,
    ): DailyWallpaper? {
        val lastPath = prefs.getString(pathPref, null).orEmpty()
        val lastCacheKey = prefs.getString(cacheKeyPref, null).orEmpty()
        val lastUrl = prefs.getString(urlPref, null).orEmpty()
        val file = File(lastPath)
        return if (lastCacheKey.isNotBlank() && lastUrl.isNotBlank() && file.isUsableImage()) {
            DailyWallpaper(lastCacheKey, file.absolutePath, lastUrl)
        } else {
            null
        }
    }

    private fun rememberCurrent(wallpaper: DailyWallpaper) {
        prefs.edit()
            .putString(KEY_CURRENT_CACHE_KEY, wallpaper.cacheKey)
            .putString(KEY_CURRENT_PATH, wallpaper.filePath)
            .putString(KEY_CURRENT_URL, wallpaper.sourceUrl)
            .apply()
    }

    private fun rememberNext(wallpaper: DailyWallpaper) {
        prefs.edit()
            .putString(KEY_NEXT_CACHE_KEY, wallpaper.cacheKey)
            .putString(KEY_NEXT_PATH, wallpaper.filePath)
            .putString(KEY_NEXT_URL, wallpaper.sourceUrl)
            .apply()
    }

    private fun clearNext() {
        prefs.edit()
            .remove(KEY_NEXT_CACHE_KEY)
            .remove(KEY_NEXT_PATH)
            .remove(KEY_NEXT_URL)
            .apply()
    }

    private fun cleanupOldFiles(keepPaths: Set<String>) {
        cacheDir.listFiles()
            .orEmpty()
            .filter { file ->
                file.isFile &&
                    file.name.startsWith("learn-background-") &&
                    file.name.endsWith(".jpg") &&
                    file.absolutePath !in keepPaths
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
        const val KEY_CURRENT_CACHE_KEY = "current_cache_key"
        const val KEY_CURRENT_PATH = "current_path"
        const val KEY_CURRENT_URL = "current_url"
        const val KEY_NEXT_CACHE_KEY = "next_cache_key"
        const val KEY_NEXT_PATH = "next_path"
        const val KEY_NEXT_URL = "next_url"
        const val KEY_LAST_CACHE_KEY = "last_cache_key"
        const val KEY_LAST_PATH = "last_path"
        const val KEY_LAST_URL = "last_url"
        const val MIN_IMAGE_BYTES = 8 * 1024
    }
}
