"""User-level file library APIs."""

from __future__ import annotations

import html
import mimetypes
import re
from html.parser import HTMLParser
from pathlib import Path as FilePath
from urllib.parse import quote

from fastapi import APIRouter, Body, Depends, File, Form, Path, Query, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlmodel import Session

from app.api.deps import CurrentUserContext, get_current_user_context, get_db
from app.api.openapi import build_error_responses
from app.repositories.files_repo import get_raw_file_by_id_for_user
from app.schemas.common import ApiResponse, ok_response
from app.schemas.files import FileDeleteData, FileDeleteRequest, FilesData, FilesUploadData
from app.shared.infra.storage import get_content_store
from app.workflows.ingest.intake import (
    delete_user_files,
    list_user_files,
    run_parse_files_background,
    save_uploaded_files_and_request_parse,
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
        registry_course = f"files:{user.user_id}"
        request.app.state.background_task_registry.spawn(
            run_parse_files_background(
                user_id=user.user_id,
                file_ids=parse_file_ids,
                background_task_registry=request.app.state.background_task_registry,
            ),
            kind="files.parse",
            course_id=registry_course,
            name=f"files.parse:{registry_course}",
            dedupe_key=f"files.parse:{registry_course}:{':'.join(sorted(parse_file_ids))}",
        )
    return ok_response(data)


@router.get(
    "",
    response_model=ApiResponse[FilesData],
    summary="Get user library files with full data",
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
    "/{file_id}/download",
    summary="Download parsed markdown file",
    responses=build_error_responses([404, 500]),
)
async def download_user_file(
    file_id: str = Path(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> Response:
    raw_file = get_raw_file_by_id_for_user(session, user_id=user.user_id, file_id=file_id)
    if raw_file is None:
        return Response(status_code=404, content=b"Not found")

    markdown_content = raw_file.markdown_content
    if not markdown_content:
        return Response(status_code=404, content=b"Markdown content not available")

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

    storage_key = f"{base_prefix.rstrip('/')}/{normalized_asset_path}"
    media_type = mimetypes.guess_type(asset_path)[0] or "application/octet-stream"

    cs = get_content_store()
    try:
        data = await cs.read_bytes(storage_key)
        return Response(content=data, media_type=media_type)
    except Exception:
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
        if name.startswith("on") or name in {"formaction", "nonce", "srcdoc"}:
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
        safe_attrs = _sanitize_interactive_attrs(tag_name, attrs)
        attr_text = "".join(
            f' {name}="{html.escape(value, quote=True)}"'
            for name, value in safe_attrs
        )
        self._parts.append(f"<{tag_name}{attr_text}>")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_name = tag.lower()
        if tag_name in _INTERACTIVE_HTML_BLOCKED_TAGS or self._blocked_depth:
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
        if self._blocked_depth or tag_name in _INTERACTIVE_HTML_VOID_TAGS:
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
    selected_text: str
    description: str | None = None
    segments: list[dict[str, float]] | None = None


class InteractiveGenerateData(BaseModel):
    html: str
    highlight_id: int | None = None
    highlight: HighlightData | None = None


@router.post(
    "/{file_id}/interactive",
    response_model=ApiResponse[InteractiveGenerateData],
    summary="Generate interactive content from selected text",
    responses=build_error_responses([400, 404, 500]),
)
async def generate_interactive(
    file_id: str = Path(...),
    body: InteractiveGenerateRequest = Body(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[InteractiveGenerateData]:
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

    context_before = ""
    context_after = ""
    idx = markdown_content.find(selected_text)
    if idx >= 0:
        start = max(0, idx - 500)
        end = min(len(markdown_content), idx + len(selected_text) + 500)
        context_before = markdown_content[start:idx]
        context_after = markdown_content[idx + len(selected_text) : end]

    # 使用 LLM 生成交互式内容
    from app.shared.infra.llm_support import acompletion
    system_prompt = """你是一个教学内容生成助手。根据用户选中的文本和可选的描述，生成一个交互式的学习内容。

要求：
1. 生成一个完整的 HTML 片段（不需要 html/head/body 标签）
2. 内容要有趣、交互性强，可以是：测验题、填空题、对比表格、思维导图、代码示例等
3. 使用内联 CSS 样式，不要依赖外部资源
4. 不要输出 script 标签、on* 事件属性、iframe、外部资源或 javascript: 链接；交互优先用 details/summary、checkbox/radio + CSS 等无脚本结构
5. 风格简洁现代，适合暗色和亮色主题
6. 直接输出 HTML，不要加 markdown 代码块标记"""

    user_message = f"""选中的文本：
{selected_text}

上下文（选中前）：
{context_before[-200:] if context_before else "无"}

上下文（选中后）：
{context_after[:200] if context_after else "无"}"""

    if body.description:
        user_message += f"\n\n用户要求：{body.description}"

    try:
        html_content = await acompletion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            model="primary",
            temperature=0.7,
            max_tokens=2000,
            extra_metadata={"substep": "library_file_interactive"},
        )
        html_content = html_content.strip()
        # 清理 markdown 代码块标记
        if html_content.startswith("```"):
            html_content = html_content.split("\n", 1)[1] if "\n" in html_content else html_content[3:]
        if html_content.endswith("```"):
            html_content = html_content[:-3]
        html_content = html_content.strip()
        html_content = _sanitize_interactive_html(html_content)
    except Exception as exc:
        import structlog
        logger = structlog.get_logger()
        logger.error("interactive_generation_failed", error=str(exc))
        return Response(status_code=500, content=b"Generation failed")

    # 创建高亮记录
    from app.models.chat import Highlight
    highlight = Highlight(
        user_id=user.user_id,
        file_id=file_id,
        selected_text=selected_text,
        color="sky",
        description=body.description.strip() if body.description else None,
        interactive_html=html_content,
        segments_json=_clean_highlight_segments(body.segments),
    )
    session.add(highlight)
    session.commit()
    session.refresh(highlight)

    return ok_response(InteractiveGenerateData(
        html=html_content,
        highlight_id=highlight.id,
        highlight=_highlight_data(highlight),
    ))
