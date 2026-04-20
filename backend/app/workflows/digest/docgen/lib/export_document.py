"""Export helpers for the merged DocGen knowledge document."""

from __future__ import annotations

import html
import gc
import re
import tempfile
from pathlib import Path
from urllib.parse import quote

from app.shared.infra.exceptions import AITeachMeError

_FENCE_RE = re.compile(r"^```(?P<lang>[A-Za-z0-9_-]*)\s*$")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_UL_RE = re.compile(r"^\s*[-*+]\s+(.+?)\s*$")
_OL_RE = re.compile(r"^\s*\d+[.)]\s+(.+?)\s*$")
_TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?[\s:|-]+\|[\s:|-]+\|?\s*$")
_LINK_RE = re.compile(r"!?\[([^\]]+)\]\(([^)]+)\)")
_BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")
_INLINE_CODE_RE = re.compile(r"`([^`]+)`")


def build_export_filename(*, subject: str, markdown: str, extension: str) -> str:
    """Build a safe download filename from the document heading."""

    title = ""
    for line in str(markdown or "").splitlines():
        match = _HEADING_RE.match(line.strip())
        if match is not None:
            title = match.group(2)
            break
    raw = title or subject or "knowledge_doc"
    cleaned = re.sub(r"[\\/:*?\"<>|\r\n\t]+", "_", raw).strip("._ ")
    cleaned = re.sub(r"\s+", "_", cleaned)[:80].strip("_")
    return f"{cleaned or 'knowledge_doc'}.{extension.lstrip('.')}"


def build_content_disposition(filename: str) -> str:
    """Return a Content-Disposition header that supports Chinese filenames."""

    fallback = re.sub(r"[^A-Za-z0-9._-]+", "_", filename).strip("_") or "knowledge_doc"
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename)}"


def markdown_to_pdf_bytes(*, markdown: str, title: str | None = None) -> bytes:
    """Render markdown into a paginated PDF using PyMuPDF."""

    if not str(markdown or "").strip():
        raise AITeachMeError(
            "当前知识文档为空，无法导出 PDF。",
            error_code="KNOWLEDGE_DOC_EMPTY",
            status_code=404,
        )
    try:
        import fitz
    except Exception as exc:  # pragma: no cover - deployment dependency guard.
        raise AITeachMeError(
            "当前环境缺少 PDF 导出依赖 PyMuPDF。",
            error_code="PDF_EXPORT_UNAVAILABLE",
            status_code=503,
        ) from exc

    html_text = _markdown_to_html(markdown, title=title)
    css = """
body {
  font-family: sans-serif;
  color: #1f2329;
  font-size: 11pt;
  line-height: 1.65;
}
h1 { font-size: 24pt; margin: 0 0 18pt; }
h2 { font-size: 17pt; margin: 22pt 0 10pt; border-bottom: 1px solid #dee0e3; padding-bottom: 4pt; }
h3 { font-size: 13.5pt; margin: 16pt 0 8pt; }
h4, h5, h6 { font-size: 12pt; margin: 12pt 0 6pt; }
p { margin: 0 0 8pt; }
ul, ol { margin: 0 0 8pt 18pt; }
li { margin: 0 0 3pt; }
blockquote { border-left: 3px solid #b4b8bf; margin: 8pt 0; padding: 4pt 0 4pt 10pt; color: #646a73; }
code { font-family: monospace; background: #f5f6f7; padding: 1pt 3pt; border-radius: 3pt; }
pre { font-family: monospace; white-space: pre-wrap; background: #f5f6f7; padding: 8pt; border-radius: 5pt; font-size: 9pt; }
table { border-collapse: collapse; width: 100%; margin: 8pt 0 12pt; }
th, td { border: 1px solid #dee0e3; padding: 4pt 6pt; vertical-align: top; }
th { background: #f5f6f7; font-weight: bold; }
a { color: #3370ff; text-decoration: none; }
.image-note { color: #646a73; font-style: italic; }
""".strip()

    page_rect = fitz.paper_rect("a4")
    content_rect = page_rect + (54, 54, -54, -54)
    story = fitz.Story(html_text, user_css=css)
    tmp_path = ""
    writer = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp_path = tmp.name
        writer = fitz.DocumentWriter(tmp_path)
        story.write(writer, lambda _rect_num, _filled: (page_rect, content_rect, fitz.Matrix(1, 1)))
        writer.close()
        writer = None
        return Path(tmp_path).read_bytes()
    finally:
        if writer is not None:
            writer.close()
        if tmp_path:
            gc.collect()
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except PermissionError:
                pass


