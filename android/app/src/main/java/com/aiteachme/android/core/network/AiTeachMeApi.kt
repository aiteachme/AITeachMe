package com.aiteachme.android.core.network

import com.aiteachme.android.core.network.dto.*
import okhttp3.MultipartBody
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.Multipart
import retrofit2.http.PATCH
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

    @POST("/api/v1/courses/add")
    suspend fun createDraftCourse(
        @Body request: Map<String, String> = emptyMap(),
    ): ApiResponse<CourseItem>

    @POST("/api/v1/courses/delete/preview")
    suspend fun previewDeleteCourse(
        @Body request: CourseDeletePreviewRequest,
    ): ApiResponse<CourseDeletePreviewData>

    @POST("/api/v1/courses/delete")
    suspend fun deleteCourse(
        @Body request: CourseDeleteRequest,
    ): ApiResponse<CourseDeleteData>

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

    @Multipart
    @POST("/api/v1/courses/{course_id}/files/upload")
    suspend fun uploadCourseFiles(
        @Path("course_id") courseId: String,
        @Part files: List<MultipartBody.Part>,
    ): ApiResponse<FilesUploadData>

    @POST("/api/v1/courses/{course_id}/files/link")
    suspend fun linkCourseFiles(
        @Path("course_id") courseId: String,
        @Body request: CourseFilesLinkRequest,
    ): ApiResponse<FilesData>

    @POST("/api/v1/files/delete")
    suspend fun deleteUserFiles(
        @Body request: FileDeleteRequest,
    ): ApiResponse<FileDeleteData>

    @POST("/api/v1/courses/{course_id}/files/delete")
    suspend fun deleteCourseFiles(
        @Path("course_id") courseId: String,
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

    @POST("/api/v1/courses/{course_id}/knowledge/build/graph")
    suspend fun startKnowledgeGraphBuild(
        @Path("course_id") courseId: String,
        @Body request: Map<String, String> = emptyMap(),
    ): ApiResponse<KnowledgeGraphBuildData>

    @POST("/api/v1/courses/{course_id}/knowledge/build/cancel")
    suspend fun cancelKnowledgeBuild(
        @Path("course_id") courseId: String,
        @Body request: Map<String, String> = emptyMap(),
    ): ApiResponse<KnowledgeGraphBuildData>

    @POST("/api/v1/courses/{course_id}/knowledge/build/plans/{session_id}/confirm")
    suspend fun confirmBuildPlannerSession(
        @Path("course_id") courseId: String,
        @Path("session_id") sessionId: String,
        @Body request: Map<String, String> = emptyMap(),
    ): ApiResponse<BuildPlannerConfirmResponse>

    @POST("/api/v1/courses/{course_id}/knowledge/graph/full")
    suspend fun getKnowledgeGraph(
        @Path("course_id") courseId: String,
        @Body request: Map<String, String> = emptyMap(),
    ): ApiResponse<FullGraphResponse>

    @POST("/api/v1/courses/{course_id}/knowledge/overview")
    suspend fun getKnowledgeOverview(
        @Path("course_id") courseId: String,
        @Body request: KnowledgeOverviewRequest = KnowledgeOverviewRequest(),
    ): ApiResponse<KnowledgeOverviewResponse>

    @POST("/api/v1/courses/{course_id}/knowledge/clear")
    suspend fun clearKnowledge(
        @Path("course_id") courseId: String,
        @Body request: Map<String, String> = emptyMap(),
    ): ApiResponse<ClearKnowledgeResponse>

    @POST("/api/v1/courses/{course_id}/knowledge/graph/knowledge-units")
    suspend fun listKnowledgeUnits(
        @Path("course_id") courseId: String,
        @Body request: KnowledgeUnitsQueryRequest = KnowledgeUnitsQueryRequest(),
    ): ApiResponse<PaginatedData<KnowledgeUnitResponse>>

    @POST("/api/v1/courses/{course_id}/knowledge/graph/knowledge-units/detail")
    suspend fun getKnowledgeUnitDetail(
        @Path("course_id") courseId: String,
        @Body request: KnowledgeUnitDetailRequest,
    ): ApiResponse<KnowledgeUnitDetailResponse>

    @POST("/api/v1/courses/{course_id}/knowledge/graph/knowledge-units/relations")
    suspend fun getKnowledgeUnitRelations(
        @Path("course_id") courseId: String,
        @Body request: KnowledgeUnitRelationsRequest,
    ): ApiResponse<List<KnowledgeRelationResponse>>

    @POST("/api/v1/courses/{course_id}/knowledge/graph/knowledge-units/path")
    suspend fun getKnowledgeUnitPath(
        @Path("course_id") courseId: String,
        @Body request: KnowledgeUnitPathRequest,
    ): ApiResponse<KnowledgePathResponse>

    @POST("/api/v1/courses/{course_id}/knowledge/graph/subgraph")
    suspend fun getKnowledgeSubgraph(
        @Path("course_id") courseId: String,
        @Body request: KnowledgeSubgraphRequest = KnowledgeSubgraphRequest(),
    ): ApiResponse<KnowledgeSubgraphResponse>

    @POST("/api/v1/courses/{course_id}/knowledge/graph/relations/explain")
    suspend fun explainKnowledgeRelation(
        @Path("course_id") courseId: String,
        @Body request: KnowledgeRelationExplanationRequest,
    ): ApiResponse<KnowledgeRelationExplanationResponse>

    @POST("/api/v1/courses/{course_id}/exams/generate")
    suspend fun generateExam(
        @Path("course_id") courseId: String,
        @Body request: ExamGenerateRequest,
    ): ApiResponse<ExamGenerateResponse>

    @GET("/api/v1/courses/{course_id}/exams/history")
    suspend fun listExamHistory(
        @Path("course_id") courseId: String,
        @Query("page") page: Int = 1,
        @Query("size") size: Int = 20,
    ): ApiResponse<PaginatedData<ExamHistoryItem>>

    @GET("/api/v1/courses/{course_id}/exams/question-templates")
    suspend fun listQuestionTemplates(
        @Path("course_id") courseId: String,
    ): ApiResponse<List<QuestionTemplateItemResponse>>

    @GET("/api/v1/courses/{course_id}/exams/question-templates/{question_template_id}/answer-history")
    suspend fun listQuestionTemplateAnswerHistory(
        @Path("course_id") courseId: String,
        @Path("question_template_id") questionTemplateId: Int,
        @Query("page") page: Int = 1,
        @Query("size") size: Int = 20,
    ): ApiResponse<List<QuestionTemplateAnswerHistoryItem>>

    @PATCH("/api/v1/courses/{course_id}/exams/question-templates/{question_template_id}/mark")
    suspend fun markQuestionTemplate(
        @Path("course_id") courseId: String,
        @Path("question_template_id") questionTemplateId: Int,
        @Body request: QuestionTemplateMarkRequest,
    ): ApiResponse<QuestionTemplateMarkResponse>

    @GET("/api/v1/courses/{course_id}/exams/question-types")
    suspend fun listQuestionTypes(
        @Path("course_id") courseId: String,
    ): ApiResponse<List<QuestionTypeRegistryItemResponse>>

    @GET("/api/v1/courses/{course_id}/exams/{exam_paper_id}")
    suspend fun getExamDetail(
        @Path("course_id") courseId: String,
        @Path("exam_paper_id") examPaperId: Int,
    ): ApiResponse<ExamPaperDetailResponse>

    @POST("/api/v1/courses/{course_id}/exams/{exam_paper_id}/submit")
    suspend fun submitExam(
        @Path("course_id") courseId: String,
        @Path("exam_paper_id") examPaperId: Int,
        @Body request: ExamSubmitRequest,
    ): ApiResponse<ExamGradeResponse>

    @GET("/api/v1/courses/{course_id}/exams/{exam_paper_id}/study-guide")
    suspend fun getExamStudyGuide(
        @Path("course_id") courseId: String,
        @Path("exam_paper_id") examPaperId: Int,
    ): ApiResponse<ExamStudyGuideResponse>

    @GET("/api/v1/courses/{course_id}/profile/mastery")
    suspend fun getMasteryOverview(
        @Path("course_id") courseId: String,
    ): ApiResponse<MasteryOverviewResponse>

    @GET("/api/v1/courses/{course_id}/profile/study-plan")
    suspend fun getStudyPlan(
        @Path("course_id") courseId: String,
    ): ApiResponse<List<StudyPlanStepResponse>>

    @GET("/api/v1/courses/{course_id}/profile/reviews")
    suspend fun listReviewTasks(
        @Path("course_id") courseId: String,
    ): ApiResponse<List<ReviewTaskResponse>>

    @POST("/api/v1/courses/{course_id}/profile/reviews/{task_id}/complete")
    suspend fun completeReviewTask(
        @Path("course_id") courseId: String,
        @Path("task_id") taskId: Int,
        @Body request: Map<String, String> = emptyMap(),
    ): ApiResponse<ReviewTaskResponse>

    @POST("/api/v1/system/settings")
    suspend fun getSystemSettings(
        @Body request: InitRequest = InitRequest(),
    ): ApiResponse<SettingsOverviewData>

    @PATCH("/api/v1/system/settings")
    suspend fun updateSystemSettings(
        @Body request: UpdateUserSettingsRequest,
    ): ApiResponse<SettingsOverviewData>

    @POST("/api/v1/system/feedback")
    suspend fun submitFeedback(
        @Body request: FeedbackSubmitRequest,
    ): ApiResponse<FeedbackSubmitResponse>
}
