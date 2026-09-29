"""Course-scoped APIs for importing and managing declarative question types."""

from __future__ import annotations

import tempfile
from importlib import resources
from pathlib import Path as FsPath

from fastapi import APIRouter, Body, Depends, File, Path, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from sqlmodel import Session, select

from app.api.deps import CurrentUserContext, get_current_user_context, get_db, normalize_course_id
from app.api.openapi import build_error_responses
from app.models import Course
from app.schemas.common import ApiResponse, ok_response
from app.schemas.question_type_packages import (
    QuestionTypeCatalogItemResponse,
    QuestionTypeCatalogPatchRequest,
    QuestionTypeExampleResponse,
    QuestionTypePackageInstallData,
    QuestionTypePackageInstallRequest,
    QuestionTypePackagePreviewData,
)
from app.shared.infra.exceptions import AITeachMeError
from app.workflows.support.question_type_packages import validate_atqskill
from app.workflows.support.question_type_packages.contracts import (
    MAX_PACKAGE_BYTES,
)
from app.workflows.support.question_type_packages.installer import (
    create_pending_import,
    get_question_type_asset,
    get_question_type_catalog_item,
    install_pending_import,
    list_question_type_catalog,
    update_question_type_catalog_item,
)
from app.workflows.support.course_mutation_lock import course_mutation_lock


router = APIRouter(
    prefix="/api/v1/courses/{course_id}/question-types",
    tags=["question-type-packages"],
)

_UPLOAD_CHUNK_BYTES = 64 * 1024
_SUPPORTED_UPLOAD_SUFFIXES = {".atqskill", ".zip"}
_SAFE_ASSET_MEDIA_TYPES = frozenset(
    {"image/png", "image/jpeg", "image/webp"}
)
_EXAMPLE_PACKAGE_NAMES = {
    "experiment_design": ("实验设计题", "experiment_design-2.0.0.atqskill"),
    "case_analysis": ("案例分析题", "case_analysis-2.0.0.atqskill"),
    "argument_debate": ("论证辩论题", "argument_debate-2.0.0.atqskill"),
    "feynman_explanation": ("费曼解释题", "feynman_explanation-2.0.0.atqskill"),
    "oral_defense": ("书面答辩题", "oral_defense-2.0.0.atqskill"),
    "scenario_interview": ("情境面试题", "scenario_interview-2.0.0.atqskill"),
}
_LEGACY_EXAMPLE_IDS = {
    "experiment_design_v2": "experiment_design",
    "case_analysis_v2": "case_analysis",
    "argument_debate_v1": "argument_debate",
    "feynman_explanation_v1": "feynman_explanation",
    "oral_defense_v1": "oral_defense",
    "scenario_interview_v1": "scenario_interview",
}


def _ensure_owned_course(
    session: Session,
    *,
    course_id: str,
    user_id: str,
    for_update: bool = False,
) -> Course:
    statement = select(Course).where(Course.id == course_id, Course.user_id == user_id)
    if for_update:
        statement = statement.with_for_update()
    course = session.exec(statement).first()
    if course is None:
        raise AITeachMeError(
            detail=f"课程 `{course_id}` 不存在。",
            error_code="COURSE_NOT_FOUND",
            status_code=404,
        )
    return course


def _validate_upload_filename(filename: str) -> None:
    suffix = FsPath(filename).suffix.casefold()
    if suffix not in _SUPPORTED_UPLOAD_SUFFIXES:
        raise AITeachMeError(
            detail="请上传 .atqskill 题型包；兼容内容相同的 .zip 文件。",
            error_code="QUESTION_TYPE_PACKAGE_FILE_UNSUPPORTED",
            status_code=400,
        )


async def _copy_upload(file: UploadFile, target: FsPath) -> int:
    bytes_written = 0
    with target.open("wb") as output:
        while True:
            chunk = await file.read(_UPLOAD_CHUNK_BYTES)
            if not chunk:
                break
            bytes_written += len(chunk)
            if bytes_written > MAX_PACKAGE_BYTES:
                raise AITeachMeError(
                    detail="题型包不能超过 8 MB。",
                    error_code="QUESTION_TYPE_PACKAGE_TOO_LARGE",
                    status_code=413,
                )
            output.write(chunk)
    if bytes_written == 0:
        raise AITeachMeError(
            detail="题型包文件为空。",
            error_code="QUESTION_TYPE_PACKAGE_EMPTY",
            status_code=400,
        )
    return bytes_written


