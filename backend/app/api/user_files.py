"""User-level file library APIs."""

from __future__ import annotations

import html
import mimetypes
import re
import uuid
from html.parser import HTMLParser
from pathlib import Path as FilePath
from urllib.parse import quote

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Path, Query, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.api.deps import CurrentUserContext, get_current_user_context, get_db
from app.api.openapi import build_error_responses
from app.models import TaskStatus
from app.repositories.files_repo import get_raw_file_by_id_for_user, get_raw_file_markdown_chunk_for_user
from app.schemas.common import ApiResponse, ok_response
from app.schemas.files import (
    FileDeleteData,
    FileDeleteRequest,
    FileMarkdownChunk,
    FileRecord,
    FilesData,
    FilesUploadData,
)
from app.shared.infra.execution import TracedExecutionContext
from app.shared.infra.llm_support import run_llm_tasks
from app.shared.infra.llm_support.model_choices import normalize_runtime_model_override, use_runtime_model_override
from app.shared.infra.observability.trace import (
    langsmith_trace,
    llm_trace_scope,
    sanitize_langsmith_input,
    sanitize_langsmith_output,
)
from app.shared.infra.storage import get_content_store
from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.digest.docgen.lib.interactive_html import generate_selection_interactive_html
from app.workflows.ingest.intake import (
    build_file_record,
    delete_user_files,
    get_user_file_or_raise,
    list_user_files,
    resolve_file_markdown_content,
    save_uploaded_files_and_request_parse,
    spawn_parse_files_background,
)

router = APIRouter(prefix="/api/v1/files", tags=["files"])
_INTERACTIVE_HTML_BLOCKED_TAGS = {
    "base",
    "embed",
    "iframe",
    "img",
    "link",
    "meta",
    "object",
    "script",
    "style",
    "svg",
    "template",
}
_INTERACTIVE_HTML_UNWRAPPED_TAGS = {"form"}
_INTERACTIVE_HTML_VOID_TAGS = {"area", "br", "col", "hr", "input", "wbr"}
_INTERACTIVE_HTML_SAFE_URL_RE = re.compile(r"^(?:https?:|mailto:|#|/(?!/))", re.IGNORECASE)
_INTERACTIVE_HTML_UNSAFE_STYLE_RE = re.compile(
    r"(?:expression\s*\(|url\s*\(|javascript:|data:)",
    re.IGNORECASE,
)


@router.post(
    "/upload",
    response_model=ApiResponse[FilesUploadData],
    summary="Upload files to the user library and start parsing immediately",
    responses=build_error_responses([400, 413, 422, 500]),
)
async def upload_user_files(
    request: Request,
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
        course_id=None,
        owner_user_id=user.user_id,
        files=files,
        parse_request_metadata=parse_request_metadata,
    )
    if parse_file_ids:
        spawn_parse_files_background(
            getattr(request.app.state, "background_task_registry", None),
            user_id=user.user_id,
            file_ids=parse_file_ids,
        )
    return ok_response(data)


