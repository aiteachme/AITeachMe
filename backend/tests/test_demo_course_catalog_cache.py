from __future__ import annotations

import pytest

import app.workflows.support.export_import.courses as courses_module


@pytest.fixture(autouse=True)
def reset_remote_catalog_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(courses_module, "_REMOTE_DESCRIPTOR_CACHE", None)


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
