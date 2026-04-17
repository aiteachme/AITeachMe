"""Shared domain exception definitions."""

from __future__ import annotations

from http import HTTPStatus
from typing import Any


class AITeachMeError(Exception):
    """Base class for business-facing errors."""

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
        super().__init__(detail=f"Knowledge chunk `{chunk_id}` does not exist.")


class InvalidSubjectError(AITeachMeError):
    error_code = "INVALID_SUBJECT"
    status_code = HTTPStatus.BAD_REQUEST

    def __init__(self, subject: str) -> None:
        super().__init__(detail=f"Subject slug `{subject}` is invalid.")


class SubjectAlreadyExistsError(AITeachMeError):
    error_code = "SUBJECT_ALREADY_EXISTS"
    status_code = HTTPStatus.CONFLICT

    def __init__(self, subject: str) -> None:
        super().__init__(detail=f"Subject `{subject}` already exists.")


class SubjectRegistryNotFoundError(AITeachMeError):
    error_code = "SUBJECT_NOT_FOUND"
    status_code = HTTPStatus.NOT_FOUND

    def __init__(self, subject: str) -> None:
        super().__init__(detail=f"Subject `{subject}` does not exist.")


class SubjectInUseError(AITeachMeError):
    error_code = "SUBJECT_IN_USE"
    status_code = HTTPStatus.CONFLICT

    def __init__(self, subject: str) -> None:
        super().__init__(detail=f"Subject `{subject}` still has content.")


class KnowledgeClearConflictError(AITeachMeError):
    error_code = "KNOWLEDGE_CLEAR_CONFLICT"
    status_code = HTTPStatus.CONFLICT

    def __init__(self, subject: str, blocking_details: str) -> None:
        super().__init__(
            detail=f"Subject `{subject}` still has linked data and cannot be cleared: {blocking_details}.",
        )


class FileParseError(AITeachMeError):
    error_code = "FILE_PARSE_ERROR"
    status_code = HTTPStatus.UNPROCESSABLE_ENTITY

    def __init__(self, filename: str, reason: str = "") -> None:
        suffix = f" {reason}" if reason else ""
        super().__init__(detail=f"Failed to parse file `{filename}`.{suffix}")


class FileTooLargeError(AITeachMeError):
    error_code = "FILE_TOO_LARGE"
    status_code = HTTPStatus.REQUEST_ENTITY_TOO_LARGE

    def __init__(self, max_size_mb: int) -> None:
        super().__init__(detail=f"Uploaded file exceeds the {max_size_mb} MB limit.")


class UnsupportedFileTypeError(AITeachMeError):
    error_code = "UNSUPPORTED_FILE_TYPE"
    status_code = HTTPStatus.UNPROCESSABLE_ENTITY

    def __init__(self, filetype: str) -> None:
        super().__init__(detail=f"Unsupported file type `{filetype}`.")


class RawFileNotFoundError(AITeachMeError):
    error_code = "RAW_FILE_NOT_FOUND"
    status_code = HTTPStatus.NOT_FOUND

    def __init__(self, file_id: int | str) -> None:
        super().__init__(detail=f"Raw file `{file_id}` does not exist.")


class InvalidRawFileStateError(AITeachMeError):
    error_code = "INVALID_RAW_FILE_STATE"
    status_code = HTTPStatus.UNPROCESSABLE_ENTITY

    def __init__(self, file_id: int | str, current_state: str, expected: str) -> None:
        super().__init__(
            detail=f"Raw file `{file_id}` is in state `{current_state}`, expected `{expected}`.",
        )


class ExamNotFoundError(AITeachMeError):
    error_code = "EXAM_NOT_FOUND"
    status_code = HTTPStatus.NOT_FOUND

    def __init__(self, exam_id: int) -> None:
        super().__init__(detail=f"Exam `{exam_id}` does not exist.")


class MissingLLMApiKeyError(AITeachMeError):
    error_code = "LLM_API_KEY_MISSING"
    status_code = HTTPStatus.SERVICE_UNAVAILABLE

    def __init__(self) -> None:
        super().__init__(detail="LLM_API_KEY is not configured.")


class LLMCallError(AITeachMeError):
    error_code = "LLM_CALL_ERROR"
    status_code = HTTPStatus.BAD_GATEWAY

    def __init__(self, reason: str = "") -> None:
        suffix = f" {reason}" if reason else ""
        super().__init__(detail=f"Upstream model call failed.{suffix}")


