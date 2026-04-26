from app.workflows.digest.docgen.lib.publish import _resolve_published_chapter_source_file_ids


def test_published_chapter_source_file_ids_fall_back_to_matching_assignment():
    ids = _resolve_published_chapter_source_file_ids(
        {},
        chapter_index=2,
        fallback_assignment={"chapter_index": 1, "source_file_ids": [99]},
        assignments_by_index={
            2: {"chapter_index": 2, "source_file_ids": [7, "8", 7, 0, "bad"]},
        },
    )

    assert ids == [7, 8]


def test_published_chapter_source_file_ids_keep_chapter_sources_first():
    ids = _resolve_published_chapter_source_file_ids(
        {"source_file_ids": ["3", 3, 4]},
        chapter_index=2,
        fallback_assignment={"chapter_index": 2, "source_file_ids": [7]},
        assignments_by_index={2: {"chapter_index": 2, "source_file_ids": [8]}},
    )

    assert ids == [3, 4]
