package com.aiteachme.android.core.network

import com.aiteachme.android.core.network.dto.ApiResponse
import com.aiteachme.android.core.network.dto.HealthData
import retrofit2.http.GET

interface AiTeachMeApi {
    @GET("/api/health")
    suspend fun health(): ApiResponse<HealthData>
}