@router.get(
    "",
    response_model=ApiResponse[list[QuestionTypeCatalogItemResponse]],
    summary="列出课程题型目录",
    responses=build_error_responses([404, 500]),
)
async def list_question_types_api(
    course_id: str = Path(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[list[QuestionTypeCatalogItemResponse]]:
    normalized = normalize_course_id(course_id)
    _ensure_owned_course(session, course_id=normalized, user_id=user.user_id)
    return ok_response(list_question_type_catalog(session, course_id=normalized))


@router.post(
    "/imports",
    response_model=ApiResponse[QuestionTypePackagePreviewData],
    summary="上传并校验课程题型包",
    responses=build_error_responses([400, 404, 413, 422, 429, 500]),
)
async def preview_question_type_import_api(
    course_id: str = Path(...),
    file: UploadFile = File(..., description=".atqskill 题型包或兼容 ZIP。"),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[QuestionTypePackagePreviewData]:
    normalized = normalize_course_id(course_id)
    _ensure_owned_course(session, course_id=normalized, user_id=user.user_id)
    raw_filename = (file.filename or "upload.atqskill").strip() or "upload.atqskill"
    if any(ord(character) < 32 or ord(character) == 127 for character in raw_filename):
        raise AITeachMeError(
            detail="题型包文件名包含不允许的控制字符。",
            error_code="QUESTION_TYPE_PACKAGE_FILENAME_INVALID",
            status_code=400,
        )
    filename = raw_filename.replace("\\", "/").rsplit("/", 1)[-1][:200]
    _validate_upload_filename(filename)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".atqskill") as temp_file:
        temp_path = FsPath(temp_file.name)
    try:
        await _copy_upload(file, temp_path)
        result = await run_in_threadpool(validate_atqskill, temp_path)
        archive_bytes = temp_path.read_bytes() if result.valid else b""
        _record, preview = create_pending_import(
            session,
            course_id=normalized,
            user_id=user.user_id,
            original_filename=filename,
            archive_bytes=archive_bytes,
            result=result,
        )
        return ok_response(preview)
    finally:
        temp_path.unlink(missing_ok=True)
        await file.close()


@router.post(
    "/imports/{import_id}/confirm",
    response_model=ApiResponse[QuestionTypePackageInstallData],
    summary="确认安装已校验的课程题型包",
    responses=build_error_responses([404, 409, 410, 413, 500]),
)
async def confirm_question_type_import_api(
    course_id: str = Path(...),
    import_id: str = Path(...),
    body: QuestionTypePackageInstallRequest = Body(
        default=QuestionTypePackageInstallRequest()
    ),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[QuestionTypePackageInstallData]:
    normalized = normalize_course_id(course_id)
    with course_mutation_lock(normalized):
        try:
            _ensure_owned_course(
                session,
                course_id=normalized,
                user_id=user.user_id,
                for_update=True,
            )
            installed = install_pending_import(
                session,
                course_id=normalized,
                user_id=user.user_id,
                import_id=import_id,
                set_current=body.set_current,
            )
            # Dependency cleanup runs after this lock is released. Finish the
            # transaction here so the next request sees the installed version.
            session.commit()
        except Exception:
            session.rollback()
            raise
        return ok_response(installed)


@router.get(
    "/examples",
    response_model=ApiResponse[list[QuestionTypeExampleResponse]],
    summary="列出官方题型包示例",
    responses=build_error_responses([404, 500]),
)
async def list_question_type_examples_api(
    course_id: str = Path(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[list[QuestionTypeExampleResponse]]:
    normalized = normalize_course_id(course_id)
    _ensure_owned_course(session, course_id=normalized, user_id=user.user_id)
    return ok_response(
        [
            QuestionTypeExampleResponse(
                example_id=example_id,
                template_key=example_id,
                name=name,
                filename=filename,
            )
            for example_id, (name, filename) in sorted(_EXAMPLE_PACKAGE_NAMES.items())
        ]
    )


@router.get(
    "/examples/{example_id}",
    response_class=FileResponse,
    summary="下载官方题型包示例",
    responses=build_error_responses([400, 404, 500]),
)
async def download_question_type_example_api(
    course_id: str = Path(...),
    example_id: str = Path(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> FileResponse:
    normalized = normalize_course_id(course_id)
    _ensure_owned_course(session, course_id=normalized, user_id=user.user_id)
    example_id = _LEGACY_EXAMPLE_IDS.get(example_id, example_id)
    if example_id not in _EXAMPLE_PACKAGE_NAMES:
        raise AITeachMeError(
            detail="题型示例不存在。",
            error_code="QUESTION_TYPE_EXAMPLE_NOT_FOUND",
            status_code=404,
        )
    _name, filename = _EXAMPLE_PACKAGE_NAMES[example_id]
    resource = resources.files(
        "app.workflows.support.question_type_packages.example_packages"
    ).joinpath(filename)
    if not resource.is_file():
        raise AITeachMeError(
            detail="题型示例文件暂不可用。",
            error_code="QUESTION_TYPE_EXAMPLE_UNAVAILABLE",
            status_code=500,
        )
    return FileResponse(
        path=str(resource),
        filename=filename,
        media_type="application/zip",
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.get(
    "/assets/{asset_id}",
    response_class=Response,
    summary="读取已安装题型包资源",
    responses=build_error_responses([404, 409, 500]),
)
async def question_type_asset_api(
    course_id: str = Path(...),
    asset_id: int = Path(..., ge=1),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> Response:
    normalized = normalize_course_id(course_id)
    _ensure_owned_course(session, course_id=normalized, user_id=user.user_id)
    asset, content = get_question_type_asset(
        session,
        course_id=normalized,
        asset_id=asset_id,
    )
    if asset.media_type not in _SAFE_ASSET_MEDIA_TYPES:
        raise AITeachMeError(
            detail="题型资源格式不受支持。",
            error_code="QUESTION_TYPE_ASSET_UNSAFE",
            status_code=409,
        )
    return Response(
        content=content,
        media_type=asset.media_type,
        headers={
            "Cache-Control": "private, max-age=31536000, immutable",
            "Content-Disposition": "inline",
            "Content-Security-Policy": "default-src 'none'; sandbox",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get(
    "/{registry_id}",
    response_model=ApiResponse[QuestionTypeCatalogItemResponse],
    summary="读取课程题型详情",
    responses=build_error_responses([404, 500]),
)
async def get_question_type_api(
    course_id: str = Path(...),
    registry_id: int = Path(..., ge=1),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[QuestionTypeCatalogItemResponse]:
    normalized = normalize_course_id(course_id)
    _ensure_owned_course(session, course_id=normalized, user_id=user.user_id)
    return ok_response(
        get_question_type_catalog_item(
            session,
            course_id=normalized,
            registry_id=registry_id,
        )
    )


@router.patch(
    "/{registry_id}",
    response_model=ApiResponse[QuestionTypeCatalogItemResponse],
    summary="修改课程上传题型状态或当前版本",
    responses=build_error_responses([404, 409, 422, 500]),
)
async def patch_question_type_api(
    course_id: str = Path(...),
    registry_id: int = Path(..., ge=1),
    body: QuestionTypeCatalogPatchRequest = Body(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[QuestionTypeCatalogItemResponse]:
    normalized = normalize_course_id(course_id)
    with course_mutation_lock(normalized):
        try:
            _ensure_owned_course(
                session,
                course_id=normalized,
                user_id=user.user_id,
                for_update=True,
            )
            updated = update_question_type_catalog_item(
                session,
                course_id=normalized,
                registry_id=registry_id,
                status=body.status,
                current_version_id=body.current_version_id,
            )
            # Serialize status/version changes through commit, just like installs.
            session.commit()
        except Exception:
            session.rollback()
            raise
        return ok_response(updated)


__all__ = ["router"]
