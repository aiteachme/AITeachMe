"""项目统一异常定义。"""

from __future__ import annotations

from http import HTTPStatus
from typing import Any


class AITeachMeError(Exception):
    """所有对外业务异常的基类。"""

    error_code: str = "AITEACHME_ERROR"
    status_code: int = HTTPStatus.INTERNAL_SERVER_ERROR

    def __init__(
        self,
        detail: str,
        *,
        error_code: str | None = None,
        status_code: int | None = None,
        data: Any | None = None,
    ) -> None:
        super().__init__(detail)
        self.detail = detail
        self.data = data
        if error_code is not None:
            self.error_code = error_code
        if status_code is not None:
            self.status_code = status_code


class KnowledgeChunkNotFoundError(AITeachMeError):
    error_code = "KNOWLEDGE_CHUNK_NOT_FOUND"
    status_code = HTTPStatus.NOT_FOUND

    def __init__(self, chunk_id: int) -> None:
        super().__init__(detail=f"知识切块 `{chunk_id}` 不存在。")


class InvalidSubjectError(AITeachMeError):
    error_code = "INVALID_SUBJECT"
    status_code = HTTPStatus.BAD_REQUEST

    def __init__(self, subject_id: str) -> None:
        super().__init__(
            detail=f"学科标识 `{subject_id}` 不合法，只允许字母、数字、下划线和中划线。"
        )


class SubjectAlreadyExistsError(AITeachMeError):
    error_code = "SUBJECT_ALREADY_EXISTS"
    status_code = HTTPStatus.CONFLICT

    def __init__(self, subject_id: str) -> None:
        super().__init__(detail=f"学科 `{subject_id}` 已存在。")


class SubjectRegistryNotFoundError(AITeachMeError):
    error_code = "SUBJECT_NOT_FOUND"
    status_code = HTTPStatus.NOT_FOUND

    def __init__(self, subject_id: str) -> None:
        super().__init__(detail=f"学科 `{subject_id}` 不存在。")


class SubjectInUseError(AITeachMeError):
    error_code = "SUBJECT_IN_USE"
    status_code = HTTPStatus.CONFLICT

    def __init__(self, subject_id: str) -> None:
        super().__init__(detail=f"学科 `{subject_id}` 下仍有内容，不能删除。")


class KnowledgeClearConflictError(AITeachMeError):
    error_code = "KNOWLEDGE_CLEAR_CONFLICT"
    status_code = HTTPStatus.CONFLICT

    def __init__(self, subject_id: str, blocking_details: str) -> None:
        super().__init__(
            detail=(
                f"学科 `{subject_id}` 仍有关联的考试、画像或对话数据，"
                f"暂不能直接清空知识。阻塞项：{blocking_details}。"
            )
        )


class FileParseError(AITeachMeError):
    error_code = "FILE_PARSE_ERROR"
    status_code = HTTPStatus.UNPROCESSABLE_ENTITY

    def __init__(self, filename: str, reason: str = "") -> None:
        detail = f"文件 `{filename}` 解析失败。"
        if reason:
            detail = f"{detail}{reason}"
        super().__init__(detail=detail)


class FileTooLargeError(AITeachMeError):
    error_code = "FILE_TOO_LARGE"
    status_code = HTTPStatus.REQUEST_ENTITY_TOO_LARGE

    def __init__(self, max_size_mb: int) -> None:
        super().__init__(detail=f"上传文件超过 {max_size_mb} MB 限制。")


class FileCountLimitError(AITeachMeError):
    error_code = "FILE_COUNT_LIMIT_EXCEEDED"
    status_code = HTTPStatus.REQUEST_ENTITY_TOO_LARGE

    def __init__(self, max_files: int) -> None:
        super().__init__(detail=f"单次最多上传 {max_files} 个文件。")


class UnsupportedFileTypeError(AITeachMeError):
    error_code = "UNSUPPORTED_FILE_TYPE"
    status_code = HTTPStatus.UNPROCESSABLE_ENTITY

    def __init__(self, filetype: str) -> None:
        super().__init__(detail=f"暂不支持文件类型 `{filetype}`。")


class InvalidImportPackageError(AITeachMeError):
    error_code = "INVALID_IMPORT_PACKAGE"
    status_code = HTTPStatus.UNPROCESSABLE_ENTITY

    def __init__(self, reason: str = "") -> None:
        detail = "导入课程包格式不正确。"
        if reason:
            detail = f"{detail}{reason}"
        super().__init__(detail=detail)


class ImportPackageTooLargeError(AITeachMeError):
    error_code = "IMPORT_PACKAGE_TOO_LARGE"
    status_code = HTTPStatus.REQUEST_ENTITY_TOO_LARGE

    def __init__(self, max_size_mb: int) -> None:
        super().__init__(detail=f"导入课程包超过 {max_size_mb} MB 限制。")


