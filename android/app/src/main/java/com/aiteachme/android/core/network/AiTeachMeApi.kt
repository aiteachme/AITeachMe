package com.aiteachme.android.core.network

import com.aiteachme.android.core.network.dto.ApiResponse
import com.aiteachme.android.core.network.dto.AuthSessionData
import com.aiteachme.android.core.network.dto.ChatListRequest
import com.aiteachme.android.core.network.dto.ChatMessageItem
import com.aiteachme.android.core.network.dto.ChatSessionCreateData
import com.aiteachme.android.core.network.dto.ChatSessionCreateRequest
import com.aiteachme.android.core.network.dto.ChatSessionDeleteData
import com.aiteachme.android.core.network.dto.ChatSessionDeleteRequest
import com.aiteachme.android.core.network.dto.ChatSessionItem
import com.aiteachme.android.core.network.dto.ChatSessionListRequest
import com.aiteachme.android.core.network.dto.CourseItem
import com.aiteachme.android.core.network.dto.DocGenBuildData
import com.aiteachme.android.core.network.dto.DocGenBuildRequest
import com.aiteachme.android.core.network.dto.DocGenGetResponse
import com.aiteachme.android.core.network.dto.FileDeleteData
import com.aiteachme.android.core.network.dto.FileDeleteRequest
import com.aiteachme.android.core.network.dto.FilesData
import com.aiteachme.android.core.network.dto.FilesUploadData
import com.aiteachme.android.core.network.dto.LoginRequest
import com.aiteachme.android.core.network.dto.LogoutRequest
import com.aiteachme.android.core.network.dto.PageRequest
import com.aiteachme.android.core.network.dto.PaginatedData
import com.aiteachme.android.core.network.dto.HealthData
import com.aiteachme.android.core.network.dto.RegisterRequest
import com.aiteachme.android.core.network.dto.SendEmailCodeData
import com.aiteachme.android.core.network.dto.SendEmailCodeRequest
import okhttp3.MultipartBody
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.Multipart
import retrofit2.http.Path
import retrofit2.http.POST
import retrofit2.http.Part
import retrofit2.http.Query

interface AiTeachMeApi {
    @GET("/api/health")
    suspend fun health(): ApiResponse<HealthData>

    @POST("/api/v1/courses/list")
    suspend fun listCourses(
        @Body request: PageRequest = PageRequest(),
    ): ApiResponse<PaginatedData<CourseItem>>

    @POST("/api/v1/courses/draft")
    suspend fun createDraftCourse(
        @Body request: Map<String, String> = emptyMap(),
    ): ApiResponse<CourseItem>

    @POST("/api/v1/auth/user")
    suspend fun currentUser(
        @Body request: LogoutRequest = LogoutRequest(),
    ): ApiResponse<AuthSessionData>

    @POST("/api/v1/auth/login")
    suspend fun login(
        @Body request: LoginRequest,
    ): ApiResponse<AuthSessionData>

    @POST("/api/v1/auth/register")
    suspend fun register(
        @Body request: RegisterRequest,
    ): ApiResponse<AuthSessionData>

    @POST("/api/v1/auth/email/send-code")
    suspend fun sendEmailCode(
        @Body request: SendEmailCodeRequest,
    ): ApiResponse<SendEmailCodeData>

    @POST("/api/v1/auth/logout")
    suspend fun logout(
        @Body request: LogoutRequest = LogoutRequest(),
    ): ApiResponse<AuthSessionData>

    @GET("/api/v1/files")
    suspend fun listUserFiles(
        @Query("file_ids") fileIds: List<String>? = null,
    ): ApiResponse<FilesData>

    @GET("/api/v1/courses/{course_id}/files")
    suspend fun listCourseFiles(
        @Path("course_id") courseId: String,
    ): ApiResponse<FilesData>

    @Multipart
    @POST("/api/v1/files/upload")
    suspend fun uploadUserFiles(
        @Part files: List<MultipartBody.Part>,
    ): ApiResponse<FilesUploadData>

    @POST("/api/v1/files/delete")
    suspend fun deleteUserFiles(
        @Body request: FileDeleteRequest,
    ): ApiResponse<FileDeleteData>

    @POST("/api/v1/chats/list")
    suspend fun listGlobalChatMessages(
        @Body request: ChatListRequest = ChatListRequest(),
    ): ApiResponse<PaginatedData<ChatMessageItem>>

    @POST("/api/v1/courses/{course_id}/chats/list")
    suspend fun listCourseChatMessages(
        @Path("course_id") courseId: String,
        @Body request: ChatListRequest = ChatListRequest(),
    ): ApiResponse<PaginatedData<ChatMessageItem>>

    @POST("/api/v1/chats/sessions/list")
    suspend fun listGlobalChatSessions(
        @Body request: ChatSessionListRequest = ChatSessionListRequest(),
    ): ApiResponse<PaginatedData<ChatSessionItem>>

    @POST("/api/v1/courses/{course_id}/chats/sessions/list")
    suspend fun listCourseChatSessions(
        @Path("course_id") courseId: String,
        @Body request: ChatSessionListRequest = ChatSessionListRequest(),
    ): ApiResponse<PaginatedData<ChatSessionItem>>

    @POST("/api/v1/chats/sessions/create")
    suspend fun createGlobalChatSession(
        @Body request: ChatSessionCreateRequest = ChatSessionCreateRequest(),
    ): ApiResponse<ChatSessionCreateData>

    @POST("/api/v1/courses/{course_id}/chats/sessions/create")
    suspend fun createCourseChatSession(
        @Path("course_id") courseId: String,
        @Body request: ChatSessionCreateRequest = ChatSessionCreateRequest(),
    ): ApiResponse<ChatSessionCreateData>

    @POST("/api/v1/chats/sessions/delete")
    suspend fun deleteGlobalChatSession(
        @Body request: ChatSessionDeleteRequest,
    ): ApiResponse<ChatSessionDeleteData>

    @POST("/api/v1/courses/{course_id}/chats/sessions/delete")
    suspend fun deleteCourseChatSession(
        @Path("course_id") courseId: String,
        @Body request: ChatSessionDeleteRequest,
    ): ApiResponse<ChatSessionDeleteData>

    @POST("/api/v1/courses/{course_id}/knowledge/docs")
    suspend fun getKnowledgeDocs(
        @Path("course_id") courseId: String,
        @Body request: Map<String, String> = emptyMap(),
    ): ApiResponse<DocGenGetResponse>

    @POST("/api/v1/courses/{course_id}/knowledge/build")
    suspend fun startKnowledgeBuild(
        @Path("course_id") courseId: String,
        @Body request: DocGenBuildRequest,
    ): ApiResponse<DocGenBuildData>
}
