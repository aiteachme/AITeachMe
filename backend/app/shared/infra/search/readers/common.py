from __future__ import annotations

import ipaddress
import io
import re
import zipfile
from xml.etree import ElementTree
from urllib.parse import urljoin, urlparse

import httpx

from app.shared.infra.search.defaults import DEFAULT_SEARCH_SCRAPE_TIMEOUT_S
from app.shared.infra.search.types import ScrapedPage

_CORE_TITLE_QNAME = "{http://purl.org/dc/elements/1.1/}title"

DEFAULT_READER_HEADERS = {
    "User-Agent": "AITeachMe/0.2 (educational knowledge builder; contact: support@aiteachme.local)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,text/plain;q=0.8,*/*;q=0.7",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
}
_REDIRECT_STATUS_CODES = {301, 302, 303, 307, 308}
_MAX_FETCH_REDIRECTS = 5
_LOCALHOST_NAMES = {"localhost", "localhost.localdomain"}


def _validate_public_fetch_url(url: str) -> None:
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Only http(s) URLs with a hostname can be fetched.")

    hostname = parsed.hostname.rstrip(".").lower()
    if hostname in _LOCALHOST_NAMES or hostname.endswith(".localhost"):
        raise ValueError("Refusing to fetch localhost URLs.")

    try:
        ip = ipaddress.ip_address(hostname.strip("[]"))
    except ValueError:
        return
    if not ip.is_global:
        raise ValueError("Refusing to fetch non-public IP URLs.")


async def fetch_url(url: str, *, headers: dict[str, str] | None = None) -> httpx.Response:
    merged_headers = {**DEFAULT_READER_HEADERS, **(headers or {})}
    current_url = str(url or "").strip()

    async with httpx.AsyncClient(timeout=DEFAULT_SEARCH_SCRAPE_TIMEOUT_S, follow_redirects=False) as client:
        for _ in range(_MAX_FETCH_REDIRECTS + 1):
            _validate_public_fetch_url(current_url)
            response = await client.get(current_url, headers=merged_headers)
            status_code = getattr(response, "status_code", None)
            location = getattr(response, "headers", {}).get("location") if getattr(response, "headers", None) else None
            if status_code in _REDIRECT_STATUS_CODES and location:
                base_url = str(getattr(response, "url", None) or current_url)
                current_url = urljoin(base_url, location)
                continue
            response.raise_for_status()
            return response
    raise httpx.TooManyRedirects(f"Exceeded {_MAX_FETCH_REDIRECTS} redirects while fetching {url!r}.")


def build_error_page(url: str, *, error: Exception | str, content_type: str, reader_name: str) -> ScrapedPage:
    return ScrapedPage(
        url=url,
        success=False,
        error=str(error),
        content_type=content_type,
        reader_name=reader_name,
    )


def normalize_read_text(text: str, *, limit: int = 12000) -> str:
    normalized = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"[ \t]+\n", "\n", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    normalized = re.sub(r"[ \t]{2,}", " ", normalized)
    return normalized.strip()[:limit]


def open_zip_archive(payload: bytes) -> zipfile.ZipFile:
    return zipfile.ZipFile(io.BytesIO(payload))


def extract_core_title(archive: zipfile.ZipFile) -> str:
    try:
        with archive.open("docProps/core.xml") as handle:
            root = ElementTree.parse(handle).getroot()
    except Exception:
        return ""
    node = root.find(f".//{_CORE_TITLE_QNAME}")
    return (node.text or "").strip() if node is not None and node.text else ""


def extract_paragraphs_from_xml(xml_bytes: bytes, *, paragraph_qname: str, text_qname: str) -> list[str]:
    root = ElementTree.fromstring(xml_bytes)
    paragraphs: list[str] = []
    for paragraph in root.iter(paragraph_qname):
        parts = [(node.text or "").strip() for node in paragraph.iter(text_qname) if (node.text or "").strip()]
        joined = " ".join(parts).strip()
        if joined:
            paragraphs.append(joined)
    return paragraphs
