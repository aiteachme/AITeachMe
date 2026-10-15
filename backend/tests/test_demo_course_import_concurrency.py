from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.api import export_import as export_import_api
from app.api.deps import CurrentUserContext
from app.schemas.export_import import ImportResultData


def test_demo_import_keeps_event_loop_available_during_package_download(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    package_path = tmp_path / "demo.atmx"
    package_path.write_bytes(b"test package")
    download_started = threading.Event()
    download_released = threading.Event()
    download_finished = threading.Event()
    caller_thread = threading.get_ident()
    session = object()

    def download_package(identifier: str) -> tuple[Path, str]:
        assert identifier == "demo-course"
        download_started.set()
        try:
            # The timeout keeps this regression safe even before the fix,
            # when the download would block the coroutine that releases it.
            download_released.wait(timeout=2)
            return package_path, "demo.atmx"
        finally:
            download_finished.set()

    def import_package(actual_session, *, file_path, options, user_id):
        # Only the network download moves to a worker; the DB session stays
        # on the request's original thread and is never used concurrently.
        assert threading.get_ident() == caller_thread
        assert actual_session is session
        assert file_path == package_path
        assert options.new_course_name == "示例课程副本"
        assert options.rebuild_embeddings is False
        assert user_id == "demo-import-user"
        return ImportResultData(course_id="course_demo", course_name="示例课程副本")

    monkeypatch.setattr(export_import_api, "download_course_package", download_package)
    monkeypatch.setattr(export_import_api, "import_course", import_package)
    monkeypatch.setattr(
        export_import_api, "spawn_imported_embedding_rebuild_background", lambda *_args, **_kwargs: False,
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
    user = CurrentUserContext(user_id="demo-import-user", email=None, is_local=True)

    async def run_import_and_other_request() -> None:
        import_task = asyncio.create_task(export_import_api.import_demo_course_api(
            request=request,
            identifier="demo-course",
            new_course_name="示例课程副本",
            user=user,
            session=session,
        ))
        try:
            assert await asyncio.to_thread(download_started.wait, 3)
            # A second request/coroutine can run before the download returns.
            assert not download_finished.is_set(), "示例课程下载阻塞了事件循环"
        finally:
            download_released.set()
            response = await import_task
        assert response.data.course_id == "course_demo"

    asyncio.run(run_import_and_other_request())
    assert not package_path.exists()
