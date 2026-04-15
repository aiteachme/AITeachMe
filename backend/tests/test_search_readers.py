import asyncio
import io
import zipfile

from app.shared.infra.search.readers.common import normalize_read_text
from app.shared.infra.search.readers.docx_reader import extract_docx_text
from app.shared.infra.search.readers.jina_reader import JinaReader
from app.shared.infra.search.readers.pptx_reader import extract_pptx_text
from app.shared.infra.search.types import ScrapedPage


def _build_docx_payload() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "docProps/core.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
            <cp:coreProperties
              xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
              xmlns:dc="http://purl.org/dc/elements/1.1/">
              <dc:title>线性代数讲义</dc:title>
            </cp:coreProperties>
            """,
        )
        archive.writestr(
            "word/document.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
              <w:body>
                <w:p><w:r><w:t>矩阵</w:t></w:r><w:r><w:t>与</w:t></w:r><w:r><w:t>行列式</w:t></w:r></w:p>
                <w:p><w:r><w:t>特征值与特征向量</w:t></w:r></w:p>
              </w:body>
            </w:document>
            """,
        )
    return buffer.getvalue()


def _build_pptx_payload() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "docProps/core.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
            <cp:coreProperties
              xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
              xmlns:dc="http://purl.org/dc/elements/1.1/">
              <dc:title>高数速成课</dc:title>
            </cp:coreProperties>
            """,
        )
        archive.writestr(
            "ppt/slides/slide1.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
            <p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
                   xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
              <p:cSld>
                <p:spTree>
                  <p:sp>
                    <p:txBody>
                      <a:p><a:r><a:t>极限与连续</a:t></a:r></a:p>
                      <a:p><a:r><a:t>重点题型</a:t></a:r></a:p>
                    </p:txBody>
                  </p:sp>
                </p:spTree>
              </p:cSld>
            </p:sld>
            """,
        )
        archive.writestr(
            "ppt/slides/slide2.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
            <p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
                   xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
              <p:cSld>
                <p:spTree>
                  <p:sp>
                    <p:txBody>
                      <a:p><a:r><a:t>导数的定义</a:t></a:r></a:p>
                    </p:txBody>
                  </p:sp>
                </p:spTree>
              </p:cSld>
            </p:sld>
            """,
        )
    return buffer.getvalue()


def test_normalize_read_text_collapses_whitespace() -> None:
    text = "第一行  \r\n\r\n\r\n第二行\t\t内容"
    assert normalize_read_text(text) == "第一行\n\n第二行 内容"


def test_extract_docx_text_reads_core_title_and_paragraphs() -> None:
    title, content = extract_docx_text(_build_docx_payload())
    assert title == "线性代数讲义"
    assert "矩阵 与 行列式" in content
    assert "特征值与特征向量" in content


def test_extract_pptx_text_reads_slides_in_order() -> None:
    title, content = extract_pptx_text(_build_pptx_payload())
    assert title == "高数速成课"
    assert "Slide 1" in content
    assert "极限与连续" in content
    assert "重点题型" in content
    assert "Slide 2" in content
    assert "导数的定义" in content


def test_jina_reader_is_opt_in(monkeypatch) -> None:
    monkeypatch.delenv("JINA_READER_ENABLED", raising=False)
    assert JinaReader.supports_url("https://example.com") is False

    monkeypatch.setenv("JINA_READER_ENABLED", "true")
    assert JinaReader.supports_url("https://example.com") is True


def test_jina_reader_converts_url_and_extracts_title(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        text = "Title: 示例页面\n\n正文内容"

    async def fake_fetch_url(url: str, *, headers=None):
        captured["url"] = url
        captured["headers"] = headers
        return FakeResponse()

    monkeypatch.setenv("JINA_API_KEY", "jina-key")
    monkeypatch.setattr("app.shared.infra.search.readers.jina_reader.fetch_url", fake_fetch_url)

    page = asyncio.run(JinaReader().read("https://example.com/a?b=1"))

    assert captured["url"] == "https://r.jina.ai/https://example.com/a?b=1"
    assert captured["headers"] == {"Authorization": "Bearer jina-key"}
    assert isinstance(page, ScrapedPage)
    assert page.title == "示例页面"
    assert page.content == "正文内容"
    assert page.reader_name == "jina"