class LLMTimeoutError(AITeachMeError):
    error_code = "LLM_TIMEOUT"
    status_code = HTTPStatus.GATEWAY_TIMEOUT

    def __init__(self, timeout_s: int = 60) -> None:
        super().__init__(detail=f"Upstream model call timed out after {timeout_s} seconds.")


class VectorExtensionUnavailableError(AITeachMeError):
    error_code = "VECTOR_EXTENSION_UNAVAILABLE"
    status_code = HTTPStatus.SERVICE_UNAVAILABLE

    def __init__(self, reason: str = "") -> None:
        suffix = f" {reason}" if reason else ""
        super().__init__(detail=f"sqlite-vec is unavailable.{suffix}")


class AuthDisabledError(AITeachMeError):
    error_code = "AUTH_DISABLED"
    status_code = HTTPStatus.SERVICE_UNAVAILABLE

    def __init__(self) -> None:
        super().__init__(detail="Authentication is disabled in local mode.")


class AuthNotReadyError(AITeachMeError):
    error_code = "AUTH_NOT_READY"
    status_code = HTTPStatus.SERVICE_UNAVAILABLE

    def __init__(self) -> None:
        super().__init__(detail="Authentication scaffolding is reserved but not implemented.")


class DigestJobNotFoundError(AITeachMeError):
    error_code = "DIGEST_JOB_NOT_FOUND"
    status_code = HTTPStatus.NOT_FOUND

    def __init__(self, job_id: int) -> None:
        super().__init__(detail=f"Digest job `{job_id}` does not exist.")


class KnowledgeUnitNotFoundError(AITeachMeError):
    error_code = "KNOWLEDGE_UNIT_NOT_FOUND"
    status_code = HTTPStatus.NOT_FOUND

    def __init__(self, unit_id: int) -> None:
        super().__init__(detail=f"KnowledgeUnit `{unit_id}` does not exist.")


class NoReadyFilesForDocGenError(AITeachMeError):
    error_code = "NO_READY_FILES_FOR_DOCGEN"
    status_code = HTTPStatus.UNPROCESSABLE_ENTITY

    def __init__(self, subject: str) -> None:
        super().__init__(detail=f"Subject `{subject}` has no ready parsed files for doc generation.")


class ConfirmedBuildPlanRequiredError(AITeachMeError):
    error_code = "CONFIRMED_BUILD_PLAN_REQUIRED"
    status_code = HTTPStatus.UNPROCESSABLE_ENTITY

    def __init__(self, build_type: str) -> None:
        super().__init__(detail=f"Confirmed build plan is required for `{build_type}` build.")


class SubjectBuildLockConflictError(AITeachMeError):
    error_code = "BUILD_IN_PROGRESS"
    status_code = HTTPStatus.CONFLICT

    def __init__(self, subject: str) -> None:
        super().__init__(detail=f"Subject `{subject}` is currently building.")


class KnowledgeBuildPrecheckConflictError(AITeachMeError):
    error_code = "KNOWLEDGE_BUILD_PRECHECK_CONFLICT"
    status_code = HTTPStatus.CONFLICT

    def __init__(self, detail: str, *, data: Any | None = None) -> None:
        super().__init__(detail=detail, data=data)


class EvidenceNotFoundError(AITeachMeError):
    error_code = "EVIDENCE_NOT_FOUND"
    status_code = HTTPStatus.NOT_FOUND

    def __init__(self, evidence_id: int) -> None:
        super().__init__(detail=f"Evidence `{evidence_id}` does not exist.")


class BuildPlannerSessionNotFoundError(AITeachMeError):
    error_code = "BUILD_PLANNER_SESSION_NOT_FOUND"
    status_code = HTTPStatus.NOT_FOUND

    def __init__(self, session_id: str) -> None:
        super().__init__(detail=f"Build planner session `{session_id}` does not exist.")


class ConfirmedBuildPlanNotFoundError(AITeachMeError):
    error_code = "CONFIRMED_BUILD_PLAN_NOT_FOUND"
    status_code = HTTPStatus.NOT_FOUND

    def __init__(self, plan_id: str) -> None:
        super().__init__(detail=f"Confirmed build plan `{plan_id}` does not exist.")


class BuildPlannerEmptyPlanError(AITeachMeError):
    error_code = "BUILD_PLANNER_EMPTY_PLAN"
    status_code = HTTPStatus.UNPROCESSABLE_ENTITY

    def __init__(self, session_id: str) -> None:
        super().__init__(detail=f"Build planner session `{session_id}` has no confirmable draft plan.")
