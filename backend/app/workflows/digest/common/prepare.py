"""Shared preparation entrypoint for digest builds."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import structlog

from app.shared.infra.database import managed_session
from app.shared.infra.storage import get_content_store, resolve_course_storage_scope
from app.shared.infra.workflow.runtime import await_shielded_and_drain, cancel_tasks_and_drain, run_sync_and_drain
from app.models import RawFile
from app.repositories.files_repo import list_raw_files_by_ids
from app.workflows.digest.common.material_profile import (
    build_material_profile,
    decide_digest_mode,
)
from app.workflows.digest.common.asset_indexer import build_asset_registry
from app.workflows.digest.common.hint_extractor import extract_fast_topic_hints
from app.workflows.digest.common.models import ChunkIdentityMap, DigestMaterialContext, SourcePacket
from app.workflows.digest.common.section_splitter import split_into_sections
from app.workflows.digest.common.course_recognizer import recognize_course_profile

logger = structlog.get_logger()

INLINE_FORMULA_PATTERN = re.compile(r"\$[^$\n]+\$|\$\$[^$]+\$\$", re.DOTALL)
TABLE_PATTERN = re.compile(r"^\s*\|.+\|\s*$", re.MULTILINE)
IMAGE_PATTERN = re.compile(r"!\[[^\]]*\]\(([^)]+)\)|<img[^>]+src=[\"']([^\"']+)[\"']", re.IGNORECASE)
_SOURCE_READ_CONCURRENCY = 8


async def prepare_shared_inputs(
    course_id: str,
    file_ids: list[str],
    *,
    user_prompt: str | None = None,
) -> DigestMaterialContext:
    """Prepare shared inputs once for a digest build."""

    logger.info("shared_prepare_started", course_id=course_id, file_count=len(file_ids))
    source_packets = await load_source_packets(course_id, file_ids)
    if not source_packets:
        logger.warning("shared_prepare_empty", course_id=course_id)
        return DigestMaterialContext()

    return await run_sync_and_drain(
        _prepare_material_context, course_id, source_packets, user_prompt=user_prompt,
    )


def _prepare_material_context(
    course_id: str, source_packets: list[SourcePacket], *, user_prompt: str | None,
) -> DigestMaterialContext:
    section_packets = [
        section
        for packet in source_packets
        for section in split_into_sections(
            packet.normalized_content,
            file_id=packet.file_id,
            filename=packet.filename,
        )
    ]
    chunk_identity_map = ChunkIdentityMap(
        chunk_uid_to_section={
            section.digest_chunk_uid: index for index, section in enumerate(section_packets)
        },
        section_to_chunk_uid={
            index: section.digest_chunk_uid for index, section in enumerate(section_packets)
        },
    )
    fast_hints = extract_fast_topic_hints(section_packets)
    course_profile = recognize_course_profile(
        course_id=course_id,
        source_packets=source_packets,
        section_packets=section_packets,
        fast_hints=fast_hints,
    )
    material_profile = build_material_profile(
        source_packets,
        section_packets,
        course_profile,
    )
    digest_mode_decision = decide_digest_mode(
        material_profile,
        user_prompt=user_prompt,
        course_profile=course_profile,
    )
    material_context = DigestMaterialContext(
        source_documents=source_packets,
        material_sections=section_packets,
        chunk_identity_map=chunk_identity_map,
        material_hints=fast_hints,
        material_assets=build_asset_registry(course_id, source_packets),
        learning_domain_profile=course_profile,
        material_stats_profile=material_profile,
        course_mode_decision=digest_mode_decision,
    )
    logger.info(
        "shared_prepare_completed",
        course_id=course_id,
        source_count=len(source_packets),
        section_count=len(section_packets),
        asset_count=len(material_context.material_assets.assets),
        discipline=course_profile.discipline,
        sub_discipline=course_profile.sub_discipline,
        content_type=course_profile.content_type,
        digest_mode=digest_mode_decision.mode.value,
        digest_mode_confidence=digest_mode_decision.confidence,
        exercise_density=material_profile.stats.exercise_density,
    )
    return material_context


async def prepare_material_context(
    course_id: str,
    file_ids: list[str],
    *,
    user_prompt: str | None = None,
) -> DigestMaterialContext:
    """New canonical name for shared material preparation."""

    return await prepare_shared_inputs(course_id, file_ids, user_prompt=user_prompt)


async def load_source_packets(course_id: str, file_ids: list[str]) -> list[SourcePacket]:
    """Load parsed raw markdown and normalize it into source packets."""

    cs = get_content_store()
    requested_order = {file_id: index for index, file_id in enumerate(file_ids)}

    def load_records():
        course_scope = resolve_course_storage_scope(course_id)
        with managed_session() as session:
            raw_files = sorted(
                list_raw_files_by_ids(session, course_id, file_ids),
                key=lambda raw_file: requested_order.get(raw_file.id, len(requested_order)),
            )
            # Fully loaded, detached records can be read after the worker's
            # session closes, including when its commit expires ORM objects.
            for raw_file in raw_files:
                session.expunge(raw_file)
        return course_scope, raw_files

    course_scope, raw_files = await run_sync_and_drain(load_records)
    storage_reads = asyncio.Semaphore(_SOURCE_READ_CONCURRENCY)

    async def load_one(raw_file: RawFile) -> SourcePacket | None:
        if not raw_file.id:
            return None

        file_id = raw_file.id
        file_scope = cs.user_file_scope(user_id=raw_file.user_id or course_scope.user_id)
        md_key = raw_file.markdown_path or file_scope.raw_markdown_key(
            file_id=raw_file.id,
            filename=raw_file.original_filename,
        )
        # Ingest and Markdown edits persist the authoritative body in the DB.
        # Object storage is only needed for older records without that body.
        content = raw_file.parsed_markdown or ""
        if not content.strip():
            async with storage_reads:
                content = await cs.read_text(md_key, default="") or ""

        markdown_path_str = md_key
        asset_dir_str = getattr(raw_file, "asset_dir", None) or file_scope.asset_prefix(
            file_id=raw_file.id,
            filename=raw_file.original_filename,
        ).rstrip("/")

        if not content.strip():
            return None

        normalized_content = normalize_markdown_content(content)
        image_refs = extract_image_refs(normalized_content)
        return SourcePacket(
            file_id=file_id,
            filename=raw_file.original_filename,
            filetype=raw_file.file_ext,
            markdown_path=markdown_path_str,
            asset_dir=asset_dir_str,
            normalized_content=normalized_content,
            char_count=len(normalized_content),
            has_formulas=bool(INLINE_FORMULA_PATTERN.search(normalized_content)),
            has_tables=bool(TABLE_PATTERN.search(normalized_content)),
            has_images=bool(image_refs),
            image_refs=image_refs,
        )

    tasks = [asyncio.create_task(load_one(raw_file)) for raw_file in raw_files]
    try:
        packets = await asyncio.gather(*tasks)
    except BaseException:
        await await_shielded_and_drain(cancel_tasks_and_drain(tasks))
        raise
    return [packet for packet in packets if packet is not None]


def normalize_markdown_content(content: str) -> str:
    """Normalize markdown without any LLM calls."""

    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in normalized.split("\n")]
    collapsed: list[str] = []
    blank_count = 0
    for line in lines:
        if not line.strip():
            blank_count += 1
            if blank_count <= 2:
                collapsed.append("")
            continue
        blank_count = 0
        collapsed.append(line)
    return "\n".join(collapsed).strip()


def extract_image_refs(content: str) -> list[str]:
    """Extract referenced image file names from markdown."""

    refs: list[str] = []
    for match in IMAGE_PATTERN.finditer(content):
        raw = match.group(1) or match.group(2) or ""
        if not raw:
            continue
        refs.append(Path(raw.strip()).name)
    return list(dict.fromkeys(refs))
