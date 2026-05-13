from __future__ import annotations

import app.workflows.support.export_import.courses as courses_module


def test_available_demo_course_list_reuses_package_probe_cache(monkeypatch) -> None:
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
                "course_name": "演示课程",
                "package_url": "atmx/demo-course.atmx",
            }
        ]

    def fake_package_exists(package_url: str) -> bool:
        probed_urls.append(package_url)
        return True

    monkeypatch.setattr(courses_module, "_REMOTE_DESCRIPTOR_CACHE", None)
    monkeypatch.setattr(courses_module, "_REMOTE_AVAILABLE_DESCRIPTOR_CACHE", None)
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
