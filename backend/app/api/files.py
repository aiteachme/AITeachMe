"""File APIs."""

from __future__ import annotations

import mimetypes
from pathlib import Path as FilePath
from typing import Any

from fastapi import APIRouter, Body, Depends, File, Form, Path, Request, UploadFile
from fastapi.responses import Response
from sqlmodel import Session

from app.api.deps import CurrentUserContext, get_current_user_context, get_db, normalize_course_id
from app.api.openapi import build_error_responses
from app.schemas.common import ApiResponse, ok_response
from app.schemas.files import FileDeleteData, FileDeleteRequest, FileLinkRequest, FilesData, FilesUploadData
from app.shared.infra.storage import get_content_store
from app.repositories.files_repo import link_raw_files_to_course
from app.workflows.ingest.intake import (
    delete_files,
    get_user_files_or_raise,
    list_course_files,
    ready_file_ids_for_course_indexing,
    save_uploaded_files_and_request_parse,
    spawn_index_course_files_background,
    spawn_parse_files_background,
)
from app.workflows.support.courses import get_course_record

router = APIRouter(prefix="/api/v1/courses/{course_id}/files", tags=["files"])

_DOCGEN_STATIC_FIGURE_PREFIX = "docgen/figures/"


def _normalize_safe_asset_path(asset_path: str) -> str | None:
    """Return a storage-relative asset path, or None when traversal is attempted."""

    normalized = str(asset_path or "").lstrip("/\\")
    if not normalized or ".." in FilePath(normalized.replace("\\", "/")).parts:
        return None
    return normalized


def _normalize_manifest_asset_path(value: object) -> str:
    return str(value or "").replace("\\", "/").strip().lstrip("/")


def _iter_docgen_asset_manifest_items(manifest: Any) -> list[dict[str, Any]]:
    if not isinstance(manifest, dict):
        return []
    asset_manifest = manifest.get("asset_manifest")
    if not isinstance(asset_manifest, dict):
        return []
    assets = asset_manifest.get("assets")
    if not isinstance(assets, list):
        return []
    return [asset for asset in assets if isinstance(asset, dict)]


async def _restore_static_docgen_figure_asset(
    *,
    content_store: Any,
    manifest_key: str,
    storage_key: str,
    normalized_asset_path: str,
) -> bytes | None:
    """Rebuild missing static DocGen figure HTML from the published manifest.

    Static figure manifests keep the structured ``figure_spec``. If an object
    store write was missed or an asset was pruned, the public asset route can
    safely re-render the script-free HTML and write it back.
    """

    normalized_asset_path = _normalize_manifest_asset_path(normalized_asset_path)
    if not (
        normalized_asset_path.startswith(_DOCGEN_STATIC_FIGURE_PREFIX)
        and normalized_asset_path.endswith(".html")
    ):
        return None

    try:
        manifest = await content_store.read_json_raw(manifest_key)
    except Exception:
        return None

    matched_asset: dict[str, Any] | None = None
    for asset in _iter_docgen_asset_manifest_items(manifest):
        if asset.get("kind") != "static_html_figure":
            continue
        if _normalize_manifest_asset_path(asset.get("asset_path")) == normalized_asset_path:
            matched_asset = asset
            break
    if matched_asset is None:
        return None

    try:
        from app.shared.infra.tools.builtin.markdown_processing import validate_single_file_html
        from app.workflows.digest.docgen.lib.figure_spec import FigureSpec, render_figure_spec_html
        from app.workflows.digest.docgen.lib.html_sidecar import normalize_single_file_html

        raw_spec = matched_asset.get("figure_spec")
        if not isinstance(raw_spec, dict):
            return None
        spec = FigureSpec.model_validate(raw_spec)
        title = str(matched_asset.get("title") or spec.title or "静态图示").strip() or "静态图示"
        html = normalize_single_file_html(
            render_figure_spec_html(spec, title=title),
            title=title,
            allow_scripts=False,
        )
        if validate_single_file_html(html):
            return None
        data = html.encode("utf-8")
        try:
            await content_store.write_text(storage_key, html)
        except Exception:
            pass
        return data
    except Exception:
        return None


