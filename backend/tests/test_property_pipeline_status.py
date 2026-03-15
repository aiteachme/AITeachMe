"""
属性测试：流水线状态聚合（Property 12 — Pipeline Status Aggregation）

验证 compute_pipeline_status 对所有 parse_status × pipeline_stage 组合返回正确的
stage/progress/message，progress 单调递增。
"""

import os

os.environ.setdefault("LLM_API_KEY", "test-key-for-testing")
os.environ.setdefault("DATA_DIR", "./test_data")

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app.repositories.models import RawFile, Knowledge, ParseStatus, PipelineStage
from app.services.upload_service import compute_pipeline_status


# ═══════════════════════════════════════════════════════════════
# Expected mapping (ground truth from requirements 5.10)
# ═══════════════════════════════════════════════════════════════

# parse_status states that are resolved before looking at pipeline_stage
PARSE_ONLY_EXPECTED = {
    ParseStatus.PENDING:      ("upload",  0,   "等待解析"),
    ParseStatus.PARSING:      ("parse",   20,  "正在解析文档"),
    ParseStatus.PARSE_FAILED: ("failed",  100, "解析失败"),
}

# When parse_status == parsed but knowledge is None
PARSED_NO_KNOWLEDGE = ("parse", 30, "解析完成，准备索引")

# When parse_status == parsed and knowledge exists, keyed by pipeline_stage
PIPELINE_STAGE_EXPECTED = {
    PipelineStage.PENDING:  ("digest", 40,  "等待消化索引"),
    PipelineStage.CLEANED:  ("digest", 50,  "Markdown 清洗完成"),
    PipelineStage.OUTLINED: ("digest", 60,  "大纲提取完成"),
    PipelineStage.STORED:   ("digest", 70,  "知识落库完成"),
    PipelineStage.CHUNKED:  ("digest", 80,  "文档切块完成"),
    PipelineStage.EMBEDDED: ("done",   100, "处理完成"),
    PipelineStage.FAILED:   ("failed", 100, "索引失败"),
}

# Ordered progress values along the happy path (excluding failure branches)
HAPPY_PATH_PROGRESS = [0, 20, 30, 40, 50, 60, 70, 80, 100]


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

def _make_raw_file(parse_status: str) -> RawFile:
    """Create a minimal RawFile with the given parse_status."""
    return RawFile(
        id=1,
        subject="math",
        filename="test.pdf",
        filetype="pdf",
        file_path="/tmp/test.pdf",
        parse_status=parse_status,
    )


def _make_knowledge(pipeline_stage: str) -> Knowledge:
    """Create a minimal Knowledge with the given pipeline_stage."""
    return Knowledge(
        id=1,
        subject="math",
        raw_file_id=1,
        title="test",
        markdown_content="",
        pipeline_stage=pipeline_stage,
    )


# ═══════════════════════════════════════════════════════════════
# Strategies
# ═══════════════════════════════════════════════════════════════

parse_status_st = st.sampled_from(list(ParseStatus))
pipeline_stage_st = st.sampled_from(list(PipelineStage))


# ═══════════════════════════════════════════════════════════════
# Property tests
# ═══════════════════════════════════════════════════════════════