class RawFileNotFoundError(AITeachMeError):
    error_code = "RAW_FILE_NOT_FOUND"
    status_code = HTTPStatus.NOT_FOUND

    def __init__(self, file_id: int | str) -> None:
        super().__init__(detail=f"文件 `{file_id}` 不存在。")


class RawFileInUseError(AITeachMeError):
    error_code = "RAW_FILE_IN_USE"
    status_code = HTTPStatus.CONFLICT

    def __init__(self, file_uid: str, linked_subjects: list[dict[str, str]]) -> None:
        super().__init__(
            detail=f"文件 `{file_uid}` 仍被学科引用，不能从资料库删除。",
            data={"file_uid": file_uid, "linked_subjects": linked_subjects},
        )


class DemoCourseCatalogNotConfiguredError(AITeachMeError):
    error_code = "DEMO_COURSE_CATALOG_NOT_CONFIGURED"
    status_code = HTTPStatus.SERVICE_UNAVAILABLE

    def __init__(self) -> None:
        super().__init__(
            detail=(
                "当前发行版未配置演示课程目录。"
                "演示课程由部署侧统一发布到公共对象存储后提供。"
            )
        )


class DemoCourseCatalogUnavailableError(AITeachMeError):
    error_code = "DEMO_COURSE_CATALOG_UNAVAILABLE"
    status_code = HTTPStatus.BAD_GATEWAY

    def __init__(self, reason: str = "") -> None:
        detail = "演示课程目录当前不可用。"
        if reason:
            detail = f"{detail}{reason}"
        super().__init__(detail=detail)


class DemoCoursePackageNotFoundError(AITeachMeError):
    error_code = "DEMO_COURSE_PACKAGE_NOT_FOUND"
    status_code = HTTPStatus.NOT_FOUND

    def __init__(self, course_id: str) -> None:
        super().__init__(detail=f"演示课程 `{course_id}` 不存在。")


class InvalidRawFileStateError(AITeachMeError):
    error_code = "INVALID_RAW_FILE_STATE"
    status_code = HTTPStatus.UNPROCESSABLE_ENTITY

    def __init__(self, file_id: int | str, current_state: str, expected: str) -> None:
        super().__init__(
            detail=f"文件 `{file_id}` 当前状态为 `{current_state}`，期望状态为 `{expected}`。"
        )


class ExamNotFoundError(AITeachMeError):
    error_code = "EXAM_NOT_FOUND"
    status_code = HTTPStatus.NOT_FOUND

    def __init__(self, exam_id: int) -> None:
        super().__init__(detail=f"试卷 `{exam_id}` 不存在。")


class MissingLLMApiKeyError(AITeachMeError):
    error_code = "LLM_API_KEY_MISSING"
    status_code = HTTPStatus.SERVICE_UNAVAILABLE

    def __init__(self, *, provider: str | None = None, base_url_configured: bool | None = None) -> None:
        hints: list[str] = []
        if provider:
            hints.append(f"当前推断模型供应商为 {provider}")
        if base_url_configured is False:
            hints.append("LLM_BASE_URL 未配置")
        if hints:
            super().__init__(detail=f"未配置 LLM_API_KEY（{'，'.join(hints)}）。")
        else:
            super().__init__(detail="未配置 LLM_API_KEY。")


class LLMCallError(AITeachMeError):
    error_code = "LLM_CALL_ERROR"
    status_code = HTTPStatus.BAD_GATEWAY

    def __init__(self, reason: str = "") -> None:
        detail = "上游模型调用失败。"
        if reason:
            detail = f"{detail}{reason}"
        super().__init__(detail=detail)


class LLMTimeoutError(AITeachMeError):
    error_code = "LLM_TIMEOUT"
    status_code = HTTPStatus.GATEWAY_TIMEOUT

    def __init__(self, timeout_s: int = 60) -> None:
        super().__init__(detail=f"上游模型调用超时，超过 {timeout_s} 秒。")


class VectorExtensionUnavailableError(AITeachMeError):
    error_code = "VECTOR_EXTENSION_UNAVAILABLE"
    status_code = HTTPStatus.SERVICE_UNAVAILABLE

    def __init__(self, reason: str = "") -> None:
        detail = "当前环境不可用 sqlite-vec。"
        if reason:
            detail = f"{detail}{reason}"
        super().__init__(detail=detail)


class AuthDisabledError(AITeachMeError):
    error_code = "AUTH_DISABLED"
    status_code = HTTPStatus.SERVICE_UNAVAILABLE

    def __init__(self) -> None:
        super().__init__(detail="当前运行模式未启用账号鉴权。")


