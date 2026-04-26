from __future__ import annotations

import pytest

from app.shared.infra.exceptions import DemoCourseCatalogNotConfiguredError
from app.workflows.support.export_import import courses


def test_script_generated_demo_course_catalog_shape_loads(monkeypatch) -> None:
    payload = {
        "schema_version": "1.0",
        "generated_by": "scripts/private/demo_course_package.py",
        "updated_at": "2026-04-26T12:00:00+00:00",
        "courses": [
            {
                "course_id": "linear-algebra",
                "id": "linear-algebra",
                "slug": "linear-algebra",
                "subject_name": "线性代数",
                "package": "packages/linear-algebra/v20260426_120000/linear-algebra.atmx",
                "package_key": "demo-courses/packages/linear-algebra/v20260426_120000/linear-algebra.atmx",
                "package_filename": "linear-algebra.atmx",
                "file_size_bytes": 1024,
                "sha256": "a" * 64,
                "exported_at": "2026-04-26T11:59:00+00:00",
                "published_at": "2026-04-26T12:00:00+00:00",
                "stats": {
                    "raw_file_count": "2",
                    "knowledge_unit_count": 18,
                },
            }
        ],
    }

    monkeypatch.setenv("APP_MODE", "cloud")
    monkeypatch.setenv("S3_PUBLIC_BASE_URL", "https://cdn.example.test")
    monkeypatch.setattr(courses, "_fetch_remote_catalog_payload", lambda _catalog_url: payload)

    items = courses.list_available_courses()
    assert len(items) == 1
    assert items[0].filename == "linear-algebra"
    assert items[0].subject_name == "线性代数"
    assert items[0].file_size_bytes == 1024
    assert items[0].stats["raw_file_count"] == 2
    assert items[0].stats["knowledge_unit_count"] == 18

    descriptor = courses.get_remote_course_descriptor("linear-algebra.atmx")
    assert descriptor.identifier == "linear-algebra"
    assert descriptor.package_filename == "linear-algebra.atmx"
    assert (
        descriptor.package_url
        == "https://cdn.example.test/demo-courses/packages/linear-algebra/v20260426_120000/linear-algebra.atmx"
    )


def test_local_mode_does_not_read_or_download_demo_courses(monkeypatch) -> None:
    monkeypatch.setenv("APP_MODE", "local")
    monkeypatch.setenv("S3_PUBLIC_BASE_URL", "https://cdn.example.test")

    def fail_fetch(_catalog_url: str):
        raise AssertionError("local mode should not fetch remote demo courses")

    monkeypatch.setattr(courses, "_fetch_remote_catalog_payload", fail_fetch)

    assert courses.list_available_courses() == []
    with pytest.raises(DemoCourseCatalogNotConfiguredError):
        courses.download_course_package("linear-algebra")
