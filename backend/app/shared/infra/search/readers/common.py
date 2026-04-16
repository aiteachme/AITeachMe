from __future__ import annotations

import io
import re
import zipfile
from xml.etree import ElementTree

import httpx

from app.shared.infra.settings import get_settings
from app.shared.infra.search.types import ScrapedPage

_CORE_TITLE_QNAME = "{http://purl.org/dc/elements/1.1/}title"


async def fetch_url(url: str, *, headers: dict[str, str] | None = None) -> httpx.Response:
    settings = get_settings()
    async with httpx.AsyncClient(timeout=settings.search.scrape_timeout_s, follow_redirects=True) as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        return response


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
