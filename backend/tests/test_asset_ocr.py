from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.workflows.ingest.parsing import asset_ocr


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_placeholder_fallback_preserves_skipped_items_after_parallel_breaker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prefix = "doc__file__"
    assets = [
        tmp_path / f"{prefix}p1_{index:03d}.png"
        for index in range(1, 5)
    ]
    for index, path in enumerate(assets, start=1):
        marker = b"fail" if index <= 2 else b"ok"
        path.write_bytes(marker + (b"x" * 3000))

    async def fake_parse_image_bytes_with_llm_vision(image_bytes: bytes, **_: object) -> str:
        await asyncio.sleep(0)
        if image_bytes.startswith(b"fail"):
            return "[unclear]"
        return "recognized text"

    monkeypatch.setattr(
        asset_ocr,
        "parse_image_bytes_with_llm_vision",
        fake_parse_image_bytes_with_llm_vision,
    )

    markdown = "\n".join(
        f"image [{index}] intentionally omitted"
        for index in range(1, 5)
    )

    result = await asset_ocr.enhance_markdown_with_asset_ocr(
        markdown,
        asset_dir=tmp_path,
        asset_link_prefix="../assets",
        asset_name_prefix=prefix,
        enabled=True,
        limit=4,
        language_mode="auto",
        concurrency=4,
    )

    assert result.placeholder_replacements == 4
    assert "intentionally omitted" not in result.markdown
    assert result.markdown.count("![Extracted image") == 4
    assert result.markdown.count("recognized text") == 2
    for path in assets:
        assert f"../assets/{path.name}" in result.markdown
