"""Markdown normalization helpers for ingest workflows."""

from __future__ import annotations

import base64
from pathlib import Path
import re
from urllib.parse import unquote

from pydantic import BaseModel

from app.workflows.ingest.shared.parsing.utils import save_image_bytes


_HEADING_RE = re.compile(r"^(#{1,6})\s*(.*)", re.MULTILINE)
_FENCED_BLOCK_RE = re.compile(r"(^(`{3,})[^\n]*\n.*?^\2[ \t]*$)", re.MULTILINE | re.DOTALL)
_MARKDOWN_IMAGE_RE = re.compile(r"!\[(?P<alt>[^\]]*)\]\((?P<target>[^)]+)\)")
_HTML_IMAGE_RE = re.compile(r'(<img\b[^>]*?\bsrc=["\'])(?P<src>[^"\']+)(["\'])', re.IGNORECASE)
_OMITTED_PLACEHOLDER_RE = re.compile(r"(?:picture|image)\s*\[[^\]]+\]\s*intentionally omitted", re.IGNORECASE)


class CanonicalMarkdownResult(BaseModel):
    """Canonical markdown payload with normalization stats."""

    markdown: str
    rewritten_image_refs: int = 0
    extracted_data_images: int = 0
    appended_asset_images: int = 0


def canonicalize_markdown(
    raw: str,
    *,
    asset_dir: Path | None = None,
    asset_link_prefix: str | None = None,
    asset_name_prefix: str | None = None,
    asset_gallery_limit: int = 16,
) -> CanonicalMarkdownResult:
    """Normalize markdown into a stable downstream format."""

    if not raw:
        return CanonicalMarkdownResult(markdown="")

    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    normalized_parts: list[str] = []
    cursor = 0
    for match in _FENCED_BLOCK_RE.finditer(text):
        prefix = text[cursor:match.start()]
        if prefix:
            normalized_parts.append(_normalize_text_segment(prefix))
        normalized_parts.append(match.group(1))
        cursor = match.end()
    suffix = text[cursor:]
    if suffix:
        normalized_parts.append(_normalize_text_segment(suffix))

    normalized = "".join(normalized_parts).strip("\n")
    if asset_dir is not None:
        result = _canonicalize_assets(
            normalized,
            asset_dir=asset_dir,
            asset_link_prefix=asset_link_prefix,
            asset_name_prefix=asset_name_prefix,
            asset_gallery_limit=asset_gallery_limit,
        )
    else:
        result = CanonicalMarkdownResult(markdown=normalized)

    if result.markdown and not result.markdown.endswith("\n"):
        result.markdown = f"{result.markdown}\n"
    return result


def _normalize_text_segment(text: str) -> str:
    return _collapse_blank_lines(_normalize_non_fenced_markdown(text))


def _normalize_non_fenced_markdown(text: str) -> str:
    text = re.sub(r"^(#{1,6})([^\s#])", r"\1 \2", text, flags=re.MULTILINE)
    text = re.sub(r"^(\s*[-*])([^\s])", r"\1 \2", text, flags=re.MULTILINE)
    text = re.sub(r"^(\s*\d+\.)([^\s])", r"\1 \2", text, flags=re.MULTILINE)
    return _normalize_heading_levels(text)


def _collapse_blank_lines(text: str) -> str:
    cleaned: list[str] = []
    prev_blank = False
    for line in (item.rstrip() for item in text.splitlines()):
        is_blank = line == ""
        if is_blank and prev_blank:
            continue
        cleaned.append(line)
        prev_blank = is_blank

    while cleaned and cleaned[0] == "":
        cleaned.pop(0)
    while cleaned and cleaned[-1] == "":
        cleaned.pop()
    return "\n".join(cleaned)


def _normalize_heading_levels(text: str) -> str:
    """Keep heading levels continuous so downstream chunking is more stable."""

    levels_used = {len(match.group(1)) for match in _HEADING_RE.finditer(text)}
    if not levels_used:
        return text

    sorted_levels = sorted(levels_used)
    level_map = {
        old_level: min(new_level, 6)
        for new_level, old_level in enumerate(sorted_levels, start=1)
    }
    if all(old_level == new_level for old_level, new_level in level_map.items()):
        return text

    def _replace_heading(match: re.Match[str]) -> str:
        old_level = len(match.group(1))
        new_level = level_map.get(old_level, old_level)
        return f"{'#' * new_level} {match.group(2)}"

    return _HEADING_RE.sub(_replace_heading, text)


