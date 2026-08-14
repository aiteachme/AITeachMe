"""MinerU Cloud API 集成（基于 Token），用于 ingest 工作流。

本模块实现了 `backend/playground/mineru_test.py` 里演示的核心流程：

1) POST /api/v4/file-urls/batch  -> 获取 batch_id + 预签名上传 URL
2) PUT 文件字节到预签名 URL
3) 轮询 GET /api/v4/extract-results/batch/{batch_id} 直到 state == done
4) 下载 `full_zip_url`（zip）并解压
5) 读取 `full.md`，并收集 `images/` 资源文件

设计说明：
- 使用 requests 对齐官方示例，避免预签名 URL 因默认 header 不一致而签名失配。
- 下载结果 zip 时，如果环境代理链路异常，会自动直连重试一次。
- 全部函数为同步实现；在异步工作流中请用 `asyncio.to_thread(...)` 调用。
- 解析结果解压到调用方提供的临时目录中，清理由调用方控制。

安全说明：
- MinerU Cloud 端点需要 API Token。
- 调用方应尽量避免将 Token 长期落盘到数据库。
"""

from __future__ import annotations

import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog

from app.workflows.ingest.parsing.lib.provider_contracts import ExternalProviderTimeoutError

DEFAULT_MINERU_BASE_URL = "https://mineru.net"
logger = structlog.get_logger(__name__)


def _get_requests():
    """延迟导入 requests。

    说明：MinerU 官方示例使用 requests；为了避免 urllib 的默认 header
    触发预签名 URL 的签名不匹配，这里也严格按示例方式发请求。
    """

    try:
        import requests  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "缺少 requests 依赖：请先安装 requests（例如在 backend 环境里执行 `pip install requests`）。"
        ) from exc
    return requests


@dataclass(frozen=True, slots=True)
class MinerURequestOptions:
    """用户可控的 MinerU 参数。"""

    api_token: str
    enable_formula: bool = True
    enable_table: bool = True
    is_ocr: bool = False
    model_version: str = "vlm"


@dataclass(frozen=True, slots=True)
class MinerUExtractedResult:
    """从 MinerU zip 解压得到的结果指针。"""

    markdown_path: Path
    images_dir: Path | None
    batch_id: str
    file_name: str


def _build_deadline(total_timeout_s: float | None) -> float | None:
    if total_timeout_s is None or total_timeout_s <= 0:
        return None
    return time.monotonic() + float(total_timeout_s)


def _remaining_timeout_s(
    *,
    deadline: float | None,
    fallback_timeout_s: float,
    provider_name: str,
    total_timeout_s: float | None,
) -> float:
    if deadline is None:
        return fallback_timeout_s
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ExternalProviderTimeoutError(provider_name, total_timeout_s or fallback_timeout_s)
    return max(min(float(fallback_timeout_s), remaining), 0.5)


def _raise_timeout_if_deadline_exceeded(
    *,
    deadline: float | None,
    provider_name: str,
    total_timeout_s: float | None,
) -> None:
    if deadline is not None and time.monotonic() >= deadline:
        raise ExternalProviderTimeoutError(provider_name, total_timeout_s or 0)