@given(ps=parse_status_st)
@settings(max_examples=20, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_non_parsed_status_ignores_knowledge(ps):
    """For parse_status != parsed, the result depends only on parse_status,
    regardless of whether knowledge exists or what pipeline_stage it has."""
    if ps == ParseStatus.PARSED:
        return  # skip — parsed is handled separately

    raw_file = _make_raw_file(ps)
    result_no_knowledge = compute_pipeline_status(raw_file, None)
    result_with_knowledge = compute_pipeline_status(raw_file, _make_knowledge(PipelineStage.EMBEDDED))

    expected_stage, expected_progress, expected_message = PARSE_ONLY_EXPECTED[ps]

    # Both should produce the same result
    for result in [result_no_knowledge, result_with_knowledge]:
        assert result["stage"] == expected_stage
        assert result["progress"] == expected_progress
        assert result["message"] == expected_message


@given(stage=pipeline_stage_st)
@settings(max_examples=20, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_parsed_with_knowledge_matches_expected(stage):
    """When parse_status=parsed and knowledge exists, the result matches
    the expected mapping for each pipeline_stage."""
    raw_file = _make_raw_file(ParseStatus.PARSED)
    knowledge = _make_knowledge(stage)
    result = compute_pipeline_status(raw_file, knowledge)

    expected_stage, expected_progress, expected_message = PIPELINE_STAGE_EXPECTED[stage]
    assert result["stage"] == expected_stage
    assert result["progress"] == expected_progress
    assert result["message"] == expected_message

    # error field: non-null only for failed stage
    if stage == PipelineStage.FAILED:
        assert result["error"] is not None
    else:
        assert result["error"] is None


def test_parsed_without_knowledge():
    """When parse_status=parsed but knowledge is None, returns intermediate state."""
    raw_file = _make_raw_file(ParseStatus.PARSED)
    result = compute_pipeline_status(raw_file, None)

    expected_stage, expected_progress, expected_message = PARSED_NO_KNOWLEDGE
    assert result["stage"] == expected_stage
    assert result["progress"] == expected_progress
    assert result["message"] == expected_message
    assert result["error"] is None


def test_progress_monotonically_increases_along_happy_path():
    """Progress values along the happy path (pending → parsing → parsed/no-knowledge
    → pipeline pending → cleaned → outlined → stored → chunked → embedded)
    are strictly monotonically increasing."""
    happy_path_stages = [
        (ParseStatus.PENDING, None),
        (ParseStatus.PARSING, None),
        (ParseStatus.PARSED, None),  # no knowledge yet
        (ParseStatus.PARSED, PipelineStage.PENDING),
        (ParseStatus.PARSED, PipelineStage.CLEANED),
        (ParseStatus.PARSED, PipelineStage.OUTLINED),
        (ParseStatus.PARSED, PipelineStage.STORED),
        (ParseStatus.PARSED, PipelineStage.CHUNKED),
        (ParseStatus.PARSED, PipelineStage.EMBEDDED),
    ]

    progress_values = []
    for ps, pipeline_stage in happy_path_stages:
        raw_file = _make_raw_file(ps)
        knowledge = _make_knowledge(pipeline_stage) if pipeline_stage else None
        result = compute_pipeline_status(raw_file, knowledge)
        progress_values.append(result["progress"])

    # Verify strict monotonic increase
    for i in range(1, len(progress_values)):
        assert progress_values[i] > progress_values[i - 1], (
            f"Progress not strictly increasing at step {i}: "
            f"{progress_values[i - 1]} -> {progress_values[i]} "
            f"(stages: {happy_path_stages[i - 1]} -> {happy_path_stages[i]})"
        )


def test_progress_values_match_spec():
    """Verify exact progress values match the spec (requirements 5.10)."""
    assert compute_pipeline_status(
        _make_raw_file(ParseStatus.PENDING), None
    )["progress"] == 0

    assert compute_pipeline_status(
        _make_raw_file(ParseStatus.PARSING), None
    )["progress"] == 20

    assert compute_pipeline_status(
        _make_raw_file(ParseStatus.PARSE_FAILED), None
    )["progress"] == 100

    assert compute_pipeline_status(
        _make_raw_file(ParseStatus.PARSED), None
    )["progress"] == 30

    parsed_rf = _make_raw_file(ParseStatus.PARSED)
    assert compute_pipeline_status(parsed_rf, _make_knowledge(PipelineStage.PENDING))["progress"] == 40
    assert compute_pipeline_status(parsed_rf, _make_knowledge(PipelineStage.CLEANED))["progress"] == 50
    assert compute_pipeline_status(parsed_rf, _make_knowledge(PipelineStage.OUTLINED))["progress"] == 60
    assert compute_pipeline_status(parsed_rf, _make_knowledge(PipelineStage.STORED))["progress"] == 70
    assert compute_pipeline_status(parsed_rf, _make_knowledge(PipelineStage.CHUNKED))["progress"] == 80
    assert compute_pipeline_status(parsed_rf, _make_knowledge(PipelineStage.EMBEDDED))["progress"] == 100
    assert compute_pipeline_status(parsed_rf, _make_knowledge(PipelineStage.FAILED))["progress"] == 100


@given(ps=parse_status_st, stage=pipeline_stage_st)
@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_result_always_has_required_keys(ps, stage):
    """For any combination of parse_status × pipeline_stage, the result
    always contains the four required keys: stage, progress, message, error."""
    raw_file = _make_raw_file(ps)
    knowledge = _make_knowledge(stage) if ps == ParseStatus.PARSED else None
    result = compute_pipeline_status(raw_file, knowledge)

    assert "stage" in result
    assert "progress" in result
    assert "message" in result
    assert "error" in result
    assert isinstance(result["stage"], str)
    assert isinstance(result["progress"], int)
    assert isinstance(result["message"], str)
    assert result["error"] is None or isinstance(result["error"], str)


@given(ps=parse_status_st, stage=pipeline_stage_st)
@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_progress_within_bounds(ps, stage):
    """Progress is always between 0 and 100 inclusive."""
    raw_file = _make_raw_file(ps)
    knowledge = _make_knowledge(stage) if ps == ParseStatus.PARSED else None
    result = compute_pipeline_status(raw_file, knowledge)

    assert 0 <= result["progress"] <= 100


@given(ps=parse_status_st, stage=pipeline_stage_st)
@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_stage_is_valid_value(ps, stage):
    """The stage field is always one of the valid values."""
    valid_stages = {"upload", "parse", "digest", "done", "failed"}
    raw_file = _make_raw_file(ps)
    knowledge = _make_knowledge(stage) if ps == ParseStatus.PARSED else None
    result = compute_pipeline_status(raw_file, knowledge)

    assert result["stage"] in valid_stages, f"Invalid stage: {result['stage']}"


@given(ps=parse_status_st, stage=pipeline_stage_st)
@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_error_only_on_failure(ps, stage):
    """The error field is non-null only when stage is 'failed'."""
    raw_file = _make_raw_file(ps)
    knowledge = _make_knowledge(stage) if ps == ParseStatus.PARSED else None
    result = compute_pipeline_status(raw_file, knowledge)

    if result["stage"] == "failed":
        assert result["error"] is not None, "Failed stage should have error message"
    else:
        assert result["error"] is None, f"Non-failed stage '{result['stage']}' should not have error"


@given(ps=parse_status_st, stage=pipeline_stage_st)
@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_done_only_at_progress_100(ps, stage):
    """Stage 'done' only appears when progress is 100."""
    raw_file = _make_raw_file(ps)
    knowledge = _make_knowledge(stage) if ps == ParseStatus.PARSED else None
    result = compute_pipeline_status(raw_file, knowledge)

    if result["stage"] == "done":
        assert result["progress"] == 100
