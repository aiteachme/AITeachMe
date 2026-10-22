from __future__ import annotations

import hashlib

import httpx
import pytest

import app.workflows.support.export_import.courses as courses_module
from app.shared.infra.exceptions import DemoCourseCatalogUnavailableError


@pytest.fixture(autouse=True)
def reset_remote_catalog_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(courses_module, "_REMOTE_DESCRIPTOR_CACHE", None)


def test_catalog_failure_is_not_cached_as_an_empty_list_and_recovers(monkeypatch):
    attempts = 0

    def fetch_catalog(_url):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise DemoCourseCatalogUnavailableError(reason="连接超时")
        return [{"id": "recovered", "course_name": "Recovered", "package_url": "atmx/recovered.atmx"}]

    monkeypatch.setattr(courses_module, "_fetch_remote_catalog_payload", fetch_catalog)
    with pytest.raises(DemoCourseCatalogUnavailableError):
        courses_module.list_available_courses()
    assert [item.filename for item in courses_module.list_available_courses()] == ["recovered"]
    assert attempts == 2


def test_invalid_catalog_is_distinct_from_an_explicit_empty_catalog(monkeypatch):
    monkeypatch.setattr(courses_module, "_fetch_remote_catalog_payload", lambda _url: {"message": "unavailable"})
    with pytest.raises(DemoCourseCatalogUnavailableError):
        courses_module.list_available_courses()
    monkeypatch.setattr(courses_module, "_fetch_remote_catalog_payload", lambda _url: {"courses": []})
    assert courses_module.list_available_courses() == []


def test_demo_course_list_reuses_catalog_cache_without_package_probes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 100.0
    fetch_count = 0

    def fake_monotonic() -> float:
        return now

    def fake_fetch_catalog(_catalog_url: str) -> list[dict[str, object]]:
        nonlocal fetch_count
        fetch_count += 1
        return [
            {
                "id": "demo-course",
                "course_name": "Demo Course",
                "package_url": "atmx/demo-course.atmx",
            },
            {
                "id": "second-course",
                "course_name": "Second Course",
                "package_url": "atmx/second-course.atmx",
            },
        ]

    monkeypatch.setattr(courses_module.time, "monotonic", fake_monotonic)
    monkeypatch.setattr(courses_module, "_fetch_remote_catalog_payload", fake_fetch_catalog)

    first = courses_module.list_available_courses()
    second = courses_module.list_available_courses()

    assert [item.filename for item in first] == ["demo-course", "second-course"]
    assert [item.filename for item in second] == ["demo-course", "second-course"]
    assert fetch_count == 1

    now += courses_module._CATALOG_CACHE_TTL_S + 1.0
    third = courses_module.list_available_courses()

    assert [item.filename for item in third] == ["demo-course", "second-course"]
    assert fetch_count == 2


def test_package_download_restarts_after_partial_read_and_caches_verified_fallback(monkeypatch, tmp_path):
    package = b"complete demo course package"
    descriptor = courses_module._RemoteCourseDescriptor(
        identifier="demo-course", course_name="Demo", package_filename="demo.atmx",
        package_url="https://raw.githubusercontent.com/aiteachme/assets/main/demo-courses/atmx/demo.atmx",
        file_size_bytes=len(package), sha256=hashlib.sha256(package).hexdigest(),
    )
    requests = []

    class BrokenStream(httpx.SyncByteStream):
        def __iter__(self):
            yield b"partial"
            raise httpx.ReadTimeout("interrupted")

    def handle(request):
        requests.append(request)
        if request.url.host == "raw.githubusercontent.com":
            return httpx.Response(200, stream=BrokenStream())
        return httpx.Response(200, content=package)

    client = httpx.Client(transport=httpx.MockTransport(handle))
    monkeypatch.setattr(courses_module.httpx, "Client", lambda **_kwargs: client)
    monkeypatch.setattr(courses_module, "get_remote_course_descriptor", lambda _id: descriptor)
    monkeypatch.setattr(courses_module, "get_runtime_data_dir", lambda: tmp_path)

    downloaded, filename = courses_module.download_course_package("demo-course")
    try:
        assert downloaded.read_bytes() == package
        assert filename == "demo.atmx"
        assert [r.url.host for r in requests] == ["raw.githubusercontent.com", "api.github.com"]
        assert requests[0].url.query == b""
        assert requests[1].headers["Accept"] == "application/vnd.github.raw+json"
        cached, _ = courses_module.download_course_package("demo-course")
        try:
            assert cached.read_bytes() == package
            assert len(requests) == 2
        finally:
            cached.unlink()
    finally:
        downloaded.unlink()


def test_package_connection_failure_is_reported_as_domain_error(monkeypatch, tmp_path):
    descriptor = courses_module._RemoteCourseDescriptor(
        identifier="demo-course", course_name="Demo", package_filename="demo.atmx",
        package_url="https://raw.githubusercontent.com/aiteachme/assets/main/demo-courses/atmx/demo.atmx",
    )

    def fail(request):
        raise httpx.ConnectTimeout("unreachable", request=request)

    client = httpx.Client(transport=httpx.MockTransport(fail))
    monkeypatch.setattr(courses_module.httpx, "Client", lambda **_kwargs: client)
    monkeypatch.setattr(courses_module, "get_remote_course_descriptor", lambda _id: descriptor)
    monkeypatch.setattr(courses_module, "get_runtime_data_dir", lambda: tmp_path)

    with pytest.raises(DemoCourseCatalogUnavailableError, match="下载连接失败或超时"):
        courses_module.download_course_package("demo-course")


def test_catalog_items_remain_visible_when_package_probe_would_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_fetch_catalog(_catalog_url: str) -> list[dict[str, object]]:
        return [
            {
                "id": "delayed-course",
                "course_name": "Delayed Course",
                "package_url": "atmx/delayed.atmx",
            }
        ]

    monkeypatch.setattr(courses_module, "_fetch_remote_catalog_payload", fake_fetch_catalog)

    courses = courses_module.list_available_courses()

    assert [item.filename for item in courses] == ["delayed-course"]


def test_get_remote_course_descriptor_uses_catalog_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetch_count = 0

    def fake_fetch_catalog(_catalog_url: str) -> list[dict[str, object]]:
        nonlocal fetch_count
        fetch_count += 1
        return [
            {
                "id": "offline-course",
                "course_name": "Offline Course",
                "package_url": "atmx/offline.atmx",
                "file_size_bytes": 123,
            }
        ]

    monkeypatch.setattr(courses_module, "_fetch_remote_catalog_payload", fake_fetch_catalog)

    listed = courses_module.list_available_courses()
    descriptor = courses_module.get_remote_course_descriptor("offline-course")

    assert [item.filename for item in listed] == ["offline-course"]
    assert descriptor.identifier == "offline-course"
    assert descriptor.package_filename == "offline.atmx"
    assert descriptor.file_size_bytes == 123
    assert fetch_count == 1