def parse_file_to_dir(
    *,
    file_path: Path,
    options: MinerURequestOptions,
    output_dir: Path,
    base_url: str = DEFAULT_MINERU_BASE_URL,
    poll_interval_s: float = 2.0,
    poll_timeout_s: float = 600.0,
    total_timeout_s: float | None = None,
) -> MinerUExtractedResult:
    """调用 MinerU Cloud 解析单个文件，并将 zip 解压到 output_dir。

    参数：
        file_path: 本地文件路径。
        options: MinerU Cloud 请求参数（包含 API Token）。
        output_dir: 下载 zip 的解压目录。
        base_url: MinerU API Base URL（默认 https://mineru.net）。
        poll_interval_s: 轮询间隔。
        poll_timeout_s: 最长等待 state == done/failed 的时间。

    返回：
        MinerUExtractedResult，包含 `full.md` 路径与可选 images 目录。

    异常：
        任一 API 调用失败会抛出 RuntimeError。
    """

    if not options.api_token.strip():
        raise RuntimeError(
            "MinerU API Token 为空：请在前端设置中填写 Token，或在后端环境变量 MINERU_API_TOKENS / MINERU_API_TOKEN 中配置 Token。"
        )

    base = base_url.rstrip("/")
    output_dir.mkdir(parents=True, exist_ok=True)
    deadline = _build_deadline(total_timeout_s)
    logger.info(
        "mineru_cloud_parse_requested",
        file_name=file_path.name,
        model_version=options.model_version,
        enable_formula=options.enable_formula,
        enable_table=options.enable_table,
        is_ocr=options.is_ocr,
    )

    # 1) 申请预签名上传 URL
    batch_id, upload_url, file_name = _request_batch_upload_url(
        base,
        options=options,
        file_name=file_path.name,
        deadline=deadline,
        total_timeout_s=total_timeout_s,
    )

    # 2) 上传文件字节到预签名 URL
    _put_file(
        upload_url,
        file_path,
        deadline=deadline,
        total_timeout_s=total_timeout_s,
    )
    logger.info("mineru_cloud_upload_completed", batch_id=batch_id, file_name=file_name)

    # 3) 轮询直到 done/failed
    zip_url = _poll_until_done(
        base,
        api_token=options.api_token,
        batch_id=batch_id,
        file_name=file_name,
        poll_interval_s=poll_interval_s,
        poll_timeout_s=poll_timeout_s,
        deadline=deadline,
        total_timeout_s=total_timeout_s,
    )

    # 4) 下载 zip
    zip_path = output_dir / "mineru_result.zip"
    _download_file(
        zip_url,
        zip_path,
        deadline=deadline,
        total_timeout_s=total_timeout_s,
    )
    logger.info("mineru_cloud_result_downloaded", batch_id=batch_id, zip_path=str(zip_path))

    # 5) 解压并定位 full.md 与 images/
    with zipfile.ZipFile(zip_path, "r") as zf:
        _safe_extract_zip(zf, output_dir)

    markdown_path = _find_first(output_dir, "full.md")
    if markdown_path is None:
        raise RuntimeError("MinerU 结果 zip 中未找到 full.md")

    images_dir = None
    # 通常 `images/` 与 `full.md` 同目录；这里做一次兜底搜索。
    candidate = markdown_path.parent / "images"
    if candidate.exists() and candidate.is_dir():
        images_dir = candidate
    else:
        found_images_dir = _find_first_dir(output_dir, "images")
        if found_images_dir is not None:
            images_dir = found_images_dir

    return MinerUExtractedResult(
        markdown_path=markdown_path,
        images_dir=images_dir,
        batch_id=batch_id,
        file_name=file_name,
    )


def _request_batch_upload_url(
    base: str,
    *,
    options: MinerURequestOptions,
    file_name: str,
    deadline: float | None,
    total_timeout_s: float | None,
) -> tuple[str, str, str]:
    # 严格对齐 backend/playground/mineru_test.py：requests.post(..., json=payload)
    requests = _get_requests()

    url = f"{base}/api/v4/file-urls/batch"
    payload = {
        "files": [{"name": file_name, "data_id": "doc_001"}],
        "model_version": options.model_version,
        "enable_formula": options.enable_formula,
        "enable_table": options.enable_table,
        "is_ocr": options.is_ocr,
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {options.api_token}",
    }

    try:
        resp = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=_remaining_timeout_s(
                deadline=deadline,
                fallback_timeout_s=60,
                provider_name="MinerU",
                total_timeout_s=total_timeout_s,
            ),
        )
    except Exception as exc:
        _raise_timeout_if_deadline_exceeded(
            deadline=deadline,
            provider_name="MinerU",
            total_timeout_s=total_timeout_s,
        )
        raise RuntimeError(f"MinerU 申请上传链接失败: {exc}") from exc

    if resp.status_code != 200:
        snippet = (resp.text or "").strip().replace("\r", " ").replace("\n", " ")[:600]
        raise RuntimeError(f"MinerU 申请上传链接失败: HTTP {resp.status_code}; resp={snippet}")

    try:
        decoded = resp.json()
    except Exception as exc:
        snippet = (resp.text or "")[:200]
        raise RuntimeError(f"MinerU 返回非 JSON: {snippet}") from exc

    if decoded.get("code") != 0:
        err_code = decoded.get("code")
        err_msg = decoded.get("msg")
        raise RuntimeError(f"MinerU 申请上传链接失败: {err_code}; {err_msg}")

    data = decoded.get("data") or {}
    batch_id = data.get("batch_id")
    file_urls = data.get("file_urls")
    if not batch_id or not isinstance(file_urls, list) or not file_urls:
        raise RuntimeError("MinerU 返回数据不完整：缺少 batch_id 或 file_urls")

    upload_url_value = file_urls[0]
    upload_url: str | None = None
    # 兼容 MinerU 返回 list[str] 或 list[dict] 两种可能结构。
    if isinstance(upload_url_value, str):
        upload_url = upload_url_value
    elif isinstance(upload_url_value, dict):
        candidate = upload_url_value.get("url") or upload_url_value.get("upload_url")
        if candidate:
            upload_url = str(candidate)

    if not upload_url or not upload_url.strip().startswith("http"):
        raise RuntimeError("MinerU 返回数据不完整：upload_url 无效")

    logger.info("mineru_cloud_batch_created", batch_id=str(batch_id), file_name=file_name)

    return str(batch_id), upload_url.strip(), file_name


