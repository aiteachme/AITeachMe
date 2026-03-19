"""PDF 解析器：多 parser fallback + 图片提取。"""

from __future__ import annotations

from pathlib import Path

import structlog

from app.agents.ingest.parse_utils import save_image_bytes
from app.core.exceptions import FileParseError

logger = structlog.get_logger()


async def parse_pdf(file_path: str | Path, asset_dir: Path) -> str:
    """PDF 解析主入口：尝试多个 parser，选最优结果。

    策略：
    1. pymupdf4llm — markdown 结构最好
    2. MarkItDown — 兜底文本
    3. pymupdf 原生 — 纯文本 + 图片提取

    无论哪个 parser 成功，都用 pymupdf 补充提取图片。
    """
    path = Path(file_path)
    logger.info("parse_pdf_start", filename=path.name)

    markdown: str | None = None
    parser_used = "none"

    # 尝试 pymupdf4llm（最好的 markdown 结构）
    try:
        markdown = await _parse_pdf_pymupdf4llm(path)
        parser_used = "pymupdf4llm"
    except Exception as exc:
        logger.warning("parse_pdf_pymupdf4llm_failed", filename=path.name, error=str(exc))

    # 尝试 MarkItDown
    if markdown is None:
        try:
            markdown = await _parse_pdf_markitdown(path)
            parser_used = "markitdown"
        except Exception as exc:
            logger.warning("parse_pdf_markitdown_failed", filename=path.name, error=str(exc))

    # 最后兜底：pymupdf 原生（含图片提取）
    if markdown is None:
        try:
            markdown = await _parse_pdf_pymupdf_native(path, asset_dir)
            parser_used = "pymupdf_native"
        except Exception as exc:
            logger.warning("parse_pdf_pymupdf_native_failed", filename=path.name, error=str(exc))

    if markdown is None:
        raise FileParseError(path.name, reason="所有 PDF 解析器均失败。")

    # 非 native 路径时，补充提取图片到 asset_dir
    if parser_used != "pymupdf_native":
        try:
            _extract_pdf_images(path, asset_dir)
        except Exception:
            logger.debug("pdf_image_supplement_failed", filename=path.name)

    logger.info("parse_pdf_done", filename=path.name, parser=parser_used)
    return markdown


# ---------------------------------------------------------------------------
# 内部 parser 实现
# ---------------------------------------------------------------------------


async def _parse_pdf_pymupdf4llm(path: Path) -> str:
    import pymupdf4llm

    text = pymupdf4llm.to_markdown(str(path))
    if not text or not text.strip():
        raise FileParseError(path.name, reason="pymupdf4llm 提取文本为空。")
    return text


async def _parse_pdf_markitdown(path: Path) -> str:
    from markitdown import MarkItDown

    result = MarkItDown().convert(str(path))
    if not result.text_content or not result.text_content.strip():
        raise FileParseError(path.name, reason="MarkItDown 提取文本为空。")
    return result.text_content


async def _parse_pdf_pymupdf_native(path: Path, asset_dir: Path) -> str:
    """pymupdf 原生解析：逐页提取文本 + 图片。"""
    import fitz

    doc = fitz.open(str(path))
    sections: list[str] = []
    image_count = 0

    for page_idx in range(len(doc)):
        page = doc[page_idx]
        page_num = page_idx + 1
        sections.append(f"<!-- page:{page_num} -->")

        text = page.get_text("text")
        if text and text.strip():
            sections.append(text.strip())

        for img_idx, img_info in enumerate(page.get_images(full=True)):
            xref = img_info[0]
            try:
                base_image = doc.extract_image(xref)
                if base_image is None:
                    continue
                img_bytes = base_image["image"]
                img_ext = base_image.get("ext", "png")
                if len(img_bytes) < 2048:
                    continue
                image_count += 1
                filename = save_image_bytes(
                    img_bytes, asset_dir,
                    name_hint=f"p{page_num}_img{img_idx}",
                    ext=f".{img_ext}",
                )
                sections.append(f"\n![图片 {image_count}]({filename})\n")
            except Exception:
                logger.debug("pdf_image_extract_failed", page=page_num, img_idx=img_idx)

        sections.append("")

    doc.close()
    result = "\n".join(sections).strip()
    if not result:
        raise FileParseError(path.name, reason="pymupdf 提取文本为空。")

    logger.info("parse_pdf_pymupdf_native_done", filename=path.name, images=image_count)
    return result


# ---------------------------------------------------------------------------
# 图片补充提取
# ---------------------------------------------------------------------------


def _extract_pdf_images(file_path: Path, asset_dir: Path) -> None:
    """从 PDF 中提取图片到 asset_dir（补充提取，不修改 markdown）。"""
    import fitz

    doc = fitz.open(str(file_path))
    count = 0
    for page_idx in range(len(doc)):
        page = doc[page_idx]
        for img_idx, img_info in enumerate(page.get_images(full=True)):
            xref = img_info[0]
            try:
                base_image = doc.extract_image(xref)
                if base_image is None:
                    continue
                img_bytes = base_image["image"]
                if len(img_bytes) < 2048:
                    continue
                img_ext = base_image.get("ext", "png")
                save_image_bytes(
                    img_bytes, asset_dir,
                    name_hint=f"p{page_idx + 1}_img{img_idx}",
                    ext=f".{img_ext}",
                )
                count += 1
            except Exception:
                pass
    doc.close()
    if count > 0:
        logger.info("pdf_images_supplemented", filename=file_path.name, count=count)
