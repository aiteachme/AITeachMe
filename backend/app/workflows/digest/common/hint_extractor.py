"""Rule-based fast hint extraction for unified digest builds."""

from __future__ import annotations

from collections import Counter

import structlog

from app.workflows.digest.common.models import FastTopicHints, SectionPacket

logger = structlog.get_logger()


def extract_fast_topic_hints(section_packets: list[SectionPacket]) -> FastTopicHints:
    """Extract rule-based topic hints without any LLM calls."""

    if not section_packets:
        return FastTopicHints()

    high_freq_terms = Counter(
        token
        for packet in section_packets
        for token in packet.header_candidates
        if len(token) >= 2
    ).most_common(24)

    chapter_candidates = list(
        dict.fromkeys(
            packet.title
            for packet in section_packets
            if packet.level <= 2 and packet.title.strip()
        )
    )[:18]

    formula_patterns = list(
        dict.fromkeys(
            formula
            for packet in section_packets
            for formula in packet.formula_refs
            if formula.strip()
        )
    )[:20]

    total_questions = sum(packet.question_block_count for packet in section_packets)
    question_density = min(total_questions / max(len(section_packets), 1) / 5.0, 1.0)

    hints = FastTopicHints(
        high_freq_terms=high_freq_terms,
        chapter_candidates=chapter_candidates,
        formula_patterns=formula_patterns,
        question_density=question_density,
    )
    logger.info(
        "fast_hints_extracted",
        high_freq_term_count=len(hints.high_freq_terms),
        chapter_candidate_count=len(hints.chapter_candidates),
        formula_pattern_count=len(hints.formula_patterns),
        question_density=question_density,
    )
    return hints

