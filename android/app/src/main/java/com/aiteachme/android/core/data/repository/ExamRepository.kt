package com.aiteachme.android.core.data.repository

import com.aiteachme.android.core.network.AiTeachMeApi
import com.aiteachme.android.core.network.dto.ApiResponse
import com.aiteachme.android.core.network.dto.ExamGenerateRequest
import com.aiteachme.android.core.network.dto.ExamGenerateResponse
import com.aiteachme.android.core.network.dto.ExamGradeResponse
import com.aiteachme.android.core.network.dto.ExamHistoryItem
import com.aiteachme.android.core.network.dto.ExamPaperDetailResponse
import com.aiteachme.android.core.network.dto.ExamStudyGuideResponse
import com.aiteachme.android.core.network.dto.ExamSubmitRequest
import com.aiteachme.android.core.network.dto.QuestionTemplateAnswerHistoryItem
import com.aiteachme.android.core.network.dto.QuestionTemplateItemResponse
import com.aiteachme.android.core.network.dto.QuestionTemplateMarkRequest
import com.aiteachme.android.core.network.dto.QuestionTemplateMarkResponse
import com.aiteachme.android.core.network.dto.QuestionTypeRegistryItemResponse

class ExamRepository(
    private val api: AiTeachMeApi,
) {
    suspend fun generateExam(
        courseId: String,
        request: ExamGenerateRequest,
    ): ExamGenerateResponse {
        return api.generateExam(courseId = courseId, request = request)
            .requireData("试卷生成失败")
    }

    suspend fun listHistory(
        courseId: String,
        page: Int = 1,
        size: Int = 20,
    ): List<ExamHistoryItem> {
        return api.listExamHistory(courseId = courseId, page = page, size = size)
            .requireData("考试历史加载失败")
            .items
    }

    suspend fun listQuestionTemplates(courseId: String): List<QuestionTemplateItemResponse> {
        return api.listQuestionTemplates(courseId = courseId)
            .requireData("题库模板加载失败")
    }

    suspend fun listQuestionTemplateAnswerHistory(
        courseId: String,
        questionTemplateId: Int,
        page: Int = 1,
        size: Int = 20,
    ): List<QuestionTemplateAnswerHistoryItem> {
        return api.listQuestionTemplateAnswerHistory(
            courseId = courseId,
            questionTemplateId = questionTemplateId,
            page = page,
            size = size,
        ).requireData("题目答题历史加载失败")
    }

    suspend fun markQuestionTemplate(
        courseId: String,
        questionTemplateId: Int,
        isMarked: Boolean,
    ): QuestionTemplateMarkResponse {
        return api.markQuestionTemplate(
            courseId = courseId,
            questionTemplateId = questionTemplateId,
            request = QuestionTemplateMarkRequest(isMarked = isMarked),
        ).requireData("题目标记失败")
    }

    suspend fun listQuestionTypes(courseId: String): List<QuestionTypeRegistryItemResponse> {
        return api.listQuestionTypes(courseId = courseId)
            .requireData("题型注册表加载失败")
    }

    suspend fun getExamDetail(
        courseId: String,
        examPaperId: Int,
    ): ExamPaperDetailResponse {
        return api.getExamDetail(courseId = courseId, examPaperId = examPaperId)
            .requireData("试卷详情加载失败")
    }

    suspend fun submitExam(
        courseId: String,
        examPaperId: Int,
        request: ExamSubmitRequest,
    ): ExamGradeResponse {
        return api.submitExam(courseId = courseId, examPaperId = examPaperId, request = request)
            .requireData("提交批改失败")
    }

    suspend fun getStudyGuide(
        courseId: String,
        examPaperId: Int,
    ): ExamStudyGuideResponse {
        return api.getExamStudyGuide(courseId = courseId, examPaperId = examPaperId)
            .requireData("学习指南加载失败")
    }

    private fun <T> ApiResponse<T>.requireData(fallbackMessage: String): T {
        if (code != 0) {
            throw IllegalStateException(message.ifBlank { fallbackMessage })
        }
        return data ?: throw IllegalStateException(message.ifBlank { fallbackMessage })
    }
}
