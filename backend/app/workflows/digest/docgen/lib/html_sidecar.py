"""Utilities for generated single-file HTML sidecars."""

from __future__ import annotations

import html as html_lib
import re

_FENCE_RE = re.compile(r"^```(?:html)?\s*\n(?P<body>.*)\n```$", re.IGNORECASE | re.DOTALL)
_DOCTYPE_RE = re.compile(r"<!doctype\s+html[^>]*>", re.IGNORECASE)
_HTML_DOC_RE = re.compile(r"<!doctype\s+html[^>]*>.*?</html>", re.IGNORECASE | re.DOTALL)
_HEAD_RE = re.compile(r"<head(?:\s[^>]*)?>(?P<body>.*?)</head>", re.IGNORECASE | re.DOTALL)
_BODY_RE = re.compile(r"<body(?:\s[^>]*)?>(?P<body>.*?)</body>", re.IGNORECASE | re.DOTALL)
_TITLE_RE = re.compile(r"<title(?:\s[^>]*)?>.*?</title>", re.IGNORECASE | re.DOTALL)
_SCRIPT_STYLE_RE = re.compile(r"<(?P<tag>script|style)\b[^>]*>.*?</(?P=tag)>", re.IGNORECASE | re.DOTALL)
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


def strip_html_fence(text: str) -> str:
    cleaned = str(text or "").strip()
    match = _FENCE_RE.match(cleaned)
    if match is not None:
        return match.group("body").strip()
    return cleaned


def _structure_text(text: str) -> str:
    text = _COMMENT_RE.sub("", text)
    return _SCRIPT_STYLE_RE.sub(lambda match: f"<{match.group('tag')}></{match.group('tag')}>", text)


def _count_tag(text: str, tag: str) -> int:
    return len(re.findall(rf"<{tag}\b", _structure_text(text), re.IGNORECASE))


def _protect_script_style(text: str) -> tuple[str, list[tuple[str, str]]]:
    blocks: list[tuple[str, str]] = []

    def _replace(match: re.Match[str]) -> str:
        token = f"__ATM_HTML_BLOCK_{len(blocks)}__"
        blocks.append((token, match.group(0)))
        return token

    return _SCRIPT_STYLE_RE.sub(_replace, text), blocks


def _restore_script_style(text: str, blocks: list[tuple[str, str]]) -> str:
    restored = text
    for token, block in blocks:
        restored = restored.replace(token, block)
    return restored


def _extract_main_document(text: str) -> str:
    matches = list(_HTML_DOC_RE.finditer(text))
    if not matches:
        return text
    return max(matches, key=lambda match: len(match.group(0))).group(0).strip()


def _strip_document_shell(fragment: str, *, drop_head_blocks: bool) -> str:
    cleaned, protected_blocks = _protect_script_style(str(fragment or ""))
    cleaned = _DOCTYPE_RE.sub("", cleaned)
    cleaned = re.sub(r"</?html(?:\s[^>]*)?>", "", cleaned, flags=re.IGNORECASE)
    if drop_head_blocks:
        cleaned = _HEAD_RE.sub("", cleaned)
    cleaned = re.sub(r"</?head(?:\s[^>]*)?>", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"</?body(?:\s[^>]*)?>", "", cleaned, flags=re.IGNORECASE)
    return _restore_script_style(cleaned, protected_blocks).strip()


def _rebuild_single_document(text: str, *, title: str) -> str:
    structural_text, protected_blocks = _protect_script_style(text)
    head_bodies = [
        _restore_script_style(match.group("body"), protected_blocks).strip()
        for match in _HEAD_RE.finditer(structural_text)
        if match.group("body").strip()
    ]
    head_body = "\n".join(head_bodies)
    body_matches = list(_BODY_RE.finditer(structural_text))
    if body_matches:
        body = "\n".join(
            _strip_document_shell(_restore_script_style(match.group("body"), protected_blocks), drop_head_blocks=True)
            for match in body_matches
            if match.group("body").strip()
        )
    else:
        body = re.sub(r"<!doctype\s+html[^>]*>", "", structural_text, flags=re.IGNORECASE)
        body = re.sub(r"</?html(?:\s[^>]*)?>", "", body, flags=re.IGNORECASE)
        body = _HEAD_RE.sub("", body).strip()
        body = _restore_script_style(body, protected_blocks)
        body = _strip_document_shell(body, drop_head_blocks=True)

    head_body = _strip_document_shell(head_body, drop_head_blocks=True)
    if not _TITLE_RE.search(head_body):
        head_body = f"<title>{html_lib.escape(title)}</title>\n{head_body}".strip()
    if not re.search(r"<meta[^>]+charset\s*=", head_body, re.IGNORECASE):
        head_body = '<meta charset="utf-8" />\n' + head_body
    if not re.search(r"<meta[^>]+name\s*=\s*['\"]viewport['\"]", head_body, re.IGNORECASE):
        head_body += '\n<meta name="viewport" content="width=device-width, initial-scale=1" />'

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
{head_body.strip()}
</head>
<body>
{body.strip()}
</body>
</html>"""


def normalize_single_file_html(
    html: str,
    *,
    title: str,
    allow_scripts: bool,
) -> str:
    """Normalize a model-produced sidecar into one complete HTML document."""

    cleaned = strip_html_fence(html).replace("\r\n", "\n").replace("\r", "\n").strip()
    cleaned = _extract_main_document(cleaned)
    cleaned = re.sub(r"<script[^>]+src=[\"'][^\"']+[\"'][^>]*>\s*</script>", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"<link[^>]+href=[\"']https?://[^\"']+[\"'][^>]*>", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"<img[^>]+src=[\"']https?://[^\"']+[\"'][^>]*>", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"(fetch|XMLHttpRequest|WebSocket|localStorage|sessionStorage)\s*\(", "void(", cleaned)
    if not allow_scripts:
        cleaned = re.sub(r"<script\b[^>]*>.*?</script>", "", cleaned, flags=re.IGNORECASE | re.DOTALL)
        cleaned = re.sub(r"\s+on[a-z]+\s*=\s*(['\"]).*?\1", "", cleaned, flags=re.IGNORECASE | re.DOTALL)

    if "<!DOCTYPE html>" not in cleaned[:80]:
        cleaned = "<!DOCTYPE html>\n" + cleaned
    if "<html" not in cleaned.lower():
        cleaned = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{html_lib.escape(title)}</title>
</head>
<body>
{cleaned}
</body>
</html>"""
    if not re.search(r"<meta[^>]+name\s*=\s*['\"]viewport['\"]", cleaned, re.IGNORECASE):
        cleaned = re.sub(
            r"(<head(?:\s[^>]*)?>)",
            r'\1\n  <meta name="viewport" content="width=device-width, initial-scale=1" />',
            cleaned,
            count=1,
            flags=re.IGNORECASE,
        )

    if (
        len(_DOCTYPE_RE.findall(cleaned)) != 1
        or _count_tag(cleaned, "html") != 1
        or _count_tag(cleaned, "head") != 1
        or _count_tag(cleaned, "body") != 1
    ):
        cleaned = _rebuild_single_document(cleaned, title=title)

    return cleaned.strip() + "\n"


__all__ = ["normalize_single_file_html", "strip_html_fence"]