def _canonicalize_assets(
    markdown: str,
    *,
    asset_dir: Path,
    asset_link_prefix: str | None,
    asset_name_prefix: str | None,
    asset_gallery_limit: int,
) -> CanonicalMarkdownResult:
    prefix = asset_link_prefix or "../assets"
    asset_dir.mkdir(parents=True, exist_ok=True)
    asset_lookup = _build_asset_lookup(asset_dir, asset_name_prefix=asset_name_prefix)
    rewritten = 0
    extracted_data_images = 0

    def _replace_markdown_image(match: re.Match[str]) -> str:
        nonlocal rewritten
        nonlocal extracted_data_images
        alt = match.group("alt")
        target = match.group("target")
        path, suffix = _split_markdown_target(target)
        resolved = _resolve_asset_target(
            path,
            asset_lookup=asset_lookup,
            asset_dir=asset_dir,
            prefix=prefix,
            asset_name_prefix=asset_name_prefix,
        )
        if resolved is None:
            return match.group(0)
        if resolved.extracted_data_image:
            extracted_data_images += 1
            asset_lookup[resolved.asset_name.lower()] = resolved.asset_name
        rewritten += 1
        return f"![{alt}]({resolved.url}{suffix})"

    rewritten_markdown = _MARKDOWN_IMAGE_RE.sub(_replace_markdown_image, markdown)

    def _replace_html_image(match: re.Match[str]) -> str:
        nonlocal rewritten
        nonlocal extracted_data_images
        src = match.group("src")
        resolved = _resolve_asset_target(
            src,
            asset_lookup=asset_lookup,
            asset_dir=asset_dir,
            prefix=prefix,
            asset_name_prefix=asset_name_prefix,
        )
        if resolved is None:
            return match.group(0)
        if resolved.extracted_data_image:
            extracted_data_images += 1
            asset_lookup[resolved.asset_name.lower()] = resolved.asset_name
        rewritten += 1
        return f"{match.group(1)}{resolved.url}{match.group(3)}"

    rewritten_markdown = _HTML_IMAGE_RE.sub(_replace_html_image, rewritten_markdown)

    appended_asset_images = 0
    has_omitted_placeholders = bool(_OMITTED_PLACEHOLDER_RE.search(rewritten_markdown))
    if asset_lookup and f"{prefix}/" not in rewritten_markdown and not has_omitted_placeholders:
        sorted_assets = sorted(asset_lookup.values())[: max(asset_gallery_limit, 0)]
        gallery = "\n".join(
            f"![Extracted image {index}]({prefix}/{name})"
            for index, name in enumerate(sorted_assets, start=1)
        )
        if gallery:
            appended_asset_images = len(sorted_assets)
            rewritten_markdown = f"{rewritten_markdown.strip()}\n\n## Extracted Images\n\n{gallery}"

    return CanonicalMarkdownResult(
        markdown=rewritten_markdown.strip(),
        rewritten_image_refs=rewritten,
        extracted_data_images=extracted_data_images,
        appended_asset_images=appended_asset_images,
    )


class _ResolvedAssetPath(BaseModel):
    url: str
    asset_name: str
    extracted_data_image: bool = False


def _build_asset_lookup(asset_dir: Path, *, asset_name_prefix: str | None = None) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for item in asset_dir.iterdir():
        if not item.is_file():
            continue
        if asset_name_prefix and not item.name.startswith(asset_name_prefix):
            continue
        lookup[item.name.lower()] = item.name
        if asset_name_prefix and item.name.startswith(asset_name_prefix):
            stripped_name = item.name[len(asset_name_prefix) :]
            if stripped_name:
                lookup.setdefault(stripped_name.lower(), item.name)
    return lookup


def _split_markdown_target(target: str) -> tuple[str, str]:
    trimmed = target.strip()
    if trimmed.startswith("<") and ">" in trimmed:
        end = trimmed.find(">")
        return trimmed[1:end], trimmed[end + 1 :]
    match = re.match(r'(?P<path>\S+)(?P<suffix>\s+["\'][^"\']*["\'])?$', trimmed)
    if match is None:
        return trimmed, ""
    return match.group("path"), match.group("suffix") or ""


def _resolve_asset_target(
    target: str,
    *,
    asset_lookup: dict[str, str],
    asset_dir: Path,
    prefix: str,
    asset_name_prefix: str | None = None,
) -> _ResolvedAssetPath | None:
    path = target.strip()
    if not path:
        return None

    lowered = path.lower()
    if lowered.startswith(("http://", "https://", "mailto:", "tel:", "#")):
        return None

    if lowered.startswith("data:image/"):
        extracted = _extract_data_uri_image(
            path,
            asset_dir,
            asset_name_prefix=asset_name_prefix,
        )
        if extracted is None:
            return None
        return _ResolvedAssetPath(
            url=f"{prefix}/{extracted}",
            asset_name=extracted,
            extracted_data_image=True,
        )

    if lowered.startswith(("../assets/", "../../assets/", "/_assets/")):
        return None

    filename = asset_lookup.get(Path(unquote(path)).name.lower())
    if filename is None:
        return None
    return _ResolvedAssetPath(url=f"{prefix}/{filename}", asset_name=filename)


def _extract_data_uri_image(
    data_uri: str,
    asset_dir: Path,
    *,
    asset_name_prefix: str | None = None,
) -> str | None:
    if ";base64," not in data_uri:
        return None
    header, encoded = data_uri.split(";base64,", 1)
    mime = header.replace("data:", "", 1).lower()
    ext = _image_ext_from_mime(mime)
    if ext is None:
        return None
    try:
        image_bytes = base64.b64decode(encoded, validate=False)
    except Exception:
        return None
    if not image_bytes:
        return None
    return save_image_bytes(
        image_bytes,
        asset_dir,
        name_hint="embedded_img",
        ext=ext,
        name_prefix=asset_name_prefix or "",
    )


def _image_ext_from_mime(mime: str) -> str | None:
    mapping = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/webp": ".webp",
        "image/gif": ".gif",
        "image/bmp": ".bmp",
        "image/tiff": ".tiff",
    }
    return mapping.get(mime)
