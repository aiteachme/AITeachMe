"""
统一业务异常体系

所有业务异常继承自 AITeachMeError，包含 error_code 和 status_code。
API 层捕获后返回标准 JSON 错误响应：{"detail": "...", "error_code": "..."}
"""

from http import HTTPStatus


class AITeachMeError(Exception):
    """业务异常基类"""

    error_code: str = "AITEACHME_ERROR"
    status_code: int = HTTPStatus.INTERNAL_SERVER_ERROR

    def __init__(self, detail: str, error_code: str | None = None, status_code: int | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        if error_code is not None:
            self.error_code = error_code
        if status_code is not None:
            self.status_code = status_code


class InvalidSubjectError(AITeachMeError):
    """学科名称不合法（不符合 [a-zA-Z0-9_-]{1,64} 规则）"""

    error_code = "INVALID_SUBJECT"
    status_code = HTTPStatus.BAD_REQUEST

    def __init__(self, subject: str) -> None:
        super().__init__(
            detail=f"无效的学科名称：'{subject}'，仅允许字母、数字、下划线和连字符，长度 1~64",
        )


class SubjectNotFoundError(AITeachMeError):
    """学科不存在"""

    error_code = "SUBJECT_NOT_FOUND"
    status_code = HTTPStatus.NOT_FOUND

    def __init__(self, subject: str) -> None:
        super().__init__(detail=f"学科 '{subject}' 不存在")


class FileParseError(AITeachMeError):
    """文件解析失败"""

    error_code = "FILE_PARSE_ERROR"
    status_code = HTTPStatus.UNPROCESSABLE_ENTITY

    def __init__(self, filename: str, reason: str = "") -> None:
        detail = f"文件 '{filename}' 解析失败"
        if reason:
            detail += f"：{reason}"
        super().__init__(detail=detail)


class MissingLLMApiKeyError(AITeachMeError):
    """LLM API Key 未配置"""

    error_code = "LLM_API_KEY_MISSING"
    status_code = HTTPStatus.SERVICE_UNAVAILABLE

    def __init__(self) -> None:
        super().__init__(detail="未配置 LLM_API_KEY，当前功能需要先配置该密钥后才能使用")


class FileTooLargeError(AITeachMeError):
    """上传文件超过大小限制"""

    error_code = "FILE_TOO_LARGE"
    status_code = HTTPStatus.REQUEST_ENTITY_TOO_LARGE

    def __init__(self, max_size_mb: int) -> None:
        super().__init__(detail=f"文件大小超过限制（最大 {max_size_mb}MB）")


class UnsupportedFileTypeError(AITeachMeError):
    """不支持的文件类型"""

    error_code = "UNSUPPORTED_FILE_TYPE"
    status_code = HTTPStatus.UNPROCESSABLE_ENTITY

    def __init__(self, filetype: str) -> None:
        super().__init__(detail=f"不支持的文件类型：'{filetype}'")


class LLMCallError(AITeachMeError):
    """LLM 调用失败"""

    error_code = "LLM_CALL_ERROR"
    status_code = HTTPStatus.BAD_GATEWAY

    def __init__(self, reason: str = "") -> None:
        detail = "LLM 调用失败"
        if reason:
            detail += f"：{reason}"
        super().__init__(detail=detail)


class LLMTimeoutError(AITeachMeError):
    """LLM 调用超时"""

    error_code = "LLM_TIMEOUT"
    status_code = HTTPStatus.GATEWAY_TIMEOUT

    def __init__(self, timeout_s: int = 60) -> None:
        super().__init__(detail=f"LLM 调用超时（超过 {timeout_s} 秒）")


class ExamNotFoundError(AITeachMeError):
    """考卷不存在"""

    error_code = "EXAM_NOT_FOUND"
    status_code = HTTPStatus.NOT_FOUND

    def __init__(self, exam_id: int) -> None:
        super().__init__(detail=f"考卷 ID {exam_id} 不存在")


class TaskNotFoundError(AITeachMeError):
    """任务（上传流水线）不存在"""

    error_code = "TASK_NOT_FOUND"
    status_code = HTTPStatus.NOT_FOUND

    def __init__(self, task_id: int) -> None:
        super().__init__(detail=f"任务 ID {task_id} 不存在")


class DigestPipelineError(AITeachMeError):
    """Digest 流水线处理失败"""

    error_code = "DIGEST_PIPELINE_ERROR"
    status_code = HTTPStatus.INTERNAL_SERVER_ERROR

    def __init__(self, knowledge_id: int, stage: str = "", reason: str = "") -> None:
        detail = f"知识文档 ID {knowledge_id} 消化索引失败"
        if stage:
            detail += f"（阶段：{stage}）"
        if reason:
            detail += f"：{reason}"
        super().__init__(detail=detail)
