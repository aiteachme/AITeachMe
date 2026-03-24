"""Lightweight ingest classification used to plan parser routing."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import structlog
from pydantic import BaseModel, Field

from app.workflows.ingest.parsing.docx_archive import summarize_docx_archive
from app.workflows.ingest.parsing.formats import (
    categorize_text_extension,
    is_image_extension,
    is_markitdown_generic_extension,
    is_text_extension,
    normalize_extension,
)
from app.workflows.ingest.parsing.text import is_probably_text_file, read_text_file


try:
    import fitz
except ImportError:
    fitz = None

try:
    from docx import Document
except ImportError:
    Document = None

try:
    from pptx import Presentation
except ImportError:
    Presentation = None


logger = structlog.get_logger()

_ZH_RE = re.compile(r"[\u4e00-\u9fff]")
_EN_RE = re.compile(r"[a-zA-Z]")
_HEADING_LIKE_RE = re.compile(
    r"^(第[\u4e00-\u9fff0-9]+[章节篇]|Chapter\s+\d+|Section\s+\d+|\d+[\.\s])",
    re.MULTILINE,
)
_MARKDOWN_HEADING_RE = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_TABLE_LIKE_RE = re.compile(r"\|.*\|.*\||\+[-=]+\+", re.MULTILINE)
_FORMULA_RE = re.compile(r"(?:\\frac|\\sum|\\int|\\sqrt|∑|∫|≤|≥)")


class ClassificationResult(BaseModel):
    """Classification output consumed by the ingest workflow."""

    file_category: str
    text_density: float = 0.0
    ocr_ratio: float = 0.0
    image_page_ratio: float = 0.0
    heading_count: int = 0
    estimated_pages: int = 0
    detected_language: str = "unknown"
    has_tables: bool = False
    has_formulas: bool = False
    recommended_parser: str = ""
    fallback_parsers: list[str] = Field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return self.model_dump()


def classify_file(file_path: str | Path, filetype: str) -> ClassificationResult:
    """Inspect a file quickly and choose a parser chain."""

    path = Path(file_path)
    extension = normalize_extension(filetype)

    if extension == ".pdf":
        return _classify_pdf(path)
    if extension in {".ppt", ".pptx"}:
        return _classify_pptx(path)
    if extension == ".docx":
        return _classify_docx(path)
    if is_text_extension(extension):
        return _classify_text_file(path, extension)
    if is_markitdown_generic_extension(extension):
        return ClassificationResult(
            file_category="markitdown_generic",
            recommended_parser="markitdown_generic",
        )
    if is_image_extension(extension):
        return ClassificationResult(
            file_category="image",
            estimated_pages=1,
            recommended_parser="llm_vision",
        )
    if is_probably_text_file(path):
        return _classify_text_file(path, extension)
    return ClassificationResult(
        file_category="unknown",
        recommended_parser="markitdown",
    )


def _classify_pdf(path: Path) -> ClassificationResult:
    if fitz is None:
        return ClassificationResult(
            file_category="text_pdf",
            recommended_parser="pymupdf4llm",
            fallback_parsers=["markitdown", "pymupdf_native"],
        )

    document = fitz.open(str(path))
    total_pages = len(document)
    sample_pages = min(total_pages, 10)

    total_chars = 0
    image_heavy_pages = 0
    drawing_heavy_pages = 0
    all_text_parts: list[str] = []

    formula_heavy_pages = 0
    for page_index in range(sample_pages):
        page = document[page_index]
        text = page.get_text("text") or ""
        char_count = len(text.strip())
        total_chars += char_count

        images = page.get_images(full=True)
        large_images = [image for image in images if _is_large_image(document, image[0])]
        if char_count < 50 and large_images:
            image_heavy_pages += 1

        drawing_count = len([r for r in page.cluster_drawings() if _is_meaningful_drawing_rect(r)])
        if drawing_count > 0:
            drawing_heavy_pages += 1

        # 检测公式密集页：drawing 多 + 文字少
        if drawing_count >= 3 and char_count < 500:
            formula_heavy_pages += 1

        all_text_parts.append(text)

    document.close()

    all_text = "".join(all_text_parts)
    avg_density = total_chars / sample_pages if sample_pages else 0
    image_ratio = image_heavy_pages / sample_pages if sample_pages else 0
    drawing_ratio = drawing_heavy_pages / sample_pages if sample_pages else 0
    formula_ratio = formula_heavy_pages / sample_pages if sample_pages else 0
    detected_language = _detect_language(all_text[:5000])
    heading_count = len(_HEADING_LIKE_RE.findall(all_text[:10000]))
    has_tables = bool(_TABLE_LIKE_RE.search(all_text[:10000]))
    has_formulas = bool(_FORMULA_RE.search(all_text[:10000])) or drawing_ratio > 0.3

    # 优化分类逻辑：识别数学试卷类文档
    if avg_density < 30:
        file_category = "scanned_pdf"
        recommended_parser = "pymupdf_ocr_vision"
        fallback_parsers = ["pymupdf_native", "markitdown"]
    elif formula_ratio > 0.5 and avg_density < 300:
        # 数学试卷类：公式密集 + 文字适中
        file_category = "formula_heavy_pdf"
        recommended_parser = "pymupdf_native"
        fallback_parsers = ["pymupdf4llm", "markitdown"]
    elif image_ratio > 0.5 or (drawing_ratio > 0.6 and avg_density > 200):
        # 图表密集 + 文字较多
        file_category = "complex_pdf"
        recommended_parser = "pymupdf4llm"
        fallback_parsers = ["pymupdf_native", "markitdown"]
    else:
        file_category = "text_pdf"
        recommended_parser = "pymupdf4llm"
        fallback_parsers = ["markitdown", "pymupdf_native"]

    result = ClassificationResult(
        file_category=file_category,
        text_density=round(avg_density, 1),
        ocr_ratio=round(image_ratio, 2),
        image_page_ratio=round(image_ratio, 2),
        heading_count=heading_count,
        estimated_pages=total_pages,
        detected_language=detected_language,
        has_tables=has_tables,
        has_formulas=has_formulas,
        recommended_parser=recommended_parser,
        fallback_parsers=fallback_parsers,
    )
    logger.info(
        "classify_pdf_done",
        filename=path.name,
        category=result.file_category,
        pages=result.estimated_pages,
        avg_density=result.text_density,
        image_ratio=result.image_page_ratio,
        drawing_ratio=round(drawing_ratio, 2),
        formula_ratio=round(formula_ratio, 2),
        language=result.detected_language,
    )
    return result


def _is_large_image(document: Any, xref: int) -> bool:
    try:
        image = document.extract_image(xref)
    except Exception:
        return False
    if image is None:
        return False
    return len(image["image"]) > 5000


def _has_meaningful_drawing_clusters(page: Any) -> bool:
    for rect in page.cluster_drawings():
        if _is_meaningful_drawing_rect(rect):
            return True
    return False


def _is_meaningful_drawing_rect(rect: Any) -> bool:
    width = float(rect.width)
    height = float(rect.height)
    area = width * height
    return width >= 40 and height >= 10 and area >= 1500


def _classify_pptx(path: Path) -> ClassificationResult:
    if Presentation is None:
        return ClassificationResult(
            file_category="pptx",
            recommended_parser="markitdown",
            fallback_parsers=["python_pptx_native"],
        )

    try:
        presentation = Presentation(str(path))
        slide_count = len(presentation.slides)
        total_text = 0
        for slide in presentation.slides:
            for shape in slide.shapes:
                if not shape.has_text_frame:
                    continue
                total_text += sum(len(paragraph.text.strip()) for paragraph in shape.text_frame.paragraphs)
        avg_density = total_text / slide_count if slide_count else 0
    except Exception:
        slide_count = 0
        avg_density = 0

    return ClassificationResult(
        file_category="pptx",
        text_density=round(avg_density, 1),
        estimated_pages=slide_count,
        recommended_parser="markitdown",
        fallback_parsers=["python_pptx_native"],
    )


def _classify_docx(path: Path) -> ClassificationResult:
    try:
        paragraph_count, heading_count, avg_density, sample_text = _probe_docx_text(path)
    except Exception:
        paragraph_count = 0
        heading_count = 0
        avg_density = 0.0
        sample_text = ""

    return ClassificationResult(
        file_category="docx",
        text_density=round(avg_density, 1),
        heading_count=heading_count,
        estimated_pages=max(paragraph_count // 30, 1) if paragraph_count else 0,
        detected_language=_detect_language(sample_text[:5000]) if sample_text else "unknown",
        has_tables=bool(_TABLE_LIKE_RE.search(sample_text[:10000])),
        has_formulas=bool(_FORMULA_RE.search(sample_text[:10000])),
        recommended_parser="markitdown",
        fallback_parsers=["docx_native"],
    )


def _probe_docx_text(path: Path) -> tuple[int, int, float, str]:
    if Document is not None:
        try:
            document = Document(str(path))
            texts = [paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip()]
            heading_count = sum(
                1
                for paragraph in document.paragraphs
                if paragraph.style and paragraph.style.name and paragraph.style.name.lower().startswith("heading")
            )
            paragraph_count = len(texts)
            total_text = sum(len(item) for item in texts)
            return (
                paragraph_count,
                heading_count,
                total_text / max(paragraph_count, 1),
                "\n".join(texts[:80])[:10000],
            )
        except Exception:
            pass

    summary = summarize_docx_archive(path)
    return (
        summary.paragraph_count,
        summary.heading_count,
        summary.total_text_chars / max(summary.paragraph_count, 1) if summary.paragraph_count else 0.0,
        summary.sample_text,
    )


def _classify_text_file(path: Path, extension: str) -> ClassificationResult:
    try:
        text = read_text_file(path)
    except Exception:
        text = ""

    stripped = text.strip()
    non_empty_lines = [line for line in text.splitlines() if line.strip()]
    line_count = len(non_empty_lines)
    heading_count = len(_HEADING_LIKE_RE.findall(text[:10000])) + len(_MARKDOWN_HEADING_RE.findall(text[:10000]))
    estimated_pages = max(line_count // 50, 1) if line_count else 0
    file_category = categorize_text_extension(extension)
    return ClassificationResult(
        file_category=file_category,
        text_density=round(len(stripped) / max(line_count, 1), 1) if stripped else 0.0,
        heading_count=heading_count,
        estimated_pages=estimated_pages,
        detected_language=_detect_language(text[:5000]) if stripped else "unknown",
        has_tables=bool(_TABLE_LIKE_RE.search(text[:10000])),
        has_formulas=bool(_FORMULA_RE.search(text[:10000])),
        recommended_parser="text_native",
    )


def _detect_language(text: str) -> str:
    zh_count = len(_ZH_RE.findall(text))
    en_count = len(_EN_RE.findall(text))
    if zh_count > en_count * 2:
        return "zh"
    if en_count > zh_count * 2:
        return "en"
    return "mixed"
