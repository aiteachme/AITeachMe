from __future__ import annotations

import pytest

from app.shared.infra.execution import TracedExecutionContext
from app.shared.infra.search.factory import get_reader_for_url
from app.shared.infra.search.readers.common import DEFAULT_READER_HEADERS, fetch_url
from app.shared.infra.search.readers.mediawiki_reader import MediaWikiReader
from app.shared.infra.search.source_curation import SourceCurator
from app.shared.infra.search.types import SearchResult


def test_mediawiki_reader_wins_for_zh_wiki_pages():
    reader = get_reader_for_url("https://zh.wikibooks.org/wiki/初中數學/平面幾何")

    assert isinstance(reader, MediaWikiReader)


@pytest.mark.anyio
async def test_mediawiki_reader_uses_official_extract_api(monkeypatch):
    captured: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "query": {
                    "pages": {
                        "1": {
                            "title": "初中數學/平面幾何",
                            "extract": "平面几何研究点、线、角与图形关系。",
                        }
                    }
                }
            }

    class FakeClient:
        def __init__(self, **kwargs):
            captured["client_kwargs"] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, *, params):
            captured["url"] = url
            captured["params"] = params
            return FakeResponse()

    monkeypatch.setattr("app.shared.infra.search.readers.mediawiki_reader.httpx.AsyncClient", FakeClient)

    page = await MediaWikiReader().read("https://zh.wikibooks.org/wiki/初中數學/平面幾何")

    assert page.success
    assert page.reader_name == "mediawiki"
    assert page.title == "初中數學/平面幾何"
    assert "平面几何" in page.content
    assert captured["url"] == "https://zh.wikibooks.org/w/api.php"
    assert captured["params"]["prop"] == "extracts"
    assert captured["params"]["explaintext"] == 1


@pytest.mark.anyio
async def test_fetch_url_applies_default_reader_headers(monkeypatch):
    captured: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

    class FakeClient:
        def __init__(self, **kwargs):
            captured["client_kwargs"] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, *, headers):
            captured["url"] = url
            captured["headers"] = headers
            return FakeResponse()

    monkeypatch.setattr("app.shared.infra.search.readers.common.httpx.AsyncClient", FakeClient)

    await fetch_url("https://example.com/page", headers={"Accept": "text/plain"})

    assert captured["headers"]["User-Agent"] == DEFAULT_READER_HEADERS["User-Agent"]
    assert captured["headers"]["Accept"] == "text/plain"
    assert "zh-CN" in captured["headers"]["Accept-Language"]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/file.txt",
        "http://localhost/page",
        "http://127.0.0.1/page",
        "http://169.254.169.254/latest/meta-data",
        "http://10.0.0.1/page",
    ],
)
async def test_fetch_url_rejects_unsafe_targets_before_request(url):
    with pytest.raises(ValueError):
        await fetch_url(url)


@pytest.mark.anyio
async def test_fetch_url_rejects_redirect_to_unsafe_target(monkeypatch):
    captured: dict[str, object] = {"urls": []}

    class FakeResponse:
        status_code = 302
        headers = {"location": "http://127.0.0.1/private"}
        url = "https://example.com/start"

        def raise_for_status(self) -> None:
            return None

    class FakeClient:
        def __init__(self, **kwargs):
            captured["client_kwargs"] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, *, headers):
            captured["urls"].append(url)
            return FakeResponse()

    monkeypatch.setattr("app.shared.infra.search.readers.common.httpx.AsyncClient", FakeClient)

    with pytest.raises(ValueError):
        await fetch_url("https://example.com/start")

    assert captured["urls"] == ["https://example.com/start"]


@pytest.mark.parametrize(
    ("title", "snippet"),
    [
        ("高中数学/不等式与数列/常系数线性递推数列", "递推数列与不等式课程。"),
        ("超普通心理学/社會心理學", "社会心理学课程。"),
        ("奥托 (编程语言)", "奥托编程语言教程。"),
    ],
)
def test_source_curator_filters_obviously_irrelevant_wiki_results(title, snippet):
    curator = SourceCurator(TracedExecutionContext(subject="subj_test"))

    filtered = curator._filter_sources(
        [
            SearchResult(
                url="https://zh.wikibooks.org/wiki/" + title,
                title=title,
                snippet=snippet,
                source="zh_wikibooks",
            )
        ],
        query="两位数乘一位数的竖式计算步骤与进位规则详解",
    )

    assert filtered == []


def test_source_curator_keeps_relevant_wiki_results():
    curator = SourceCurator(TracedExecutionContext(subject="subj_test"))
    result = SearchResult(
        url="https://zh.wikibooks.org/wiki/两位数乘一位数",
        title="两位数乘一位数的竖式计算",
        snippet="讲解两位数乘一位数的竖式步骤、对齐方式与进位规则。",
        source="zh_wikibooks",
    )

    filtered = curator._filter_sources([result], query="两位数乘一位数的竖式计算步骤与进位规则详解")

    assert filtered == [result]
