from app.workflows.digest.common import pedagogy


def test_chapter_title_resolution_rejects_templates_and_derives_specific_titles() -> None:
    assert pedagogy.clean_generated_chapter_title("第 03 章：核心概念总览") == "核心概念总览"
    assert pedagogy.looks_like_generic_template_title("核心概念") is True
    assert pedagogy.is_usable_resolved_chapter_title("Chapter 2") is False

    title = pedagogy.resolve_effective_chapter_title(
        {
            "title": "第 2 章",
            "required_elements": ["矩阵分解：奇异值分解和低秩近似"],
            "summary": "本章说明特征值如何支撑降维。",
        },
        chapter_index=2,
    )
    assert title == "矩阵分解：奇异值分解和低秩近似"

    assert (
        pedagogy.coerce_resolved_chapter_title(
            "章节目标",
            chapter={"resolved_title": "矩阵分解：奇异值分解和低秩近似"},
            chapter_index=2,
        )
        == "矩阵分解：奇异值分解和低秩近似"
    )


def test_document_overview_dedupes_chapters_and_hides_course_ids() -> None:
    chapters = [
        {"chapter_index": 1, "title": "核心概念总览", "summary": "short"},
        {"chapter_index": 1, "title": "矩阵分解", "summary": "longer summary wins"},
        {"chapter_index": 2, "resolved_title": "特征值应用", "summary": "x"},
        {"chapter_index": 3, "title": "第 3 章", "required_elements": ["正交投影：最小二乘几何解释"]},
    ]

    overview = pedagogy.build_document_overview(
        course_name="course_linear_algebra",
        digest_mode="sprint",
        user_prompt="",
        plan_summary="",
        source_strategy="",
        chapters=chapters,
    )

    assert "《当前课程》" in overview
    assert "共 3 章" in overview
    assert "矩阵分解、特征值应用、正交投影：最小二乘几何解释" in overview
    assert "核心概念总览" not in overview


def test_heading_quality_detects_duplicate_generic_titles() -> None:
    quality = pedagogy.analyze_chapter_heading_quality(
        "# 线性代数\n\n## 核心概念\nA\n\n## 核心概念\nB",
        digest_mode="systematic",
    )

    assert quality["digest_mode"] == "systematic"
    assert quality["h2_count"] == 2
    assert quality["duplicate_titles"] == ["核心概念"]
    assert quality["generic_titles"] == ["核心概念", "核心概念"]
    assert quality["needs_agent_repair"] is True
    assert quality["needs_scaffold_fallback"] is False
    assert {"guide", "objectives", "recap"} <= set(quality["missing_modules"])


def test_learning_scaffold_inserts_required_sections_without_duplication() -> None:
    scaffold = pedagogy.ensure_chapter_learning_scaffold(
        "只有一段内容",
        title="矩阵分解",
        objective="掌握矩阵分解",
        required_elements=["奇异值分解", "低秩近似"],
        digest_mode="sprint",
        source_count=2,
    )
    repeated = pedagogy.ensure_chapter_learning_scaffold(
        scaffold,
        title="矩阵分解",
        objective="掌握矩阵分解",
        required_elements=["奇异值分解", "低秩近似"],
        digest_mode="sprint",
        source_count=2,
    )

    assert scaffold.startswith("# 矩阵分解\n")
    assert "> [!TIP]" in scaffold
    assert "奇异值分解" in scaffold
    assert "低秩近似" in scaffold
    assert scaffold.count("核心总结") == 1
    assert repeated.count("核心总结") == 1
    assert repeated.count("> [!TIP]") == 1


def test_systematic_mode_sections_add_position_and_extension_boundaries() -> None:
    first_chapter_keys = [
        key
        for key, _heading, _block in pedagogy._build_mode_sections(
            title="矩阵分解",
            objective="理解矩阵分解在课程中的位置",
            required_elements=["奇异值分解", "低秩近似"],
            digest_mode="systematic",
            chapter_index=1,
            chapter_count=3,
        )
    ]
    final_chapter_keys = [
        key
        for key, _heading, _block in pedagogy._build_mode_sections(
            title="综合应用",
            objective="串联课程知识",
            required_elements=["综合题", "迁移应用"],
            digest_mode="systematic",
            chapter_index=3,
            chapter_count=3,
        )
    ]

    assert "map" in first_chapter_keys
    assert "extension" not in first_chapter_keys
    assert "map" not in final_chapter_keys
    assert "extension" in final_chapter_keys
