"""Application-level exceptions exposed through the API layer."""

from __future__ import annotations

from http import HTTPStatus


class AITeachMeError(Exception):
    """Base class for user-facing business errors."""

    error_code: str = "AITEACHME_ERROR"
    status_code: int = HTTPStatus.INTERNAL_SERVER_ERROR

    def __init__(
        self,
        detail: str,
        *,
        error_code: str | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(detail)
        self.detail = detail
        if error_code is not None:
            self.error_code = error_code
        if status_code is not None:
            self.status_code = status_code


class InvalidSubjectError(AITeachMeError):
    error_code = "INVALID_SUBJECT"
    status_code = HTTPStatus.BAD_REQUEST

    def __init__(self, subject: str) -> None:
        super().__init__(
            detail=(
                f"Invalid subject slug '{subject}'. "
                "Only letters, numbers, underscores, and hyphens are allowed."
            )
        )


class SubjectNotFoundError(AITeachMeError):
    error_code = "SUBJECT_NOT_FOUND"
    status_code = HTTPStatus.NOT_FOUND

    def __init__(self, subject: str) -> None:
        super().__init__(detail=f"Subject '{subject}' was not found.")


class SubjectAlreadyExistsError(AITeachMeError):
    error_code = "SUBJECT_ALREADY_EXISTS"
    status_code = HTTPStatus.CONFLICT

    def __init__(self, subject: str) -> None:
        super().__init__(detail=f"Subject '{subject}' already exists.")


class SubjectRegistryNotFoundError(AITeachMeError):
    error_code = "SUBJECT_NOT_FOUND"
    status_code = HTTPStatus.NOT_FOUND

    def __init__(self, subject: str) -> None:
        super().__init__(detail=f"Subject '{subject}' was not found.")


class SubjectInUseError(AITeachMeError):
    error_code = "SUBJECT_IN_USE"
    status_code = HTTPStatus.CONFLICT

    def __init__(self, subject: str) -> None:
        super().__init__(detail=f"Subject '{subject}' still has related content and cannot be deleted.")


class FileParseError(AITeachMeError):
    error_code = "FILE_PARSE_ERROR"
    status_code = HTTPStatus.UNPROCESSABLE_ENTITY

    def __init__(self, filename: str, reason: str = "") -> None:
        detail = f"Failed to parse file '{filename}'."
        if reason:
            detail = f"{detail} {reason}"
        super().__init__(detail=detail)


class MissingLLMApiKeyError(AITeachMeError):
    error_code = "LLM_API_KEY_MISSING"
    status_code = HTTPStatus.SERVICE_UNAVAILABLE

    def __init__(self) -> None:
        super().__init__(detail="LLM_API_KEY is not configured.")


class FileTooLargeError(AITeachMeError):
    error_code = "FILE_TOO_LARGE"
    status_code = HTTPStatus.REQUEST_ENTITY_TOO_LARGE

    def __init__(self, max_size_mb: int) -> None:
        super().__init__(detail=f"Uploaded file exceeds the limit of {max_size_mb} MB.")


class UnsupportedFileTypeError(AITeachMeError):
    error_code = "UNSUPPORTED_FILE_TYPE"
    status_code = HTTPStatus.UNPROCESSABLE_ENTITY

    def __init__(self, filetype: str) -> None:
        super().__init__(detail=f"Unsupported file type '{filetype}'.")


class LLMCallError(AITeachMeError):
    error_code = "LLM_CALL_ERROR"
    status_code = HTTPStatus.BAD_GATEWAY

    def __init__(self, reason: str = "") -> None:
        detail = "The upstream LLM call failed."
        if reason:
            detail = f"{detail} {reason}"
        super().__init__(detail=detail)


class LLMTimeoutError(AITeachMeError):
    error_code = "LLM_TIMEOUT"
    status_code = HTTPStatus.GATEWAY_TIMEOUT

    def __init__(self, timeout_s: int = 60) -> None:
        super().__init__(detail=f"The upstream LLM call timed out after {timeout_s} seconds.")


class ExamNotFoundError(AITeachMeError):
    error_code = "EXAM_NOT_FOUND"
    status_code = HTTPStatus.NOT_FOUND

    def __init__(self, exam_id: int) -> None:
        super().__init__(detail=f"Exam {exam_id} was not found.")


class TaskNotFoundError(AITeachMeError):
    error_code = "TASK_NOT_FOUND"
    status_code = HTTPStatus.NOT_FOUND

    def __init__(self, task_id: int) -> None:
        super().__init__(detail=f"Task {task_id} was not found.")


class RawFileNotFoundError(AITeachMeError):
    error_code = "RAW_FILE_NOT_FOUND"
    status_code = HTTPStatus.NOT_FOUND

    def __init__(self, file_id: int) -> None:
        super().__init__(detail=f"Raw file {file_id} was not found.")


class DocSetNotFoundError(AITeachMeError):
    error_code = "DOC_SET_NOT_FOUND"
    status_code = HTTPStatus.NOT_FOUND

    def __init__(self, docset_id: int) -> None:
        super().__init__(detail=f"Document set {docset_id} was not found.")


class InvalidRawFileStateError(AITeachMeError):
    error_code = "INVALID_RAW_FILE_STATE"
    status_code = HTTPStatus.UNPROCESSABLE_ENTITY

    def __init__(self, file_id: int, current_state: str, expected: str) -> None:
        super().__init__(
            detail=(
                f"Raw file {file_id} is in state '{current_state}' but expected "
                f"'{expected}'."
            )
        )


class DigestPipelineError(AITeachMeError):
    error_code = "DIGEST_PIPELINE_ERROR"
    status_code = HTTPStatus.INTERNAL_SERVER_ERROR

    def __init__(self, document_id: int, stage: str = "", reason: str = "") -> None:
        detail = f"Digest pipeline failed for document {document_id}."
        if stage:
            detail = f"{detail} Stage: {stage}."
        if reason:
            detail = f"{detail} {reason}"
        super().__init__(detail=detail)


class VectorExtensionUnavailableError(AITeachMeError):
    error_code = "VECTOR_EXTENSION_UNAVAILABLE"
    status_code = HTTPStatus.SERVICE_UNAVAILABLE

    def __init__(self, reason: str = "") -> None:
        detail = "sqlite-vec is not available in the current environment."
        if reason:
            detail = f"{detail} {reason}"
        super().__init__(detail=detail)


class AuthDisabledError(AITeachMeError):
    error_code = "AUTH_DISABLED"
    status_code = HTTPStatus.SERVICE_UNAVAILABLE

    def __init__(self) -> None:
        super().__init__(detail="Authentication is disabled in local mode.")


class AuthNotReadyError(AITeachMeError):
    error_code = "AUTH_NOT_READY"
    status_code = HTTPStatus.SERVICE_UNAVAILABLE

    def __init__(self) -> None:
        super().__init__(detail="Cloud authentication scaffolding exists, but registration is not implemented yet.")