class AuthNotReadyError(AITeachMeError):
    error_code = "AUTH_NOT_READY"
    status_code = HTTPStatus.SERVICE_UNAVAILABLE

    def __init__(self, detail: str = "鉴权配置尚未就绪。") -> None:
        super().__init__(detail=detail)


# ── 知识图谱增量构建 + 多视图课程结构派生 ──


class DigestJobNotFoundError(AITeachMeError):
    error_code = "DIGEST_JOB_NOT_FOUND"
    status_code = HTTPStatus.NOT_FOUND

    def __init__(self, job_id: int) -> None:
        super().__init__(detail=f"增量构建任务 `{job_id}` 不存在。")


class KnowledgeUnitNotFoundError(AITeachMeError):
    error_code = "KNOWLEDGE_UNIT_NOT_FOUND"
    status_code = HTTPStatus.NOT_FOUND

    def __init__(self, knowledge_unit_id: int) -> None:
        super().__init__(detail=f"知识单元 `{knowledge_unit_id}` 不存在。")


class NoReadyFilesForDocGenError(AITeachMeError):
    error_code = "NO_READY_FILES_FOR_DOCGEN"
    status_code = HTTPStatus.UNPROCESSABLE_ENTITY

    def __init__(self, subject_id: str) -> None:
        super().__init__(detail=f"学科 `{subject_id}` 暂无可用的已解析文件，无法开始知识构建。")


class ConfirmedBuildPlanRequiredError(AITeachMeError):
    error_code = "CONFIRMED_BUILD_PLAN_REQUIRED"
    status_code = HTTPStatus.UNPROCESSABLE_ENTITY

    def __init__(self, build_type: str) -> None:
        build_label = {
            "docs": "知识文档构建",
        }.get(build_type, "当前构建")
        super().__init__(detail=f"{build_label}必须基于已确认的构建方案执行，请先完成 planner 确认。")


class SubjectBuildLockConflictError(AITeachMeError):
    error_code = "BUILD_IN_PROGRESS"
    status_code = HTTPStatus.CONFLICT

    def __init__(self, subject_id: str) -> None:
        super().__init__(detail=f"学科 `{subject_id}` 正在构建中，请稍后重试。")


class KnowledgeBuildPrecheckConflictError(AITeachMeError):
    error_code = "KNOWLEDGE_BUILD_PRECHECK_CONFLICT"
    status_code = HTTPStatus.CONFLICT

    def __init__(self, detail: str, *, data: Any | None = None) -> None:
        super().__init__(detail=detail, data=data)


class EvidenceNotFoundError(AITeachMeError):
    error_code = "EVIDENCE_NOT_FOUND"
    status_code = HTTPStatus.NOT_FOUND

    def __init__(self, evidence_id: int) -> None:
        super().__init__(detail=f"证据 #{evidence_id} 不存在。")


class BuildPlannerSessionNotFoundError(AITeachMeError):
    error_code = "BUILD_PLANNER_SESSION_NOT_FOUND"
    status_code = HTTPStatus.NOT_FOUND

    def __init__(self, session_id: str) -> None:
        super().__init__(detail=f"构建方案会话 `{session_id}` 不存在。")


class BuildPlannerSessionBusyError(AITeachMeError):
    error_code = "BUILD_PLANNER_SESSION_BUSY"
    status_code = HTTPStatus.CONFLICT

    def __init__(self, session_id: str = "") -> None:
        detail = "上一轮方案生成仍在进行中，请先停止当前生成或等待完成。"
        if session_id:
            detail = f"构建方案会话 `{session_id}` 的上一轮生成仍在进行中，请先停止当前生成或等待完成。"
        super().__init__(detail=detail)


class ConfirmedBuildPlanNotFoundError(AITeachMeError):
    error_code = "CONFIRMED_BUILD_PLAN_NOT_FOUND"
    status_code = HTTPStatus.NOT_FOUND

    def __init__(self, plan_id: str) -> None:
        super().__init__(detail=f"已确认构建方案 `{plan_id}` 不存在。")


class BuildPlannerEmptyPlanError(AITeachMeError):
    error_code = "BUILD_PLANNER_EMPTY_PLAN"
    status_code = HTTPStatus.UNPROCESSABLE_ENTITY

    def __init__(self, session_id: str) -> None:
        super().__init__(detail=f"构建方案会话 `{session_id}` 当前没有可确认的方案草稿。")


class PlannerMaterialsNotReadyError(AITeachMeError):
    error_code = "PLANNER_MATERIALS_NOT_READY"
    status_code = HTTPStatus.CONFLICT

    def __init__(self, subject_id: str) -> None:
        super().__init__(detail=f"学科 `{subject_id}` 的资料正文仍在解析中，请等待至少一份资料完成解析后再生成构建方案。")
