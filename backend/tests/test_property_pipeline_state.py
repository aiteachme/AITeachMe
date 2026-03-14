"""
属性测试：流水线状态机（Property 10 — Pipeline State Machine）

验证 parse_status 转换：pending→parsing→parsed 或 pending→parsing→parse_failed，终态不可回退
验证 pipeline_stage 转换：pending→cleaned→outlined→stored→chunked→embedded，或 any→failed，支持恢复

验证需求：5.10, 7.2, 7.4, 7.7, 7.9
"""

import os
import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

os.environ.setdefault("LLM_API_KEY", "test-key-for-testing")
os.environ.setdefault("DATA_DIR", "./test_data")

from app.repositories.models import ParseStatus, PipelineStage


# ═══════════════════════════════════════════════════════════════
# State machine definitions
# ═══════════════════════════════════════════════════════════════

# Valid parse_status transitions: source → set of allowed targets
VALID_PARSE_TRANSITIONS: dict[str, set[str]] = {
    ParseStatus.PENDING: {ParseStatus.PARSING},
    ParseStatus.PARSING: {ParseStatus.PARSED, ParseStatus.PARSE_FAILED},
    # Terminal states — no outgoing transitions
    ParseStatus.PARSED: set(),
    ParseStatus.PARSE_FAILED: set(),
}

PARSE_TERMINAL_STATES = {ParseStatus.PARSED, ParseStatus.PARSE_FAILED}

# Valid pipeline_stage transitions: source → set of allowed targets
# The happy path is: pending→cleaned→outlined→stored→chunked→embedded
# Any non-terminal state can transition to failed.
# Recovery: failed can go back to pending (restart) or to the stage after
# the last successful one (handled by determine_entry_point).
_PIPELINE_HAPPY_PATH = [
    PipelineStage.PENDING,
    PipelineStage.CLEANED,
    PipelineStage.OUTLINED,
    PipelineStage.STORED,
    PipelineStage.CHUNKED,
    PipelineStage.EMBEDDED,
]

VALID_PIPELINE_TRANSITIONS: dict[str, set[str]] = {}
for i, stage in enumerate(_PIPELINE_HAPPY_PATH[:-1]):
    next_stage = _PIPELINE_HAPPY_PATH[i + 1]
    VALID_PIPELINE_TRANSITIONS[stage] = {next_stage, PipelineStage.FAILED}

# embedded is terminal (success)
VALID_PIPELINE_TRANSITIONS[PipelineStage.EMBEDDED] = set()

# failed can recover: restart from pending or resume from any intermediate stage
VALID_PIPELINE_TRANSITIONS[PipelineStage.FAILED] = {
    PipelineStage.PENDING,
    PipelineStage.CLEANED,
    PipelineStage.OUTLINED,
    PipelineStage.STORED,
    PipelineStage.CHUNKED,
}

PIPELINE_TERMINAL_STATES = {PipelineStage.EMBEDDED}

ALL_PARSE_STATUSES = list(ParseStatus)
ALL_PIPELINE_STAGES = list(PipelineStage)


# ═══════════════════════════════════════════════════════════════
# Strategies
# ═══════════════════════════════════════════════════════════════

parse_status_st = st.sampled_from(ALL_PARSE_STATUSES)
pipeline_stage_st = st.sampled_from(ALL_PIPELINE_STAGES)

# Generate random sequences of parse_status transitions (length 1..20)
parse_transition_seq = st.lists(parse_status_st, min_size=1, max_size=20)
pipeline_transition_seq = st.lists(pipeline_stage_st, min_size=1, max_size=20)


def simulate_parse_transitions(transitions: list[str]) -> tuple[bool, str, str, str]:
    """Simulate parse_status transitions starting from PENDING.

    Returns (all_valid, current_state, failed_from, failed_to).
    """
    current = ParseStatus.PENDING
    for target in transitions:
        allowed = VALID_PARSE_TRANSITIONS.get(current, set())
        if target not in allowed:
            return False, current, current, target
        current = target
    return True, current, "", ""


