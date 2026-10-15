import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlmodel import Session, SQLModel, create_engine, select

from app.api import user_files as user_files_api
from app.api.deps import CurrentUserContext
from app.api.user_files import _sanitize_interactive_html
from app.models import IngestStatus, RawFile, TaskStatus, User
from app.models.chat import Highlight
from app.workflows.ingest.intake import catalog


def test_sanitize_interactive_html_strips_executable_content() -> None:
    raw = """
    <div onclick="alert(1)">
      <script>alert("x")</script>
      <a href="javascript:alert(1)">bad</a>
      <a href="/safe/path">safe</a>
      <p style="color: red; background-image: url(javascript:alert(1)); font-weight: 700">Text</p>
      <img src="x" onerror="alert(1)" />
      <details open><summary>Hint</summary><input type="checkbox" checked /></details>
    </div>
    """

    cleaned = _sanitize_interactive_html(raw)

    assert "script" not in cleaned
    assert "onclick" not in cleaned
    assert "onerror" not in cleaned
    assert "javascript:" not in cleaned
    assert "<img" not in cleaned
    assert "<a>bad</a>" in cleaned
    assert 'href="/safe/path"' in cleaned
    assert 'rel="noreferrer noopener"' in cleaned
    assert "color: red" in cleaned
    assert "font-weight: 700" in cleaned
    assert "background-image" not in cleaned
    assert "<details" in cleaned
    assert "<input" in cleaned


def test_sanitize_interactive_html_unwraps_forms_and_strips_submit_attrs() -> None:
    raw = """
    <form action="https://evil.example/collect" method="post">
      <label>Choice <input type="checkbox" name="choice" form="external-form" checked /></label>
      <button formaction="https://evil.example/button" formmethod="post">Submit</button>
    </form>
    """

    cleaned = _sanitize_interactive_html(raw)

    assert "<form" not in cleaned
    assert "</form>" not in cleaned
    assert "https://evil.example" not in cleaned
    assert "action=" not in cleaned
    assert "method=" not in cleaned
    assert "form=" not in cleaned
    assert "<label>" in cleaned
    assert '<input type="checkbox" name="choice" checked="">' in cleaned


@pytest.mark.parametrize("storage_content", ["# 示例\n\n列表可以保存多个元素。", "", None])
def test_library_interactive_resolves_storage_only_markdown(
    monkeypatch: pytest.MonkeyPatch,
    storage_content: str | None,
) -> None:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine, tables=[User.__table__, RawFile.__table__, Highlight.__table__])
    markdown_key = "users/library-user/files/storage-only/markdown.md"
    storage_reads: list[str] = []
    generation_inputs: list[dict] = []

    async def read_text(key: str, *, default: str = "") -> str:
        storage_reads.append(key)
        if storage_content is None:
            raise TimeoutError("test storage temporarily unavailable")
        return storage_content

    async def generate_interactive_html(**kwargs):
        generation_inputs.append(kwargs)
        return SimpleNamespace(
            html="<div>列表演示</div>", title="列表演示", validation_issues=[], quality_issues=[],
            widget_type="", widget_outline={}, widget_config={}, language_directive="",
        )

    async def run_tasks(items, mapper):
        return [await mapper(item) for item in items]

    monkeypatch.setattr(catalog, "get_content_store", lambda: SimpleNamespace(read_text=read_text))
    monkeypatch.setattr(user_files_api, "generate_selection_interactive_html", generate_interactive_html)
    monkeypatch.setattr(user_files_api, "run_llm_tasks", run_tasks)
    with Session(engine, expire_on_commit=False) as session:
        session.add(User(id="library-user", username="library-user"))
        session.add(RawFile(
            id="storage-only", user_id="library-user", filename="notes.pdf", filetype="pdf",
            file_path="notes.pdf", markdown_path=markdown_key,
            status=TaskStatus.COMPLETED.value, ingest_status=IngestStatus.READY_FOR_DIGEST.value,
        ))
        session.commit()
        request = user_files_api.InteractiveGenerateRequest(selected_text="列表可以保存多个元素。")
        user = CurrentUserContext(user_id="library-user", email=None, is_local=True)

        if storage_content:
            result = asyncio.run(user_files_api.generate_interactive(
                file_id="storage-only", body=request, user=user, session=session,
            ))
            assert result.data.html == "<div>列表演示</div>"
            assert generation_inputs[0]["section_excerpt"] == storage_content
            highlight = session.exec(select(Highlight)).one()
            assert highlight.interactive_html == result.data.html
            assert highlight.user_id == user.user_id
        else:
            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(user_files_api.generate_interactive(
                    file_id="storage-only", body=request, user=user, session=session,
                ))
            assert exc_info.value.status_code == 503
            assert exc_info.value.detail == "资料正文暂时无法读取，请稍后重试。"
            assert not generation_inputs
            assert session.exec(select(Highlight)).all() == []
    assert storage_reads == [markdown_key]
