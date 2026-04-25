"""Shared preparation entrypoint for digest builds."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import structlog

from app.shared.infra.database import managed_session
from app.shared.infra.storage import get_content_store, resolve_subject_storage_scope
from app.models import RawFile
from app.repositories.files_repo import list_raw_files_by_ids
from app.workflows.digest.common.material_profile import (
    build_material_profile,
    decide_digest_mode,
)
from app.workflows.digest.common.asset_indexer import build_asset_registry
from app.workflows.digest.common.hint_extractor import extract_fast_topic_hints
from app.workflows.digest.common.models import ChunkIdentityMap, DigestMaterialContext, SharedInputs, SourcePacket
from app.workflows.digest.common.section_splitter import split_into_sections
from app.workflows.digest.common.subject_recognizer import recognize_subject_profile

logger = structlog.get_logger()

INLINE_FORMULA_PATTERN = re.compile(r"\$[^$\n]+\$|\$\$[^$]+\$\$", re.DOTALL)
TABLE_PATTERN = re.compile(r"^\s*\|.+\|\s*$", re.MULTILINE)
IMAGE_PATTERN = re.compile(r"!\[[^\]]*\]\(([^)]+)\)|<img[^>]+src=[\"']([^\"']+)[\"']", re.IGNORECASE)


async def prepare_shared_inputs(
    subject: str,
    file_ids: list[int],
    *,
    user_prompt: str | None = None,
) -> DigestMaterialContext:
    """Prepare shared inputs once for a digest build."""

    logger.info("shared_prepare_started", subject=subject, file_count=len(file_ids))
    source_packets = await load_source_packets(subject, file_ids)
    if not source_packets:
        logger.warning("shared_prepare_empty", subject=subject)
        return DigestMaterialContext()

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
    subject_profile = recognize_subject_profile(
        subject_slug=subject,
        source_packets=source_packets,
        section_packets=section_packets,
        fast_hints=fast_hints,
    )
    material_profile = build_material_profile(
        source_packets,
        section_packets,
        subject_profile,
    )
    digest_mode_decision = decide_digest_mode(
        material_profile,
        user_prompt=user_prompt,
        subject_profile=subject_profile,
    )
    material_context = DigestMaterialContext(
        source_documents=source_packets,
        material_sections=section_packets,
        chunk_identity_map=chunk_identity_map,
        material_hints=fast_hints,
        material_assets=build_asset_registry(subject, source_packets),
        learning_domain_profile=subject_profile,
        material_stats_profile=material_profile,
        course_mode_decision=digest_mode_decision,
    )
    logger.info(
        "shared_prepare_completed",
        subject=subject,
        source_count=len(source_packets),
        section_count=len(section_packets),
        asset_count=len(material_context.material_assets.assets),
        discipline=subject_profile.discipline,
        sub_discipline=subject_profile.sub_discipline,
        content_type=subject_profile.content_type,
        digest_mode=digest_mode_decision.mode.value,
        digest_mode_confidence=digest_mode_decision.confidence,
        exercise_density=material_profile.stats.exercise_density,
    )
    return material_context


async def prepare_material_context(
    subject: str,
    file_ids: list[int],
    *,
    user_prompt: str | None = None,
) -> DigestMaterialContext:
    """New canonical name for shared material preparation."""

    return await prepare_shared_inputs(subject, file_ids, user_prompt=user_prompt)


async def load_source_packets(subject: str, file_ids: list[int]) -> list[SourcePacket]:
    """Load parsed raw markdown and normalize it into source packets."""

    cs = get_content_store()
    subject_scope = resolve_subject_storage_scope(subject)
    requested_order = {file_id: index for index, file_id in enumerate(file_ids)}
    with managed_session() as session:
        raw_files = sorted(
            list_raw_files_by_ids(session, subject, file_ids),
            key=lambda raw_file: requested_order.get(int(raw_file.id or 0), len(requested_order)),
        )

    async def load_one(raw_file: RawFile) -> SourcePacket | None:
        if raw_file.id is None:
            return None

        file_id = int(raw_file.id)
        file_scope = cs.user_file_scope(user_id=raw_file.user_id or subject_scope.user_id)
        md_key = raw_file.markdown_path or file_scope.raw_markdown_key(
            file_uid=raw_file.uid,
            filename=raw_file.original_filename,
        )
        content = await cs.read_text(md_key, default="") or ""

        # fallback 到 DB 中的 parsed_markdown
        if not content.strip() and raw_file.parsed_markdown and raw_file.parsed_markdown.strip():
            content = raw_file.parsed_markdown

        markdown_path_str = md_key
        asset_dir_str = getattr(raw_file, "asset_dir", None) or file_scope.asset_prefix(
            file_uid=raw_file.uid,
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

    packets = await asyncio.gather(*(load_one(raw_file) for raw_file in raw_files))
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