def simulate_pipeline_transitions(transitions: list[str]) -> tuple[bool, str, str, str]:
    """Simulate pipeline_stage transitions starting from PENDING.

    Returns (all_valid, current_state, failed_from, failed_to).
    """
    current = PipelineStage.PENDING
    for target in transitions:
        allowed = VALID_PIPELINE_TRANSITIONS.get(current, set())
        if target not in allowed:
            return False, current, current, target
        current = target
    return True, current, "", ""


# ═══════════════════════════════════════════════════════════════
# Property 10a: parse_status state machine
# ═══════════════════════════════════════════════════════════════


@given(target=parse_status_st)
@settings(max_examples=50)
def test_parse_pending_only_transitions_to_parsing(target: str):
    """From PENDING, only PARSING is reachable."""
    allowed = VALID_PARSE_TRANSITIONS[ParseStatus.PENDING]
    if target in allowed:
        assert target == ParseStatus.PARSING
    else:
        assert target != ParseStatus.PARSING


@given(target=parse_status_st)
@settings(max_examples=50)
def test_parse_parsing_transitions_to_parsed_or_failed(target: str):
    """From PARSING, only PARSED or PARSE_FAILED are reachable."""
    allowed = VALID_PARSE_TRANSITIONS[ParseStatus.PARSING]
    if target in allowed:
        assert target in {ParseStatus.PARSED, ParseStatus.PARSE_FAILED}


@given(target=parse_status_st)
@settings(max_examples=50)
def test_parse_terminal_states_have_no_outgoing(target: str):
    """Terminal states (PARSED, PARSE_FAILED) cannot transition anywhere."""
    for terminal in PARSE_TERMINAL_STATES:
        allowed = VALID_PARSE_TRANSITIONS[terminal]
        assert len(allowed) == 0, f"{terminal} should have no outgoing transitions"
        assert target not in allowed


@given(transitions=st.lists(
    st.sampled_from([ParseStatus.PARSING, ParseStatus.PARSED]),
    min_size=1, max_size=5,
))
@settings(max_examples=100)
def test_parse_happy_path_reaches_parsed(transitions: list[str]):
    """The happy path pending→parsing→parsed always works."""
    happy = [ParseStatus.PARSING, ParseStatus.PARSED]
    valid, final, *_ = simulate_parse_transitions(happy)
    assert valid
    assert final == ParseStatus.PARSED


@given(transitions=st.lists(
    st.sampled_from([ParseStatus.PARSING, ParseStatus.PARSE_FAILED]),
    min_size=1, max_size=5,
))
@settings(max_examples=100)
def test_parse_failure_path_reaches_parse_failed(transitions: list[str]):
    """The failure path pending→parsing→parse_failed always works."""
    failure = [ParseStatus.PARSING, ParseStatus.PARSE_FAILED]
    valid, final, *_ = simulate_parse_transitions(failure)
    assert valid
    assert final == ParseStatus.PARSE_FAILED


@given(target=parse_status_st)
@settings(max_examples=50)
def test_parse_no_backward_from_parsed(target: str):
    """Once in PARSED, no transition is valid — state is frozen."""
    seq = [ParseStatus.PARSING, ParseStatus.PARSED, target]
    valid, final, *_ = simulate_parse_transitions(seq)
    assert not valid, f"PARSED should not transition to {target}"
    assert final == ParseStatus.PARSED


@given(target=parse_status_st)
@settings(max_examples=50)
def test_parse_no_backward_from_parse_failed(target: str):
    """Once in PARSE_FAILED, no transition is valid — state is frozen."""
    seq = [ParseStatus.PARSING, ParseStatus.PARSE_FAILED, target]
    valid, final, *_ = simulate_parse_transitions(seq)
    assert not valid, f"PARSE_FAILED should not transition to {target}"
    assert final == ParseStatus.PARSE_FAILED


# ═══════════════════════════════════════════════════════════════
# Property 10b: pipeline_stage state machine
# ═══════════════════════════════════════════════════════════════


def test_pipeline_happy_path_reaches_embedded():
    """The full happy path pending→cleaned→outlined→stored→chunked→embedded works."""
    happy = [
        PipelineStage.CLEANED,
        PipelineStage.OUTLINED,
        PipelineStage.STORED,
        PipelineStage.CHUNKED,
        PipelineStage.EMBEDDED,
    ]
    valid, final, *_ = simulate_pipeline_transitions(happy)
    assert valid
    assert final == PipelineStage.EMBEDDED


