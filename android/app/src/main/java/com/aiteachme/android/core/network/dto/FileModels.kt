package com.aiteachme.android.core.network.dto

import com.google.gson.annotations.SerializedName

data class FileAssetItem(
    val name: String = "",
    val url: String = "",
    @SerializedName("mime_type")
    val mimeType: String? = null,
    @SerializedName("asset_kind")
    val assetKind: String? = null,
    @SerializedName("page_num")
    val pageNum: Int? = null,
    val width: Int? = null,
    val height: Int? = null,
    @SerializedName("ocr_text")
    val ocrText: String? = null,
)

data class FileRecord(
    val id: String = "",
    val filename: String = "",
    val filetype: String = "",
    val status: String = "",
    @SerializedName("ingest_status")
    val ingestStatus: String = "",
    @SerializedName("markdown_ready")
    val markdownReady: Boolean = false,
    @SerializedName("asset_ready")
    val assetReady: Boolean = false,
    @SerializedName("error_message")
    val errorMessage: String? = null,
    @SerializedName("file_size_bytes")
    val fileSizeBytes: Long? = null,
    @SerializedName("detected_language")
    val detectedLanguage: String? = null,
    @SerializedName("estimated_pages")
    val estimatedPages: Int? = null,
    @SerializedName("image_count")
    val imageCount: Int? = null,
    @SerializedName("parser_used")
    val parserUsed: String? = null,
    @SerializedName("markdown_content")
    val markdownContent: String = "",
    @SerializedName("asset_base_url")
    val assetBaseUrl: String? = null,
    val assets: List<FileAssetItem> = emptyList(),
    @SerializedName("classification_json")
    val classificationJson: String? = null,
    @SerializedName("quality_score")
    val qualityScore: Double? = null,
    @SerializedName("digest_current_step")
    val digestCurrentStep: String? = null,
    @SerializedName("parse_metadata_json")
    val parseMetadataJson: String? = null,
    @SerializedName("latest_updated_at")
    val latestUpdatedAt: String = "",
    @SerializedName("created_at")
    val createdAt: String = "",
)

data class FilesData(
    @SerializedName("course_id")
    val courseId: String? = null,
    val total: Int = 0,
    @SerializedName("ready_count")
    val readyCount: Int = 0,
    @SerializedName("processing_count")
    val processingCount: Int = 0,
    @SerializedName("failed_count")
    val failedCount: Int = 0,
    val items: List<FileRecord> = emptyList(),
)

data class FilesUploadData(
    @SerializedName("course_id")
    val courseId: String? = null,
    val filenames: List<String> = emptyList(),
    @SerializedName("uploaded_items")
    val uploadedItems: List<FileRecord> = emptyList(),
    @SerializedName("started_parse_count")
    val startedParseCount: Int = 0,
)

data class FileDeleteRequest(
    @SerializedName("file_id")
    val fileId: String? = null,
    @SerializedName("file_ids")
    val fileIds: List<String>? = null,
)

data class FileDeleteData(
    @SerializedName("deleted_file_ids")
    val deletedFileIds: List<String> = emptyList(),
)
