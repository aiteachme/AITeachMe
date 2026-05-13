from __future__ import annotations

import pytest

import app.workflows.support.export_import.courses as courses_module


@pytest.fixture(autouse=True)
def reset_remote_catalog_caches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(courses_module, "_REMOTE_DESCRIPTOR_CACHE", None)
    monkeypatch.setattr(courses_module, "_REMOTE_AVAILABLE_DESCRIPTOR_CACHE", None)


def test_available_demo_course_list_reuses_package_probe_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 100.0
    fetch_count = 0
    probed_urls: list[str] = []

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
            }
        ]

    def fake_package_exists(package_url: str) -> bool:
        probed_urls.append(package_url)
        return True

    monkeypatch.setattr(courses_module.time, "monotonic", fake_monotonic)
    monkeypatch.setattr(courses_module, "_fetch_remote_catalog_payload", fake_fetch_catalog)
    monkeypatch.setattr(courses_module, "_remote_package_exists", fake_package_exists)

    first = courses_module.list_available_courses()
    second = courses_module.list_available_courses()

    assert [item.filename for item in first] == ["demo-course"]
    assert [item.filename for item in second] == ["demo-course"]
    assert fetch_count == 1
    assert len(probed_urls) == 1

    now += courses_module._CATALOG_CACHE_TTL_S + 1.0
    third = courses_module.list_available_courses()

    assert [item.filename for item in third] == ["demo-course"]
    assert fetch_count == 2
    assert len(probed_urls) == 2


def test_unavailable_demo_course_is_hidden_until_availability_cache_expires(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 100.0
    availability_by_filename = {
        "available.atmx": True,
        "delayed.atmx": False,
    }
    fetch_count = 0
    probed_filenames: list[str] = []

    def fake_monotonic() -> float:
        return now

    def fake_fetch_catalog(_catalog_url: str) -> list[dict[str, object]]:
        nonlocal fetch_count
        fetch_count += 1
        return [
            {
                "id": "available-course",
                "course_name": "Available Course",
                "package_url": "atmx/available.atmx",
            },
            {
                "id": "delayed-course",
                "course_name": "Delayed Course",
                "package_url": "atmx/delayed.atmx",
            },
        ]

    def fake_package_exists(package_url: str) -> bool:
        filename = package_url.rsplit("/", 1)[-1]
        probed_filenames.append(filename)
        return availability_by_filename[filename]

    monkeypatch.setattr(courses_module.time, "monotonic", fake_monotonic)
    monkeypatch.setattr(courses_module, "_fetch_remote_catalog_payload", fake_fetch_catalog)
    monkeypatch.setattr(courses_module, "_remote_package_exists", fake_package_exists)

    first = courses_module.list_available_courses()
    second = courses_module.list_available_courses()

    assert [item.filename for item in first] == ["available-course"]
    assert [item.filename for item in second] == ["available-course"]
    assert fetch_count == 1
    assert probed_filenames == ["available.atmx", "delayed.atmx"]

    availability_by_filename["delayed.atmx"] = True
    now += courses_module._CATALOG_CACHE_TTL_S + 1.0
    third = courses_module.list_available_courses()

    assert [item.filename for item in third] == ["available-course", "delayed-course"]
    assert fetch_count == 2
    assert probed_filenames == [
        "available.atmx",
        "delayed.atmx",
        "available.atmx",
        "delayed.atmx",
    ]


def test_get_remote_course_descriptor_uses_catalog_cache_without_package_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probe_count = 0

    def fake_fetch_catalog(_catalog_url: str) -> list[dict[str, object]]:
        return [
            {
                "id": "offline-course",
                "course_name": "Offline Course",
                "package_url": "atmx/offline.atmx",
                "file_size_bytes": 123,
            }
        ]

    def fake_package_exists(_package_url: str) -> bool:
        nonlocal probe_count
        probe_count += 1
        return False

    monkeypatch.setattr(courses_module, "_fetch_remote_catalog_payload", fake_fetch_catalog)
    monkeypatch.setattr(courses_module, "_remote_package_exists", fake_package_exists)

    assert courses_module.list_available_courses() == []
    descriptor = courses_module.get_remote_course_descriptor("offline-course")

    assert descriptor.identifier == "offline-course"
    assert descriptor.package_filename == "offline.atmx"
    assert descriptor.file_size_bytes == 123
    assert probe_count == 1