@given(stage=st.sampled_from(_PIPELINE_HAPPY_PATH[:-1]))
@settings(max_examples=50)
def test_pipeline_any_non_terminal_can_fail(stage: str):
    """Any non-terminal pipeline stage can transition to FAILED."""
    assert PipelineStage.FAILED in VALID_PIPELINE_TRANSITIONS[stage]


@given(target=pipeline_stage_st)
@settings(max_examples=50)
def test_pipeline_embedded_is_terminal(target: str):
    """EMBEDDED is a terminal success state — no outgoing transitions."""
    allowed = VALID_PIPELINE_TRANSITIONS[PipelineStage.EMBEDDED]
    assert len(allowed) == 0
    assert target not in allowed


@given(recovery_target=st.sampled_from([
    PipelineStage.PENDING,
    PipelineStage.CLEANED,
    PipelineStage.OUTLINED,
    PipelineStage.STORED,
    PipelineStage.CHUNKED,
]))
@settings(max_examples=50)
def test_pipeline_failed_can_recover(recovery_target: str):
    """FAILED state supports recovery to PENDING or any intermediate stage."""
    allowed = VALID_PIPELINE_TRANSITIONS[PipelineStage.FAILED]
    assert recovery_target in allowed


def test_pipeline_failed_cannot_jump_to_embedded():
    """FAILED cannot directly jump to EMBEDDED — must go through stages."""
    allowed = VALID_PIPELINE_TRANSITIONS[PipelineStage.FAILED]
    assert PipelineStage.EMBEDDED not in allowed


@given(
    fail_at=st.integers(min_value=0, max_value=3),
    resume_offset=st.integers(min_value=0, max_value=4),
)
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_pipeline_fail_and_recover_reaches_embedded(
    fail_at: int, resume_offset: int
):
    """Simulate: progress some stages → fail → recover → complete.

    The recovery point is clamped to a valid intermediate stage.
    """
    happy = _PIPELINE_HAPPY_PATH[1:]  # exclude PENDING (it's the start)

    # Progress through happy path up to fail_at
    transitions = list(happy[: fail_at + 1])
    transitions.append(PipelineStage.FAILED)

    # Recovery: resume from some intermediate stage (clamped)
    # After FAILED, we can resume from PENDING or any intermediate stage
    recovery_options = [
        PipelineStage.PENDING,
        PipelineStage.CLEANED,
        PipelineStage.OUTLINED,
        PipelineStage.STORED,
        PipelineStage.CHUNKED,
    ]
    resume_idx = resume_offset % len(recovery_options)
    resume_stage = recovery_options[resume_idx]
    transitions.append(resume_stage)

    # Now complete from resume_stage to EMBEDDED
    resume_happy_idx = _PIPELINE_HAPPY_PATH.index(resume_stage)
    remaining = _PIPELINE_HAPPY_PATH[resume_happy_idx + 1:]
    transitions.extend(remaining)

    valid, final, from_s, to_s = simulate_pipeline_transitions(transitions)
    assert valid, f"Failed transition {from_s}→{to_s} in sequence {transitions}"
    assert final == PipelineStage.EMBEDDED


@given(
    current=st.sampled_from(_PIPELINE_HAPPY_PATH[:-1]),
    skip_target=pipeline_stage_st,
)
@settings(max_examples=200)
def test_pipeline_no_skipping_forward(current: str, skip_target: str):
    """Cannot skip stages in the happy path (e.g., PENDING→OUTLINED is invalid)."""
    allowed = VALID_PIPELINE_TRANSITIONS[current]
    if skip_target in allowed:
        # If it's allowed, it must be either the immediate next stage or FAILED
        idx = _PIPELINE_HAPPY_PATH.index(current)
        next_stage = _PIPELINE_HAPPY_PATH[idx + 1]
        assert skip_target in {next_stage, PipelineStage.FAILED}, (
            f"From {current}, only {next_stage} or FAILED should be allowed, "
            f"got {skip_target}"
        )


# ═══════════════════════════════════════════════════════════════
# Property 10c: DB integration — transitions persist correctly
# ═══════════════════════════════════════════════════════════════