def _poll_until_done(
    base: str,
    *,
    api_token: str,
    batch_id: str,
    file_name: str,
    poll_interval_s: float,
    poll_timeout_s: float,
    deadline: float | None,
    total_timeout_s: float | None,
) -> str:
    # 严格对齐 backend/playground/mineru_test.py：requests.get(..., headers=query_headers)
    requests = _get_requests()

    url = f"{base}/api/v4/extract-results/batch/{batch_id}"
    headers = {"Authorization": f"Bearer {api_token}"}

    started_at = time.monotonic()
    while True:
        try:
            resp = requests.get(
                url,
                headers=headers,
                timeout=_remaining_timeout_s(
                    deadline=deadline,
                    fallback_timeout_s=60,
                    provider_name="MinerU",
                    total_timeout_s=total_timeout_s,
                ),
            )
        except Exception as exc:
            _raise_timeout_if_deadline_exceeded(
                deadline=deadline,
                provider_name="MinerU",
                total_timeout_s=total_timeout_s,
            )
            raise RuntimeError(f"MinerU 轮询失败: {exc}") from exc

        if resp.status_code != 200:
            snippet = (resp.text or "").strip().replace("\r", " ").replace("\n", " ")[:600]
            raise RuntimeError(f"MinerU 轮询失败: HTTP {resp.status_code}; resp={snippet}")

        try:
            decoded = resp.json()
        except Exception as exc:
            snippet = (resp.text or "")[:200]
            raise RuntimeError(f"MinerU 轮询返回非 JSON: {snippet}") from exc

        if decoded.get("code") != 0:
            err_code = decoded.get("code")
            err_msg = decoded.get("msg")
            raise RuntimeError(f"MinerU 轮询失败: {err_code}; {err_msg}")

        data = decoded.get("data") or {}
        extract_results = data.get("extract_result") or []
        if not isinstance(extract_results, list):
            raise RuntimeError("MinerU 轮询返回数据格式异常：extract_result 不是数组")

        # 找到本文件的状态。
        matched: dict[str, Any] | None = None
        for item in extract_results:
            if not isinstance(item, dict):
                continue
            if item.get("file_name") == file_name:
                matched = item
                break
        if matched is None and extract_results:
            # MinerU 可能返回单元素数组；兜底取第一个。
            first = extract_results[0]
            matched = first if isinstance(first, dict) else None

        if matched is None:
            raise RuntimeError("MinerU 轮询返回为空：未找到文件状态")

        state = matched.get("state")
        if state == "done":
            zip_url = matched.get("full_zip_url")
            if not zip_url:
                raise RuntimeError("MinerU 返回 done 但缺少 full_zip_url")
            logger.info("mineru_cloud_poll_completed", batch_id=batch_id, file_name=file_name)
            return str(zip_url)

        if state == "failed":
            err_msg = matched.get("err_msg") or "unknown"
            raise RuntimeError(f"MinerU 解析失败: {err_msg}")

        elapsed = time.monotonic() - started_at
        if elapsed >= poll_timeout_s:
            raise RuntimeError("MinerU 解析超时：等待结果时间过长")

        sleep_budget_s = _remaining_timeout_s(
            deadline=deadline,
            fallback_timeout_s=poll_interval_s,
            provider_name="MinerU",
            total_timeout_s=total_timeout_s,
        )
        time.sleep(max(min(poll_interval_s, sleep_budget_s), 0.5))