@router.get(
    "",
    response_model=ApiResponse[FilesData],
    summary="Get user library file metadata",
    responses=build_error_responses([400, 500]),
)
async def list_user_files_api(
    file_ids: list[str] | None = Query(default=None),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[FilesData]:
    unique_file_ids = list(dict.fromkeys(file_ids or [])) or None
    return ok_response(list_user_files(session, owner_user_id=user.user_id, file_ids=unique_file_ids))


@router.post(
    "/delete",
    response_model=ApiResponse[FileDeleteData],
    summary="Delete files from the user library",
    responses=build_error_responses([400, 404, 409, 422, 500]),
)
async def delete_user_files_api(
    body: FileDeleteRequest = Body(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[FileDeleteData]:
    file_ids = [body.file_id] if body.file_id is not None else []
    if body.file_ids:
        file_ids.extend(body.file_ids)
    unique_file_ids = list(dict.fromkeys(file_ids))
    return ok_response(
        await delete_user_files(
            session,
            owner_user_id=user.user_id,
            file_ids=unique_file_ids,
        )
    )


@router.get(
    "/{file_id}",
    response_model=ApiResponse[FileRecord],
    summary="Get one user library file with parsed Markdown",
    responses=build_error_responses([404, 503]),
)
async def get_user_file_api(
    file_id: str = Path(...),
    include_markdown: bool = Query(default=True, description="Include the complete parsed Markdown."),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[FileRecord]:
    raw_file = get_user_file_or_raise(
        session,
        owner_user_id=user.user_id,
        file_id=file_id,
        include_markdown_content=include_markdown,
    )
    if not include_markdown:
        return ok_response(build_file_record(raw_file, include_content=False))

    markdown_content = await resolve_file_markdown_content(raw_file)
    if (
        raw_file.status == TaskStatus.COMPLETED.value
        and raw_file.markdown_path
        and not markdown_content.strip()
    ):
        raise HTTPException(
            status_code=503,
            detail="资料正文暂时无法读取，请稍后重试。",
        )
    return ok_response(build_file_record(raw_file, markdown_content=markdown_content))


@router.get(
    "/{file_id}/markdown",
    response_model=ApiResponse[FileMarkdownChunk],
    summary="Read parsed Markdown progressively",
    responses=build_error_responses([404, 503]),
)
async def get_user_file_markdown_chunk_api(
    file_id: str = Path(...),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=65_536, ge=4_096, le=262_144),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[FileMarkdownChunk]:
    raw_file = get_user_file_or_raise(
        session,
        owner_user_id=user.user_id,
        file_id=file_id,
        include_markdown_content=False,
    )
    result = get_raw_file_markdown_chunk_for_user(
        session,
        user_id=user.user_id,
        file_id=file_id,
        offset=offset,
        limit=limit,
    )

    if result is None:
        # Authorization was already checked above; this only protects against a
        # concurrent delete between the metadata and slice queries.
        raise HTTPException(status_code=404, detail="资料不存在或已删除。")

    content, total_chars = result
    if total_chars == 0 and raw_file.markdown_path:
        recovered = await resolve_file_markdown_content(raw_file)
        if raw_file.status == TaskStatus.COMPLETED.value and not recovered.strip():
            raise HTTPException(status_code=503, detail="资料正文暂时无法读取，请稍后重试。")
        total_chars = len(recovered)
        content = recovered[offset : offset + limit]

    effective_offset = min(offset, total_chars)
    next_offset = min(effective_offset + len(content), total_chars)
    return ok_response(FileMarkdownChunk(
        content=content,
        offset=effective_offset,
        next_offset=next_offset,
        total_chars=total_chars,
        done=next_offset >= total_chars,
    ))


@router.get(
    "/{file_id}/download",
    summary="Download parsed markdown file",
    responses=build_error_responses([404, 503]),
)
async def download_user_file(
    file_id: str = Path(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> Response:
    raw_file = get_user_file_or_raise(session, owner_user_id=user.user_id, file_id=file_id)
    markdown_content = await resolve_file_markdown_content(raw_file)
    if not markdown_content:
        raise HTTPException(status_code=503, detail="资料正文暂时无法读取，请稍后重试。")

    # 构建下载文件名：替换扩展名为 .md
    filename = raw_file.filename
    name_without_ext = filename.rsplit(".", 1)[0] if "." in filename else filename
    download_filename = f"{name_without_ext}.md"

    # RFC 5987: filename*=UTF-8''<url_encoded_name> 支持中文文件名
    encoded_filename = quote(download_filename)
    return Response(
        content=markdown_content.encode("utf-8"),
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}",
        },
    )


@router.get(
    "/assets/{file_id}/{asset_path:path}",
    summary="Serve a parsed asset for a user-library file",
    responses=build_error_responses([404, 500]),
)
async def serve_user_file_asset(
    file_id: str = Path(...),
    asset_path: str = Path(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> Response:
    raw_file = get_raw_file_by_id_for_user(session, user_id=user.user_id, file_id=file_id)
    if raw_file is None:
        return Response(status_code=404, content=b"Not found")

    base_prefix = raw_file.asset_dir or get_content_store().user_file_scope(user_id=user.user_id).asset_prefix(
        file_id=raw_file.id,
        filename=raw_file.filename,
    )
    normalized_asset_path = asset_path.lstrip("/\\")
    if not normalized_asset_path or ".." in FilePath(normalized_asset_path.replace("\\", "/")).parts:
        return Response(status_code=404, content=b"Not found")

    cs = get_content_store()
    # Current ingestion flattens MinerU/PaddleOCR image directories. Try the
    # requested relative path first, then its basename for historical results.
    candidate_paths = [normalized_asset_path]
    basename = FilePath(normalized_asset_path.replace("\\", "/")).name
    if basename and basename != normalized_asset_path:
        candidate_paths.append(basename)
    for candidate_path in candidate_paths:
        storage_key = f"{base_prefix.rstrip('/')}/{candidate_path}"
        try:
            data = await cs.read_bytes(storage_key)
            media_type = mimetypes.guess_type(candidate_path)[0] or "application/octet-stream"
            return Response(content=data, media_type=media_type)
        except Exception:
            continue
    return Response(status_code=404, content=b"Not found")


# ── Highlight CRUD ──────────────────────────────────────────────────────────


class HighlightCreateRequest(BaseModel):
    selected_text: str
    anchor_id: str | None = None
    color: str = "amber"
    segments: list[dict[str, float]] | None = None


class HighlightData(BaseModel):
    id: int
    file_id: str
    selected_text: str
    anchor_id: str | None = None
    color: str
    description: str | None = None
    interactive_html: str | None = None
    segments: list[dict[str, float]] | None = None
    created_at: str


class HighlightListData(BaseModel):
    items: list[HighlightData]


def _clean_highlight_segments(value: list[dict[str, float]] | None) -> list[dict[str, float]] | None:
    if not value:
        return None
    cleaned: list[dict[str, float]] = []
    for item in value[:200]:
        try:
            top = float(item.get("top", 0))
            left = float(item.get("left", 0))
            width = float(item.get("width", 0))
            height = float(item.get("height", 0))
        except (TypeError, ValueError):
            continue
        if width <= 0 or height <= 0:
            continue
        cleaned.append({
            "top": round(top, 3),
            "left": round(left, 3),
            "width": round(width, 3),
            "height": round(height, 3),
        })
    return cleaned or None


def _highlight_data(highlight) -> HighlightData:
    return HighlightData(
        id=highlight.id,
        file_id=highlight.file_id,
        selected_text=highlight.selected_text,
        anchor_id=highlight.anchor_id,
        color=highlight.color,
        description=highlight.description,
        interactive_html=highlight.interactive_html,
        segments=highlight.segments_json if isinstance(highlight.segments_json, list) else None,
        created_at=highlight.created_at.isoformat(),
    )


def _sanitize_interactive_style(value: str) -> str:
    cleaned: list[str] = []
    for raw_declaration in str(value or "").split(";"):
        declaration = raw_declaration.strip()
        if not declaration or ":" not in declaration:
            continue
        property_name, style_value = declaration.split(":", 1)
        normalized_property = property_name.strip().lower()
        normalized_value = style_value.strip()
        if not normalized_property or not normalized_value:
            continue
        if normalized_property in {"behavior", "-moz-binding"}:
            continue
        if _INTERACTIVE_HTML_UNSAFE_STYLE_RE.search(normalized_value):
            continue
        cleaned.append(f"{normalized_property}: {normalized_value}")
    return "; ".join(cleaned)


def _is_safe_interactive_url(value: str) -> bool:
    cleaned = re.sub(r"[\x00-\x1f\x7f\s]+", "", str(value or "")).strip()
    return bool(cleaned and _INTERACTIVE_HTML_SAFE_URL_RE.match(cleaned))


def _sanitize_interactive_attrs(tag: str, attrs: list[tuple[str, str | None]]) -> list[tuple[str, str]]:
    cleaned: list[tuple[str, str]] = []
    for raw_name, raw_value in attrs:
        name = str(raw_name or "").strip().lower()
        value = "" if raw_value is None else str(raw_value)
        if not name:
            continue
        if name.startswith("on") or name in {
            "action",
            "enctype",
            "form",
            "formaction",
            "formenctype",
            "formmethod",
            "formnovalidate",
            "formtarget",
            "method",
            "nonce",
            "srcdoc",
        }:
            continue
        if name == "style":
            safe_style = _sanitize_interactive_style(value)
            if safe_style:
                cleaned.append((name, safe_style))
            continue
        if name in {"href", "src"} or name.endswith(":href"):
            if _is_safe_interactive_url(value):
                cleaned.append((name, value))
            continue
        if name == "target":
            if tag == "a":
                cleaned.append((name, "_blank"))
            continue
        cleaned.append((name, value))

    if tag == "a" and any(name == "href" for name, _ in cleaned):
        cleaned = [(name, value) for name, value in cleaned if name != "rel"]
        cleaned.append(("rel", "noreferrer noopener"))
        if not any(name == "target" for name, _ in cleaned):
            cleaned.append(("target", "_blank"))
    return cleaned


class _InteractiveHtmlSanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self._parts: list[str] = []
        self._blocked_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_name = tag.lower()
        if tag_name in _INTERACTIVE_HTML_BLOCKED_TAGS:
            self._blocked_depth += 1
            return
        if self._blocked_depth:
            return
        if tag_name in _INTERACTIVE_HTML_UNWRAPPED_TAGS:
            return
        safe_attrs = _sanitize_interactive_attrs(tag_name, attrs)
        attr_text = "".join(
            f' {name}="{html.escape(value, quote=True)}"'
            for name, value in safe_attrs
        )
        self._parts.append(f"<{tag_name}{attr_text}>")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_name = tag.lower()
        if (
            tag_name in _INTERACTIVE_HTML_BLOCKED_TAGS
            or tag_name in _INTERACTIVE_HTML_UNWRAPPED_TAGS
            or self._blocked_depth
        ):
            return
        safe_attrs = _sanitize_interactive_attrs(tag_name, attrs)
        attr_text = "".join(
            f' {name}="{html.escape(value, quote=True)}"'
            for name, value in safe_attrs
        )
        self._parts.append(f"<{tag_name}{attr_text}>")

    def handle_endtag(self, tag: str) -> None:
        tag_name = tag.lower()
        if tag_name in _INTERACTIVE_HTML_BLOCKED_TAGS:
            self._blocked_depth = max(0, self._blocked_depth - 1)
            return
        if (
            self._blocked_depth
            or tag_name in _INTERACTIVE_HTML_UNWRAPPED_TAGS
            or tag_name in _INTERACTIVE_HTML_VOID_TAGS
        ):
            return
        self._parts.append(f"</{tag_name}>")

    def handle_data(self, data: str) -> None:
        if not self._blocked_depth:
            self._parts.append(html.escape(data, quote=False))

    def handle_entityref(self, name: str) -> None:
        if not self._blocked_depth:
            self._parts.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if not self._blocked_depth:
            self._parts.append(f"&#{name};")

    def handle_comment(self, data: str) -> None:
        return

    def value(self) -> str:
        return "".join(self._parts).strip()


def _sanitize_interactive_html(html_content: str) -> str:
    parser = _InteractiveHtmlSanitizer()
    parser.feed(str(html_content or ""))
    parser.close()
    return parser.value()


@router.get(
    "/{file_id}/highlights",
    response_model=ApiResponse[HighlightListData],
    summary="List highlights for a library file",
    responses=build_error_responses([404, 500]),
)
async def list_highlights(
    file_id: str = Path(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[HighlightListData]:
    from sqlmodel import select
    from app.models.chat import Highlight

    raw_file = get_raw_file_by_id_for_user(session, user_id=user.user_id, file_id=file_id)
    if raw_file is None:
        return Response(status_code=404, content=b"Not found")

    stmt = select(Highlight).where(
        Highlight.user_id == user.user_id,
        Highlight.file_id == file_id,
    ).order_by(Highlight.created_at.asc())
    items = session.exec(stmt).all()
    return ok_response(HighlightListData(
        items=[_highlight_data(h) for h in items]
    ))


@router.post(
    "/{file_id}/highlights",
    response_model=ApiResponse[HighlightData],
    summary="Create a highlight",
    responses=build_error_responses([404, 500]),
)
async def create_highlight(
    file_id: str = Path(...),
    body: HighlightCreateRequest = Body(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[HighlightData]:
    from app.models.chat import Highlight

    raw_file = get_raw_file_by_id_for_user(session, user_id=user.user_id, file_id=file_id)
    if raw_file is None:
        return Response(status_code=404, content=b"Not found")

    selected_text = body.selected_text.strip()
    if not selected_text:
        return Response(status_code=400, content=b"Selected text is required")

    highlight = Highlight(
        user_id=user.user_id,
        file_id=file_id,
        selected_text=selected_text,
        anchor_id=body.anchor_id,
        color=body.color if body.color in {"amber", "sky"} else "amber",
        segments_json=_clean_highlight_segments(body.segments),
    )
    session.add(highlight)
    session.commit()
    session.refresh(highlight)

    return ok_response(_highlight_data(highlight))


@router.delete(
    "/{file_id}/highlights/{highlight_id}",
    response_model=ApiResponse[dict],
    summary="Delete a highlight",
    responses=build_error_responses([404, 500]),
)
async def delete_highlight(
    file_id: str = Path(...),
    highlight_id: int = Path(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[dict]:
    from sqlmodel import select
    from app.models.chat import Highlight

    stmt = select(Highlight).where(
        Highlight.id == highlight_id,
        Highlight.user_id == user.user_id,
        Highlight.file_id == file_id,
    )
    highlight = session.exec(stmt).first()
    if highlight is None:
        return Response(status_code=404, content=b"Not found")

    session.delete(highlight)
    session.commit()
    return ok_response({"deleted": True})


# ── Interactive Generation ──────────────────────────────────────────────────


class InteractiveGenerateRequest(BaseModel):
    selected_text: str = Field(min_length=1, max_length=2000)
    description: str | None = Field(default=None, max_length=1000)
    model: str | None = Field(default=None, max_length=120)
    replace_highlight_id: int | None = Field(default=None, ge=1)
    segments: list[dict[str, float]] | None = Field(default=None, max_length=200)


class InteractiveGenerateData(BaseModel):
    html: str
    highlight_id: int | None = None
    highlight: HighlightData | None = None
    title: str | None = None
    widget_type: str | None = None
    widget_outline: dict[str, object] | None = None
    widget_config: dict[str, object] | None = None
    language_directive: str | None = None


def _library_selection_excerpt(markdown_content: str, *, selected_text: str, limit: int = 5000) -> tuple[str, str, str]:
    context_before = ""
    context_after = ""
    idx = markdown_content.find(selected_text)
    if idx >= 0:
        half = max(400, limit // 2)
        start = max(0, idx - half)
        end = min(len(markdown_content), idx + len(selected_text) + half)
        context_before = markdown_content[start:idx]
        context_after = markdown_content[idx + len(selected_text) : end]
        excerpt = markdown_content[start:end]
    else:
        excerpt = markdown_content[:limit]
    return context_before, context_after, excerpt[:limit]


def _library_anchor_title(markdown_content: str, *, selected_text: str) -> str:
    idx = markdown_content.find(selected_text)
    if idx < 0:
        return "资料库选区"
    headings = list(re.finditer(r"^(?P<marks>#{1,6})\s+(?P<title>.+?)\s*$", markdown_content[:idx], re.MULTILINE))
    if not headings:
        return "资料库选区"
    title = re.sub(r"\s+", " ", headings[-1].group("title")).strip()
    return title or "资料库选区"


@router.post(
    "/{file_id}/interactive",
    response_model=ApiResponse[InteractiveGenerateData],
    summary="Generate interactive content from selected text",
    responses=build_error_responses([400, 404, 422, 500, 503]),
)
async def generate_interactive(
    file_id: str = Path(...),
    body: InteractiveGenerateRequest = Body(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[InteractiveGenerateData]:
    from sqlmodel import select
    from app.models.chat import Highlight

    raw_file = get_raw_file_by_id_for_user(session, user_id=user.user_id, file_id=file_id)
    if raw_file is None:
        return Response(status_code=404, content=b"Not found")

    markdown_content = raw_file.markdown_content or ""
    if not markdown_content:
        return Response(status_code=400, content=b"No markdown content available")

    # 找到选中文本在 markdown 中的上下文
    selected_text = body.selected_text.strip()
    if not selected_text:
        return Response(status_code=400, content=b"Selected text is required")

    context_before, context_after, section_excerpt = _library_selection_excerpt(
        markdown_content,
        selected_text=selected_text,
    )
    user_prompt = body.description.strip() if body.description else ""
    model_override = normalize_runtime_model_override(body.model)
    anchor_title = _library_anchor_title(markdown_content, selected_text=selected_text)
    heading_path = [item for item in [raw_file.filename, anchor_title] if item]
    replace_highlight: Highlight | None = None
    if body.replace_highlight_id is not None:
        stmt = select(Highlight).where(
            Highlight.id == body.replace_highlight_id,
            Highlight.user_id == user.user_id,
            Highlight.file_id == file_id,
        )
        replace_highlight = session.exec(stmt).first()
        if replace_highlight is None:
            return Response(status_code=404, content=b"Highlight not found")

    build_session_id = f"library-selection-{uuid.uuid4().hex[:12]}"
    trace_course_id = f"library:{user.user_id}"
    workflow_context = WorkflowContext(
        workflow_name="library.selection_interactive",
        course_id=trace_course_id,
        metadata={
            "lane": "library",
            "user_id": user.user_id,
            "file_id": file_id,
            "filename": raw_file.filename,
            "asset_kind": "interactive_html",
            "model_override": model_override or "",
        },
    )
    traced_context = TracedExecutionContext(
        course_id=trace_course_id,
        build_session_id=build_session_id,
        workflow_context=workflow_context,
        digest_mode="systematic",
        teaching_action="library_selection_interactive_html",
        asset_kind="interactive_html",
        extra_metadata={
            "user_id": user.user_id,
            "file_id": file_id,
            "filename": raw_file.filename,
            "model_override": model_override or "",
        },
    )
    try:
        trace_metadata = traced_context.trace_metadata(
            docgen_stage="interactive_html_generation",
            selected_chars=len(selected_text),
            prompt_chars=len(user_prompt),
            context_before_chars=len(context_before),
            context_after_chars=len(context_after),
            model_override=model_override or "",
        )
        trace_inputs = sanitize_langsmith_input(
            {
                "file_id": file_id,
                "filename": raw_file.filename,
                "anchor_title": anchor_title,
                "heading_path": heading_path,
                "selected_text_preview": selected_text[:800],
                "prompt": user_prompt,
                "model_override": model_override or "",
            },
            field_name="library_interactive_html_generation_inputs",
        )
        with llm_trace_scope(
            course_id=trace_course_id,
            build_session_id=build_session_id,
            workflow=workflow_context.workflow_name,
            lane="library",
            node="library_files.interactive_html_generation",
        ):
            with langsmith_trace(
                name="资料库：划选交互 HTML 生成",
                run_type="chain",
                inputs=trace_inputs,
                course_id=trace_course_id,
                build_session_id=build_session_id,
                workflow=workflow_context.workflow_name,
                lane="library",
                node="library_files.interactive_html_generation",
                extra_metadata=trace_metadata,
                extra_tags=["library:interactive_html"],
            ) as trace_run:
                with use_runtime_model_override(model_override):
                    generated = (
                        await run_llm_tasks(
                            [None],
                            lambda _item: generate_selection_interactive_html(
                                traced_context=traced_context,
                                anchor_title=anchor_title,
                                heading_path=heading_path,
                                selected_text=selected_text,
                                user_prompt=user_prompt,
                                section_excerpt=section_excerpt,
                                docgen_stage="library_interactive_html_selection",
                                extra_metadata={
                                    "library_file_id": file_id,
                                    "library_filename": raw_file.filename,
                                    "model_override": model_override or "",
                                },
                            ),
                        )
                    )[0]
                if trace_run is not None:
                    trace_run.end(
                        outputs=sanitize_langsmith_output(
                            {
                                "title": generated.title,
                                "html_chars": len(generated.html),
                                "validation_issue_count": len(generated.validation_issues),
                                "quality_issue_count": len(generated.quality_issues),
                                "widget_type": generated.widget_type,
                            },
                            field_name="library_interactive_html_generation_outputs",
                        )
                    )
        html_content = generated.html
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        import structlog
        logger = structlog.get_logger()
        logger.warning(
            "library_interactive_generation_failed",
            user_id=user.user_id,
            file_id=file_id,
            error=str(exc)[:240],
        )
        raise HTTPException(
            status_code=503,
            detail="交互页生成暂时失败，可能是模型服务连接中断。请稍后重试或换一段选区再生成。",
        ) from exc

    cleaned_segments = _clean_highlight_segments(body.segments)
    if replace_highlight is not None:
        highlight = replace_highlight
        highlight.selected_text = selected_text
        highlight.color = "sky"
        highlight.description = body.description.strip() if body.description else highlight.description
        highlight.interactive_html = html_content
        if cleaned_segments is not None:
            highlight.segments_json = cleaned_segments
    else:
        highlight = Highlight(
            user_id=user.user_id,
            file_id=file_id,
            selected_text=selected_text,
            color="sky",
            description=body.description.strip() if body.description else None,
            interactive_html=html_content,
            segments_json=cleaned_segments,
        )
        session.add(highlight)
    session.commit()
    session.refresh(highlight)

    return ok_response(InteractiveGenerateData(
        html=html_content,
        highlight_id=highlight.id,
        highlight=_highlight_data(highlight),
        title=generated.title,
        widget_type=generated.widget_type or None,
        widget_outline=generated.widget_outline or None,
        widget_config=generated.widget_config or None,
        language_directive=generated.language_directive or None,
    ))