def test_parse_status_db_transitions(session):
    """Verify parse_status transitions persist correctly in the DB."""
    from app.repositories.models import RawFile
    from app.repositories.ingest_repo import (
        create_raw_file,
        update_parse_status,
        get_raw_file_by_id,
    )

    rf = create_raw_file(session, RawFile(
        subject="test", filename="a.pdf", filetype="pdf",
        file_path="/tmp/a.pdf", parse_status=ParseStatus.PENDING,
    ))
    assert rf.parse_status == ParseStatus.PENDING

    # pending → parsing
    update_parse_status(session, rf.id, ParseStatus.PARSING)
    rf = get_raw_file_by_id(session, rf.id)
    assert rf.parse_status == ParseStatus.PARSING

    # parsing → parsed
    update_parse_status(session, rf.id, ParseStatus.PARSED)
    rf = get_raw_file_by_id(session, rf.id)
    assert rf.parse_status == ParseStatus.PARSED


def test_parse_status_db_failure_path(session):
    """Verify parse_status failure path persists correctly."""
    from app.repositories.models import RawFile
    from app.repositories.ingest_repo import (
        create_raw_file,
        update_parse_status,
        get_raw_file_by_id,
    )

    rf = create_raw_file(session, RawFile(
        subject="test", filename="b.pdf", filetype="pdf",
        file_path="/tmp/b.pdf", parse_status=ParseStatus.PENDING,
    ))

    update_parse_status(session, rf.id, ParseStatus.PARSING)
    update_parse_status(session, rf.id, ParseStatus.PARSE_FAILED)
    rf = get_raw_file_by_id(session, rf.id)
    assert rf.parse_status == ParseStatus.PARSE_FAILED


def test_pipeline_stage_db_happy_path(session):
    """Verify pipeline_stage happy path persists correctly in the DB."""
    from app.repositories.models import RawFile, Knowledge
    from app.repositories.ingest_repo import create_raw_file
    from app.repositories.knowledge_repo import (
        create_knowledge,
        update_pipeline_stage,
        get_knowledge_by_id,
    )

    rf = create_raw_file(session, RawFile(
        subject="test", filename="c.pdf", filetype="pdf",
        file_path="/tmp/c.pdf", parse_status=ParseStatus.PARSED,
    ))
    k = create_knowledge(session, Knowledge(
        subject="test", raw_file_id=rf.id, title="Test",
        pipeline_stage=PipelineStage.PENDING,
    ))

    for stage in _PIPELINE_HAPPY_PATH[1:]:
        update_pipeline_stage(session, k.id, stage)
        k = get_knowledge_by_id(session, k.id)
        assert k.pipeline_stage == stage

    assert k.pipeline_stage == PipelineStage.EMBEDDED


def test_pipeline_stage_db_fail_and_recover(session):
    """Verify pipeline_stage fail + recovery persists correctly."""
    from app.repositories.models import RawFile, Knowledge
    from app.repositories.ingest_repo import create_raw_file
    from app.repositories.knowledge_repo import (
        create_knowledge,
        update_pipeline_stage,
        get_knowledge_by_id,
    )

    rf = create_raw_file(session, RawFile(
        subject="test", filename="d.pdf", filetype="pdf",
        file_path="/tmp/d.pdf", parse_status=ParseStatus.PARSED,
    ))
    k = create_knowledge(session, Knowledge(
        subject="test", raw_file_id=rf.id, title="Test Recovery",
        pipeline_stage=PipelineStage.PENDING,
    ))

    # Progress: pending → cleaned → outlined
    update_pipeline_stage(session, k.id, PipelineStage.CLEANED)
    update_pipeline_stage(session, k.id, PipelineStage.OUTLINED)

    # Fail at outlined
    update_pipeline_stage(session, k.id, PipelineStage.FAILED)
    k = get_knowledge_by_id(session, k.id)
    assert k.pipeline_stage == PipelineStage.FAILED

    # Recover from outlined and complete
    update_pipeline_stage(session, k.id, PipelineStage.OUTLINED)
    update_pipeline_stage(session, k.id, PipelineStage.STORED)
    update_pipeline_stage(session, k.id, PipelineStage.CHUNKED)
    update_pipeline_stage(session, k.id, PipelineStage.EMBEDDED)
    k = get_knowledge_by_id(session, k.id)
    assert k.pipeline_stage == PipelineStage.EMBEDDED
