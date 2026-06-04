package com.aiteachme.android.core.network.dto

import com.google.gson.annotations.SerializedName

data class InitRequest(
    val mode: String? = null,
)

data class SettingEntry(
    val key: String = "",
    val label: String = "",
    val value: Any? = null,
    val source: String = "",
    val sensitive: Boolean = false,
    val editable: Boolean = false,
    val description: String = "",
)

data class SettingSection(
    val key: String = "",
    val title: String = "",
    val entries: List<SettingEntry> = emptyList(),
)

data class SettingsOverviewData(
    @SerializedName("settings_source")
    val settingsSource: String = "",
    @SerializedName("env_source")
    val envSource: String = "",
    val sections: List<SettingSection> = emptyList(),
)

data class UpdateUserSettingsRequest(
    val settings: Map<String, Any?>? = null,
    val env: Map<String, String?>? = null,
)

data class FeedbackSubmitRequest(
    val content: String,
    val scene: String = "android",
    val contact: String? = null,
)

data class FeedbackSubmitResponse(
    val accepted: Boolean = false,
    val id: String = "",
)
