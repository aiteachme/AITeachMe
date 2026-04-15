"""DOCX archive helpers that do not rely on optional third-party packages."""

from __future__ import annotations

import posixpath
import zipfile
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree as ET

from pydantic import BaseModel, Field


_NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
}
_R_EMBED = f"{{{_NS['r']}}}embed"
_REL_ID = f"{{{_NS['rel']}}}Id"
_REL_TARGET = f"{{{_NS['rel']}}}Target"
_REL_TYPE = f"{{{_NS['rel']}}}Type"
_STYLE_VAL = f"{{{_NS['w']}}}val"


class DocxArchiveParagraph(BaseModel):
    """One paragraph extracted from a DOCX archive."""

    text: str = ""
    style_name: str | None = None
    image_rel_ids: list[str] = Field(default_factory=list)


class DocxArchiveImage(BaseModel):
    """One embedded image extracted from a DOCX archive."""

    rel_id: str
    internal_path: str
    blob: bytes


class DocxArchiveDocument(BaseModel):
    """Structured content extracted from a DOCX zip archive."""

    paragraphs: list[DocxArchiveParagraph] = Field(default_factory=list)
    images: list[DocxArchiveImage] = Field(default_factory=list)


class DocxArchiveSummary(BaseModel):
    """Lightweight document summary used by routing and classification."""

    paragraph_count: int = 0
    heading_count: int = 0
    total_text_chars: int = 0
    sample_text: str = ""


def load_docx_archive(path: str | Path) -> DocxArchiveDocument:
    """Load text paragraphs and embedded images from a DOCX archive."""

    archive_path = Path(path)
    with zipfile.ZipFile(archive_path) as archive:
        paragraphs = _read_document_paragraphs(archive)
        image_targets = _read_document_image_targets(archive)
        images = _read_document_images(archive, image_targets)
    return DocxArchiveDocument(paragraphs=paragraphs, images=images)


def summarize_docx_archive(path: str | Path) -> DocxArchiveSummary:
    """Build a quick text summary from the DOCX archive structure."""

    document = load_docx_archive(path)
    text_paragraphs = [item.text.strip() for item in document.paragraphs if item.text.strip()]
    heading_count = sum(1 for item in document.paragraphs if _is_heading_style(item.style_name))
    sample_text = "\n".join(text_paragraphs[:80])[:10000]
    return DocxArchiveSummary(
        paragraph_count=len(text_paragraphs),
        heading_count=heading_count,
        total_text_chars=sum(len(item) for item in text_paragraphs),
        sample_text=sample_text,
    )


def _read_document_paragraphs(archive: zipfile.ZipFile) -> list[DocxArchiveParagraph]:
    try:
        document_root = ET.fromstring(archive.read("word/document.xml"))
    except KeyError:
        return []

    paragraphs: list[DocxArchiveParagraph] = []
    for paragraph in document_root.findall(".//w:p", _NS):
        style_name = _extract_style_name(paragraph)
        text = "".join(node.text or "" for node in paragraph.findall(".//w:t", _NS)).strip()
        image_rel_ids = list(
            dict.fromkeys(
                rel_id
                for rel_id in (
                    blip.get(_R_EMBED)
                    for blip in paragraph.findall(".//a:blip", _NS)
                )
                if rel_id
            )
        )
        if not text and not image_rel_ids:
            continue
        paragraphs.append(
            DocxArchiveParagraph(
                text=text,
                style_name=style_name,
                image_rel_ids=image_rel_ids,
            )
        )
    return paragraphs


def _extract_style_name(paragraph: ET.Element) -> str | None:
    style = paragraph.find("./w:pPr/w:pStyle", _NS)
    if style is None:
        return None
    return style.get(_STYLE_VAL)


def _read_document_image_targets(archive: zipfile.ZipFile) -> dict[str, str]:
    try:
        rels_root = ET.fromstring(archive.read("word/_rels/document.xml.rels"))
    except KeyError:
        return {}

    image_targets: dict[str, str] = {}
    for relationship in rels_root.findall("./rel:Relationship", _NS):
        rel_type = relationship.get(_REL_TYPE, "")
        if "/image" not in rel_type:
            continue
        rel_id = relationship.get(_REL_ID)
        target = relationship.get(_REL_TARGET)
        if not rel_id or not target:
            continue
        image_targets[rel_id] = _normalize_archive_path("word", target)
    return image_targets


def _normalize_archive_path(base_dir: str, target: str) -> str:
    normalized = posixpath.normpath(
        target.lstrip("/")
        if target.startswith("/")
        else str(PurePosixPath(base_dir) / target)
    )
    return normalized


def _read_document_images(
    archive: zipfile.ZipFile,
    image_targets: dict[str, str],
) -> list[DocxArchiveImage]:
    images: list[DocxArchiveImage] = []
    for rel_id, internal_path in image_targets.items():
        try:
            blob = archive.read(internal_path)
        except KeyError:
            continue
        images.append(
            DocxArchiveImage(
                rel_id=rel_id,
                internal_path=internal_path,
                blob=blob,
            )
        )
    return images


def _is_heading_style(style_name: str | None) -> bool:
    if not style_name:
        return False
    normalized = style_name.lower().replace(" ", "")
    return normalized.startswith("heading")