@router.post(
    "/upload",
    response_model=ApiResponse[FilesUploadData],
    summary="Upload files and start parsing immediately",
    responses=build_error_responses([400, 404, 413, 422, 500]),
)
async def upload_files(
    request: Request,
    course_id: str = Path(...),
    files: list[UploadFile] = File(...),
    parser_provider: str | None = Form(default=None),
    mineru_api_token: str | None = Form(default=None),
    paddle_ocr_api_token: str | None = Form(default=None),
    mineru_model_version: str | None = Form(default=None),
    mineru_enable_formula: bool | None = Form(default=None),
    mineru_enable_table: bool | None = Form(default=None),
    mineru_is_ocr: bool | None = Form(default=None),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[FilesUploadData]:
    normalized_course_id = normalize_course_id(course_id)
    course_record = get_course_record(session, normalized_course_id, owner_user_id=user.user_id)

    parse_request_metadata: dict[str, object] | None = None
    if any(
        value is not None
        for value in (
            parser_provider,
            mineru_api_token,
            paddle_ocr_api_token,
            mineru_model_version,
            mineru_enable_formula,
            mineru_enable_table,
            mineru_is_ocr,
        )
    ):
        parse_request_metadata = {}
        if parser_provider:
            parse_request_metadata["requested_parser_provider"] = parser_provider
        if any(
            value is not None
            for value in (
                mineru_api_token,
                mineru_model_version,
                mineru_enable_formula,
                mineru_enable_table,
                mineru_is_ocr,
            )
        ):
            parse_request_metadata["mineru"] = {
                "api_token": mineru_api_token,
                "model_version": mineru_model_version,
                "enable_formula": mineru_enable_formula,
                "enable_table": mineru_enable_table,
                "is_ocr": mineru_is_ocr,
            }
        if paddle_ocr_api_token is not None:
            parse_request_metadata["paddle_ocr"] = {
                "api_token": paddle_ocr_api_token,
            }

    data, parse_file_ids = await save_uploaded_files_and_request_parse(
        session,
        course_id=normalized_course_id,
        owner_user_id=user.user_id,
        files=files,
        parse_request_metadata=parse_request_metadata,
        origin_course_name=course_record.name,
    )
    background_task_registry = getattr(request.app.state, "background_task_registry", None)
    if parse_file_ids:
        spawn_parse_files_background(
            background_task_registry,
            user_id=user.user_id,
            course_id=normalized_course_id,
            file_ids=parse_file_ids,
        )
    parse_file_id_set = set(parse_file_ids)
    reused_ready_file_ids = [
        item.id
        for item in data.uploaded_items
        if item.markdown_ready and item.id not in parse_file_id_set
    ]
    spawn_index_course_files_background(
        background_task_registry,
        user_id=user.user_id,
        course_id=normalized_course_id,
        file_ids=reused_ready_file_ids,
        reason="ingest.upload.reused_completed",
    )
    return ok_response(data)


@router.get(
    "",
    response_model=ApiResponse[FilesData],
    summary="Get all course files with full data",
    responses=build_error_responses([400, 404, 500]),
)
async def list_files_api(
    course_id: str = Path(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[FilesData]:
    normalized_course_id = normalize_course_id(course_id)
    get_course_record(session, normalized_course_id, owner_user_id=user.user_id)
    return ok_response(list_course_files(session, course_id=normalized_course_id))


@router.post(
    "/link",
    response_model=ApiResponse[FilesData],
    summary="Link existing user files to a course",
    responses=build_error_responses([400, 404, 422, 500]),
)
async def link_files_api(
    request: Request,
    course_id: str = Path(...),
    body: FileLinkRequest = Body(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[FilesData]:
    normalized_course_id = normalize_course_id(course_id)
    get_course_record(session, normalized_course_id, owner_user_id=user.user_id)
    raw_files = get_user_files_or_raise(
        session,
        owner_user_id=user.user_id,
        file_ids=list(dict.fromkeys(body.file_ids)),
    )
    link_raw_files_to_course(
        session,
        owner_user_id=user.user_id,
        course_id=normalized_course_id,
        raw_files=raw_files,
    )
    spawn_index_course_files_background(
        getattr(request.app.state, "background_task_registry", None),
        user_id=user.user_id,
        course_id=normalized_course_id,
        file_ids=ready_file_ids_for_course_indexing(raw_files),
        reason="ingest.link.completed",
    )
    return ok_response(list_course_files(session, course_id=normalized_course_id))


@router.post(
    "/delete",
    response_model=ApiResponse[FileDeleteData],
    summary="Delete files",
    responses=build_error_responses([400, 404, 409, 422, 500]),
)
async def delete_files_api(
    course_id: str = Path(...),
    body: FileDeleteRequest = Body(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[FileDeleteData]:
    normalized_course_id = normalize_course_id(course_id)
    get_course_record(session, normalized_course_id, owner_user_id=user.user_id)
    file_ids = [body.file_id] if body.file_id is not None else []
    if body.file_ids:
        file_ids.extend(body.file_ids)
    unique_file_ids = list(dict.fromkeys(file_ids))
    return ok_response(
        await delete_files(
            session,
            course_id=normalized_course_id,
            owner_user_id=user.user_id,
            file_ids=unique_file_ids,
        )
    )


@router.get(
    "/assets/{asset_path:path}",
    summary="Serve file asset (images, etc.)",
    responses=build_error_responses([404, 500]),
)
async def serve_file_asset(
    course_id: str = Path(...),
    asset_path: str = Path(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> Response:
    """代理访问文件资产。

    通过后端鉴权后代理返回，避免把用户私有 storage key 暴露到公开加速域名。
    """
    normalized_course_id = normalize_course_id(course_id)
    get_course_record(session, normalized_course_id, owner_user_id=user.user_id)

    cs = get_content_store()
    course_scope = cs.course_scope(user_id=user.user_id, course_id=normalized_course_id)
    normalized_asset_path = _normalize_safe_asset_path(asset_path)
    if normalized_asset_path is None:
        return Response(status_code=404, content=b"Not found")
    storage_key = f"{course_scope.namespace}/assets/{normalized_asset_path}"
    media_type = mimetypes.guess_type(asset_path)[0] or "application/octet-stream"

    try:
        data = await cs.read_bytes(storage_key)
        return Response(content=data, media_type=media_type)
    except Exception:
        restored = await _restore_static_docgen_figure_asset(
            content_store=cs,
            manifest_key=f"{course_scope.namespace}/knowledge_markdowns/docgen_manifest.json",
            storage_key=storage_key,
            normalized_asset_path=normalized_asset_path,
        )
        if restored is not None:
            return Response(content=restored, media_type=media_type)
        return Response(status_code=404, content=b"Not found")
