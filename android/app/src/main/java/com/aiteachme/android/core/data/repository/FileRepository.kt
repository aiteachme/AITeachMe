package com.aiteachme.android.core.data.repository

import android.content.ContentResolver
import android.content.Context
import android.database.Cursor
import android.net.Uri
import android.provider.OpenableColumns
import android.webkit.MimeTypeMap
import com.aiteachme.android.core.network.AiTeachMeApi
import com.aiteachme.android.core.network.dto.CourseFilesLinkRequest
import com.aiteachme.android.core.network.dto.FileDeleteRequest
import com.aiteachme.android.core.network.dto.FileRecord
import com.aiteachme.android.core.network.dto.FilesData
import com.aiteachme.android.core.network.dto.FilesUploadData
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.MultipartBody
import okhttp3.RequestBody
import okio.BufferedSink
import okio.source
import java.io.IOException
import java.util.Locale

data class UploadFileRef(
    val uri: Uri,
    val filename: String,
    val mimeType: String?,
    val sizeBytes: Long?,
)

class FileRepository(
    private val api: AiTeachMeApi,
    context: Context,
) {
    private val appContext = context.applicationContext
    private val contentResolver: ContentResolver = appContext.contentResolver

    fun resolveUploadFiles(uris: List<Uri>): List<UploadFileRef> {
        return uris.distinct().map { uri ->
            val metadata = queryMetadata(uri)
            val mimeType = contentResolver.getType(uri)
            val fallbackExtension = MimeTypeMap.getSingleton()
                .getExtensionFromMimeType(mimeType)
                ?.takeIf { it.isNotBlank() }
            val filename = metadata.displayName
                ?: uri.lastPathSegment?.substringAfterLast('/')
                ?: "upload${fallbackExtension?.let { ".$it" }.orEmpty()}"
            UploadFileRef(
                uri = uri,
                filename = filename,
                mimeType = mimeType,
                sizeBytes = metadata.sizeBytes,
            )
        }
    }

    suspend fun listFiles(): FilesData {
        val response = api.listUserFiles()
        if (response.code != 0) {
            throw IllegalStateException(response.message.ifBlank { "资料库加载失败" })
        }
        return response.data ?: FilesData()
    }

    suspend fun getFile(fileId: String): FileRecord? {
        val response = api.listUserFiles(fileIds = listOf(fileId))
        if (response.code != 0) {
            throw IllegalStateException(response.message.ifBlank { "资料加载失败" })
        }
        return response.data?.items?.firstOrNull { it.id == fileId }
    }

    suspend fun listCourseFiles(courseId: String): FilesData {
        val response = api.listCourseFiles(courseId)
        if (response.code != 0) {
            throw IllegalStateException(response.message.ifBlank { "课程资料加载失败" })
        }
        return response.data ?: FilesData(courseId = courseId)
    }

    suspend fun uploadFiles(files: List<UploadFileRef>): FilesUploadData {
        if (files.isEmpty()) {
            return FilesUploadData()
        }
        val parts = files.map { file ->
            MultipartBody.Part.createFormData(
                name = "files",
                filename = file.filename,
                body = ContentUriRequestBody(
                    contentResolver = contentResolver,
                    uri = file.uri,
                    mimeType = file.mimeType,
                    sizeBytes = file.sizeBytes,
                ),
            )
        }
        val response = api.uploadUserFiles(parts)
        if (response.code != 0) {
            throw IllegalStateException(response.message.ifBlank { "资料上传失败" })
        }
        return response.data ?: FilesUploadData()
    }

    suspend fun uploadCourseFiles(courseId: String, files: List<UploadFileRef>): FilesUploadData {
        if (files.isEmpty()) {
            return FilesUploadData(courseId = courseId)
        }
        val parts = files.map { file ->
            MultipartBody.Part.createFormData(
                name = "files",
                filename = file.filename,
                body = ContentUriRequestBody(
                    contentResolver = contentResolver,
                    uri = file.uri,
                    mimeType = file.mimeType,
                    sizeBytes = file.sizeBytes,
                ),
            )
        }
        val response = api.uploadCourseFiles(courseId = courseId, files = parts)
        if (response.code != 0) {
            throw IllegalStateException(response.message.ifBlank { "课程资料上传失败" })
        }
        return response.data ?: FilesUploadData(courseId = courseId)
    }

    suspend fun linkFilesToCourse(courseId: String, fileIds: List<String>): FilesData {
        val response = api.linkCourseFiles(
            courseId = courseId,
            request = CourseFilesLinkRequest(fileIds = fileIds),
        )
        if (response.code != 0) {
            throw IllegalStateException(response.message.ifBlank { "资料关联失败" })
        }
        return response.data ?: FilesData(courseId = courseId)
    }

    suspend fun deleteFile(fileId: String) {
        val response = api.deleteUserFiles(FileDeleteRequest(fileId = fileId))
        if (response.code != 0) {
            throw IllegalStateException(response.message.ifBlank { "资料删除失败" })
        }
    }

    suspend fun deleteCourseFile(courseId: String, fileId: String) {
        val response = api.deleteCourseFiles(courseId = courseId, request = FileDeleteRequest(fileId = fileId))
        if (response.code != 0) {
            throw IllegalStateException(response.message.ifBlank { "课程资料移除失败" })
        }
    }

    private fun queryMetadata(uri: Uri): FileMetadata {
        var displayName: String? = null
        var sizeBytes: Long? = null
        val projection = arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE)
        val cursor = runCatching {
            contentResolver.query(uri, projection, null, null, null)
        }.getOrNull()

        cursor.useIfNotNull {
            if (it.moveToFirst()) {
                displayName = it.stringOrNull(OpenableColumns.DISPLAY_NAME)
                sizeBytes = it.longOrNull(OpenableColumns.SIZE)
            }
        }
        return FileMetadata(displayName = displayName, sizeBytes = sizeBytes)
    }

    private fun Cursor.stringOrNull(columnName: String): String? {
        val index = getColumnIndex(columnName)
        if (index < 0 || isNull(index)) {
            return null
        }
        return getString(index)?.takeIf { it.isNotBlank() }
    }

    private fun Cursor.longOrNull(columnName: String): Long? {
        val index = getColumnIndex(columnName)
        if (index < 0 || isNull(index)) {
            return null
        }
        return getLong(index).takeIf { it >= 0 }
    }

    private inline fun Cursor?.useIfNotNull(block: (Cursor) -> Unit) {
        this?.use(block)
    }

    private data class FileMetadata(
        val displayName: String?,
        val sizeBytes: Long?,
    )
}

private class ContentUriRequestBody(
    private val contentResolver: ContentResolver,
    private val uri: Uri,
    private val mimeType: String?,
    private val sizeBytes: Long?,
) : RequestBody() {
    override fun contentType() = mimeType
        ?.lowercase(Locale.US)
        ?.toMediaTypeOrNull()

    override fun contentLength(): Long = sizeBytes ?: -1

    override fun writeTo(sink: BufferedSink) {
        val inputStream = contentResolver.openInputStream(uri)
            ?: throw IOException("无法读取所选文件。")
        inputStream.use { input ->
            sink.writeAll(input.source())
        }
    }
}