def _put_file(
    url: str,
    file_path: Path,
    *,
    deadline: float | None,
    total_timeout_s: float | None,
) -> None:
    # 严格对齐 backend/playground/mineru_test.py：requests.put(target_url, data=f)
    requests = _get_requests()
    try:
        with file_path.open("rb") as f:
            resp = requests.put(
                url,
                data=f,
                timeout=_remaining_timeout_s(
                    deadline=deadline,
                    fallback_timeout_s=120,
                    provider_name="MinerU",
                    total_timeout_s=total_timeout_s,
                ),
            )
    except Exception as exc:
        _raise_timeout_if_deadline_exceeded(
            deadline=deadline,
            provider_name="MinerU",
            total_timeout_s=total_timeout_s,
        )
        raise RuntimeError(f"MinerU 上传失败: {exc}") from exc

    # 示例脚本把 200 当成功；但部分对象存储会返回 204。
    if resp.status_code not in (200, 201, 204):
        snippet = (resp.text or "").strip().replace("\r", " ").replace("\n", " ")[:600]
        raise RuntimeError(f"MinerU 上传失败: HTTP {resp.status_code}; resp={snippet}")


def _download_file(
    url: str,
    dest: Path,
    *,
    deadline: float | None,
    total_timeout_s: float | None,
) -> None:
    # 对齐示例：requests.get(zip_url, stream=True)
    requests = _get_requests()
    proxy_modes = (True, False) if requests.utils.get_environ_proxies(url) else (True,)
    last_exc: Exception | None = None

    for trust_env in proxy_modes:
        try:
            if dest.exists():
                dest.unlink()
            session = requests.Session()
            session.trust_env = trust_env
            with session.get(
                url,
                stream=True,
                timeout=_remaining_timeout_s(
                    deadline=deadline,
                    fallback_timeout_s=240,
                    provider_name="MinerU",
                    total_timeout_s=total_timeout_s,
                ),
            ) as resp:
                if resp.status_code != 200:
                    snippet = (resp.text or "").strip().replace("\r", " ").replace("\n", " ")[:600]
                    raise RuntimeError(f"MinerU 下载 zip 失败: HTTP {resp.status_code}; resp={snippet}")

                with dest.open("wb") as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                return
        except Exception as exc:
            _raise_timeout_if_deadline_exceeded(
                deadline=deadline,
                provider_name="MinerU",
                total_timeout_s=total_timeout_s,
            )
            last_exc = exc
            if dest.exists():
                dest.unlink()
            if trust_env and len(proxy_modes) > 1:
                logger.warning("mineru_download_retrying_without_proxy", error=str(exc))
                continue
            hint = ""
            if len(proxy_modes) > 1:
                hint = " 当前进程检测到环境代理，这更像是代理/CDN/TLS 链路异常，不像 API Token 问题。"
            raise RuntimeError(f"MinerU 下载 zip 失败: {exc}{hint}") from exc

    assert last_exc is not None
    raise RuntimeError(f"MinerU 下载 zip 失败: {last_exc}") from last_exc


def _request_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None,
    body_json: dict[str, Any] | None,
) -> dict[str, Any]:
    """兼容保留：当前流程已改用 requests，避免 urllib 的默认 header 陷阱。

    后续如果有其它内部调用还在使用该函数，可再逐步迁移。
    """

    requests = _get_requests()
    try:
        resp = requests.request(method, url, headers=headers, json=body_json, timeout=60)
    except Exception as exc:
        raise RuntimeError(f"MinerU 请求失败: {exc}") from exc

    if resp.status_code != 200:
        snippet = (resp.text or "").strip().replace("\r", " ").replace("\n", " ")[:600]
        raise RuntimeError(f"MinerU 请求失败: HTTP {resp.status_code}; resp={snippet}")

    try:
        decoded = resp.json()
    except Exception as exc:
        snippet = (resp.text or "")[:200]
        raise RuntimeError(f"MinerU 返回非 JSON: {snippet}") from exc

    if not isinstance(decoded, dict):
        raise RuntimeError("MinerU 返回 JSON 结构异常（非对象）")
    return decoded


def _safe_extract_zip(zf: zipfile.ZipFile, target_dir: Path) -> None:
    target_root = target_dir.resolve()
    for member in zf.infolist():
        member_path = target_dir / member.filename
        resolved = member_path.resolve()
        try:
            resolved.relative_to(target_root)
        except ValueError as exc:
            raise RuntimeError(f"MinerU result zip contains unsafe path: {member.filename!r}") from exc
    zf.extractall(target_dir)


def _find_first(root: Path, filename: str) -> Path | None:
    for path in root.rglob(filename):
        if path.is_file():
            return path
    return None


def _find_first_dir(root: Path, dirname: str) -> Path | None:
    for path in root.rglob(dirname):
        if path.is_dir():
            return path
    return None
