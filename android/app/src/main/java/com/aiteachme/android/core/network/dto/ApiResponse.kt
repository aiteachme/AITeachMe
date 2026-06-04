package com.aiteachme.android.core.network.dto

import com.google.gson.annotations.SerializedName

data class ApiResponse<T>(
    val code: Int = -1,
    val message: String = "",
    val data: T? = null,
    @SerializedName("error_code")
    val errorCode: String? = null,
)