def _markdown_to_html(markdown: str, *, title: str | None = None) -> str:
    lines = str(markdown or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    body: list[str] = []
    index = 0
    if title:
        body.append(f"<title>{html.escape(title)}</title>")
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if not stripped:
            index += 1
            continue

        fence = _FENCE_RE.match(stripped)
        if fence is not None:
            code_lines: list[str] = []
            index += 1
            while index < len(lines) and not lines[index].strip().startswith("```"):
                code_lines.append(lines[index])
                index += 1
            if index < len(lines):
                index += 1
            language = fence.group("lang")
            prefix = f"<div class=\"image-note\">{html.escape(language)} 图示源码：</div>" if language == "mermaid" else ""
            body.append(f"{prefix}<pre>{html.escape(chr(10).join(code_lines))}</pre>")
            continue

        if _is_table_start(lines, index):
            table_html, index = _consume_table(lines, index)
            body.append(table_html)
            continue

        heading = _HEADING_RE.match(stripped)
        if heading is not None:
            level = min(len(heading.group(1)), 4)
            body.append(f"<h{level}>{_inline_markdown_to_html(heading.group(2))}</h{level}>")
            index += 1
            continue

        if stripped.startswith(">"):
            block_lines: list[str] = []
            while index < len(lines) and lines[index].strip().startswith(">"):
                block_lines.append(lines[index].strip().lstrip(">").strip())
                index += 1
            body.append(f"<blockquote>{_inline_markdown_to_html(' '.join(block_lines))}</blockquote>")
            continue

        unordered = _UL_RE.match(line)
        ordered = _OL_RE.match(line)
        if unordered is not None or ordered is not None:
            tag = "ul" if unordered is not None else "ol"
            item_re = _UL_RE if tag == "ul" else _OL_RE
            items: list[str] = []
            while index < len(lines):
                item_match = item_re.match(lines[index])
                if item_match is None:
                    break
                items.append(f"<li>{_inline_markdown_to_html(item_match.group(1))}</li>")
                index += 1
            body.append(f"<{tag}>{''.join(items)}</{tag}>")
            continue

        paragraph_lines = [stripped]
        index += 1
        while index < len(lines):
            next_line = lines[index].strip()
            if not next_line or _HEADING_RE.match(next_line) or _FENCE_RE.match(next_line) or _UL_RE.match(next_line) or _OL_RE.match(next_line) or next_line.startswith(">") or _is_table_start(lines, index):
                break
            paragraph_lines.append(next_line)
            index += 1
        body.append(f"<p>{_inline_markdown_to_html(' '.join(paragraph_lines))}</p>")
    return "<html><body>" + "\n".join(body) + "</body></html>"


def _inline_markdown_to_html(text: str) -> str:
    escaped = html.escape(str(text or ""))

    def repl_link(match: re.Match[str]) -> str:
        label = html.escape(match.group(1))
        url = html.escape(match.group(2), quote=True)
        if match.group(0).startswith("!"):
            return f'<span class="image-note">[图片：{label}]</span>'
        return f'<a href="{url}">{label}</a>'

    escaped = _LINK_RE.sub(repl_link, escaped)
    escaped = _BOLD_RE.sub(r"<strong>\1</strong>", escaped)
    escaped = _INLINE_CODE_RE.sub(r"<code>\1</code>", escaped)
    return escaped


def _is_table_start(lines: list[str], index: int) -> bool:
    if index + 1 >= len(lines):
        return False
    return "|" in lines[index] and _TABLE_SEPARATOR_RE.match(lines[index + 1].strip()) is not None


def _consume_table(lines: list[str], index: int) -> tuple[str, int]:
    rows: list[list[str]] = []
    while index < len(lines) and "|" in lines[index].strip():
        if _TABLE_SEPARATOR_RE.match(lines[index].strip()) is None:
            cells = [cell.strip() for cell in lines[index].strip().strip("|").split("|")]
            rows.append(cells)
        index += 1
    if not rows:
        return "", index
    head = rows[0]
    body = rows[1:]
    head_html = "<tr>" + "".join(f"<th>{_inline_markdown_to_html(cell)}</th>" for cell in head) + "</tr>"
    body_html = "".join(
        "<tr>" + "".join(f"<td>{_inline_markdown_to_html(cell)}</td>" for cell in row) + "</tr>"
        for row in body
    )
    return f"<table><thead>{head_html}</thead><tbody>{body_html}</tbody></table>", index


__all__ = ["build_content_disposition", "build_export_filename", "markdown_to_pdf_bytes"]
