"""PaddleOCR Cloud API integration for ingest workflows.

This module mirrors the MinerU external-provider integration pattern:
- submit one job with a server-side API token
- poll until the extraction completes
- download markdown/image assets into a caller-owned temp directory

All functions are synchronous so ingest workflows should call them via
``asyncio.to_thread(...)``.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

import structlog

DEFAULT_PADDLE_OCR_JOB_URL = "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs"
DEFAULT_PADDLE_OCR_MODEL = "PaddleOCR-VL-1.5"
DEFAULT_PADDLE_OCR_OPTIONAL_PAYLOAD = {
    "useDocOrientationClassify": False,
    "useDocUnwarping": False,
    "useChartRecognition": False,
}

logger = structlog.get_logger(__name__)
_MARKDOWN_IMAGE_RE = re.compile(r"!\[(?P<alt>[^\]]*)\]\((?P<target>[^)]+)\)")
_HTML_IMAGE_RE = re.compile(r'(<img\b[^>]*?\bsrc=["\'])(?P<src>[^"\']+)(["\'])', re.IGNORECASE)


def _get_requests():
    try:
        import requests  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "缺少 requests 依赖：请先安装 requests（例如在 backend 环境里执行 `pip install requests`）。"
        ) from exc
    return requests


@dataclass(frozen=True, slots=True)
class PaddleOCRRequestOptions:
    api_token: str
    model: str = DEFAULT_PADDLE_OCR_MODEL


@dataclass(frozen=True, slots=True)
class PaddleOCRExtractedResult:
    markdown_path: Path
    images_dir: Path | None
    job_id: str
    model: str


def parse_file_to_dir(
    *,
    file_path: Path,
    options: PaddleOCRRequestOptions,
    output_dir: Path,
    job_url: str = DEFAULT_PADDLE_OCR_JOB_URL,
    poll_interval_s: float = 5.0,
    poll_timeout_s: float = 600.0,
) -> PaddleOCRExtractedResult:
    """Submit one PaddleOCR Cloud job and materialize a canonical markdown bundle."""

    if not options.api_token.strip():
        raise RuntimeError(
            "PaddleOCR API Token 为空：请在前端设置中填写 Token，或在后端环境变量 PADDLE_OCR_API_TOKEN 中配置 Token。"
        )
    if not file_path.exists():
        raise RuntimeError(f"PaddleOCR 输入文件不存在：{file_path}")

    requests = _get_requests()
    output_dir.mkdir(parents=True, exist_ok=True)
    images_dir = output_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    headers = {
        "Authorization": f"bearer {options.api_token}",
    }
    data = {
        "model": options.model,
        "optionalPayload": json.dumps(DEFAULT_PADDLE_OCR_OPTIONAL_PAYLOAD),
    }

    logger.info("paddle_ocr_cloud_parse_requested", file_name=file_path.name, model=options.model)

    try:
        with file_path.open("rb") as file_obj:
            job_response = requests.post(
                job_url,
                headers=headers,
                data=data,
                files={"file": file_obj},
                timeout=120,
            )
    except Exception as exc:
        raise RuntimeError(f"PaddleOCR 提交任务失败: {exc}") from exc

    if job_response.status_code != 200:
        snippet = (job_response.text or "").strip().replace("\r", " ").replace("\n", " ")[:600]
        raise RuntimeError(f"PaddleOCR 提交任务失败: HTTP {job_response.status_code}; resp={snippet}")

    try:
        job_payload = job_response.json()
        job_id = str(job_payload["data"]["jobId"])
    except Exception as exc:
        snippet = (job_response.text or "")[:240]
        raise RuntimeError(f"PaddleOCR 返回数据异常: {snippet}") from exc

    jsonl_url = _poll_until_done(
        job_url=job_url,
        headers=headers,
        job_id=job_id,
        poll_interval_s=poll_interval_s,
        poll_timeout_s=poll_timeout_s,
    )
    markdown_text = _download_and_materialize_jsonl(
        jsonl_url=jsonl_url,
        images_dir=images_dir,
    )
    markdown_path = output_dir / "full.md"
    markdown_path.write_text(markdown_text, encoding="utf-8")

    return PaddleOCRExtractedResult(
        markdown_path=markdown_path,
        images_dir=images_dir if any(images_dir.iterdir()) else None,
        job_id=job_id,
        model=options.model,
    )


def _poll_until_done(
    *,
    job_url: str,
    headers: dict[str, str],
    job_id: str,
    poll_interval_s: float,
    poll_timeout_s: float,
) -> str:
    requests = _get_requests()
    started_at = time.monotonic()

    while True:
        try:
            job_result_response = requests.get(f"{job_url}/{job_id}", headers=headers, timeout=60)
        except Exception as exc:
            raise RuntimeError(f"PaddleOCR 轮询失败: {exc}") from exc

        if job_result_response.status_code != 200:
            snippet = (job_result_response.text or "").strip().replace("\r", " ").replace("\n", " ")[:600]
            raise RuntimeError(f"PaddleOCR 轮询失败: HTTP {job_result_response.status_code}; resp={snippet}")

        try:
            payload = job_result_response.json()["data"]
        except Exception as exc:
            snippet = (job_result_response.text or "")[:240]
            raise RuntimeError(f"PaddleOCR 轮询返回数据异常: {snippet}") from exc

        state = str(payload.get("state") or "")
        if state == "done":
            result_url = payload.get("resultUrl") or {}
            jsonl_url = result_url.get("jsonUrl")
            if not jsonl_url:
                raise RuntimeError("PaddleOCR 返回 done 但缺少 resultUrl.jsonUrl")
            logger.info("paddle_ocr_cloud_poll_completed", job_id=job_id)
            return str(jsonl_url)

        if state == "failed":
            raise RuntimeError(f"PaddleOCR 解析失败: {payload.get('errorMsg') or 'unknown'}")

        if time.monotonic() - started_at >= poll_timeout_s:
            raise RuntimeError("PaddleOCR 解析超时：等待结果时间过长")

        time.sleep(max(poll_interval_s, 0.5))


def _download_and_materialize_jsonl(
    *,
    jsonl_url: str,
    images_dir: Path,
) -> str:
    requests = _get_requests()

    try:
        jsonl_response = requests.get(jsonl_url, timeout=240)
        jsonl_response.raise_for_status()
    except Exception as exc:
        raise RuntimeError(f"PaddleOCR 下载结果失败: {exc}") from exc

    sections: list[str] = []
    image_counter = 0

    for line in jsonl_response.text.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            result = json.loads(line)["result"]
        except Exception as exc:
            raise RuntimeError(f"PaddleOCR JSONL 解析失败: {exc}") from exc

        for layout_index, layout_result in enumerate(result.get("layoutParsingResults") or [], start=1):
            markdown_payload = layout_result.get("markdown") or {}
            markdown_block = (markdown_payload.get("text") or "").strip()
            markdown_images = markdown_payload.get("images") or {}
            output_images = layout_result.get("outputImages") or {}

            if markdown_block:
                referenced_names = _collect_referenced_image_names(markdown_block)
                rename_map: dict[str, str] = {}
                skipped_markdown_images = 0

                for raw_name, image_url in markdown_images.items():
                    normalized_name = Path(str(raw_name)).name
                    if normalized_name.lower() not in referenced_names:
                        skipped_markdown_images += 1
                        continue
                    image_counter += 1
                    filename = _download_image(
                        image_url=str(image_url),
                        dest_dir=images_dir,
                        preferred_name=f"{image_counter:03d}_{normalized_name}",
                    )
                    rename_map[normalized_name.lower()] = filename
                    logger.info("paddle_ocr_cloud_markdown_image_saved", filename=filename, raw_name=normalized_name)

                if rename_map:
                    markdown_block = _rewrite_markdown_image_names(markdown_block, rename_map)
                if skipped_markdown_images:
                    logger.info(
                        "paddle_ocr_cloud_markdown_images_skipped",
                        skipped=skipped_markdown_images,
                        layout_index=layout_index,
                    )

                if output_images:
                    logger.info(
                        "paddle_ocr_cloud_output_images_ignored",
                        ignored=len(output_images),
                        layout_index=layout_index,
                    )

                sections.append(markdown_block)

            if markdown_block:
                sections.append("")

    combined = "\n".join(section for section in sections if section is not None).strip()
    if not combined:
        raise RuntimeError("PaddleOCR 返回空 Markdown")
    if not combined.endswith("\n"):
        combined += "\n"
    return combined


def _download_image(*, image_url: str, dest_dir: Path, preferred_name: str) -> str:
    requests = _get_requests()
    try:
        response = requests.get(image_url, timeout=120)
        response.raise_for_status()
    except Exception as exc:
        raise RuntimeError(f"PaddleOCR 下载图片失败: {exc}") from exc

    filename = _dedupe_filename(dest_dir=dest_dir, preferred_name=preferred_name)
    (dest_dir / filename).write_bytes(response.content)
    return filename


def _collect_referenced_image_names(markdown: str) -> set[str]:
    referenced: set[str] = set()

    for match in _MARKDOWN_IMAGE_RE.finditer(markdown):
        target = _extract_markdown_target_path(match.group("target"))
        if not target:
            continue
        referenced.add(Path(unquote(target)).name.lower())

    for match in _HTML_IMAGE_RE.finditer(markdown):
        src = (match.group("src") or "").strip()
        if not src:
            continue
        referenced.add(Path(unquote(src)).name.lower())

    return referenced


def _rewrite_markdown_image_names(markdown: str, rename_map: dict[str, str]) -> str:
    if not rename_map:
        return markdown

    def _replace_markdown_image(match):
        target = match.group("target")
        path, suffix = _split_markdown_target(target)
        replaced = _replace_target_basename(path, rename_map)
        if replaced == path:
            return match.group(0)
        return f"![{match.group('alt')}]({replaced}{suffix})"

    rewritten = _MARKDOWN_IMAGE_RE.sub(_replace_markdown_image, markdown)

    def _replace_html_image(match):
        src = match.group("src")
        replaced = _replace_target_basename(src, rename_map)
        if replaced == src:
            return match.group(0)
        return f"{match.group(1)}{replaced}{match.group(3)}"

    return _HTML_IMAGE_RE.sub(_replace_html_image, rewritten)


def _split_markdown_target(target: str) -> tuple[str, str]:
    trimmed = target.strip()
    if trimmed.startswith("<") and ">" in trimmed:
        end = trimmed.find(">")
        return trimmed[1:end], trimmed[end + 1 :]
    match = re.match(r'(?P<path>\S+)(?P<suffix>\s+["\'][^"\']*["\'])?$', trimmed)
    if match is None:
        return trimmed, ""
    return match.group("path"), match.group("suffix") or ""


def _extract_markdown_target_path(target: str) -> str:
    path, _ = _split_markdown_target(target)
    return path.strip()


def _replace_target_basename(target: str, rename_map: dict[str, str]) -> str:
    trimmed = target.strip()
    if not trimmed:
        return target

    quote_prefix = ""
    quote_suffix = ""
    if trimmed.startswith("<") and trimmed.endswith(">"):
        quote_prefix = "<"
        quote_suffix = ">"
        trimmed = trimmed[1:-1].strip()

    path_obj = Path(unquote(trimmed))
    filename = path_obj.name
    replacement = rename_map.get(filename.lower())
    if replacement is None:
        return target

    parent = path_obj.parent
    replaced_path = replacement if str(parent) in ("", ".") else f"{parent.as_posix()}/{replacement}"
    return f"{quote_prefix}{replaced_path}{quote_suffix}"


def _dedupe_filename(*, dest_dir: Path, preferred_name: str) -> str:
    candidate = _sanitize_filename(preferred_name)
    if not (dest_dir / candidate).exists():
        return candidate

    stem = Path(candidate).stem
    suffix = Path(candidate).suffix
    index = 1
    while True:
        next_candidate = f"{stem}_{index}{suffix}"
        if not (dest_dir / next_candidate).exists():
            return next_candidate
        index += 1


def _sanitize_filename(value: str) -> str:
    sanitized = "".join(char if char not in '\\/:*?"<>|' else "_" for char in value.strip())
    return sanitized or f"image_{int(time.time())}.png"


__all__ = [
    "DEFAULT_PADDLE_OCR_JOB_URL",
    "DEFAULT_PADDLE_OCR_MODEL",
    "PaddleOCRExtractedResult",
    "PaddleOCRRequestOptions",
    "parse_file_to_dir",
]
