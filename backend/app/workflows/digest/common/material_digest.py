"""Build raw planner material context from uploaded material."""

from __future__ import annotations

from dataclasses import dataclass

import structlog

from app.shared.infra.llm_support.context_window import ContextWindowManager
from app.shared.infra.llm_support.litellm_loader import load_litellm
from app.workflows.digest.common.models import DigestMaterialContext, SourcePacket

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class MaterialDigestResult:
    """Outcome of the raw context packing pass."""

    digest: str
    total_chars: int
    total_tokens: int
    source_count: int
    llm_used: bool


def _source_label(packet: SourcePacket, *, index: int) -> str:
    return packet.filename or f"file_{packet.file_id or index + 1}"


def _estimate_text_tokens(text: str) -> int:
    """Estimate token count without mutating the prompt material."""
    if not text.strip():
        return 0
    try:
        from app.shared.infra.llm_support.common import resolve_settings_model
        from app.shared.infra.settings import get_settings

        model, _selector = resolve_settings_model(get_settings(), "reason")
        litellm = load_litellm()
        return len(list(litellm.encode(model=model or "gpt-4o-mini", text=text)))
    except Exception:
        manager = ContextWindowManager()
        return manager.estimate_tokens(text)


def _render_packet_context(packet: SourcePacket, *, index: int, total: int) -> tuple[str, int]:
    content = (packet.normalized_content or "").strip()
    if not content:
        return "", 0
    token_count = _estimate_text_tokens(content)
    label = _source_label(packet, index=index)
    section = (
        f"===== 资料 {index + 1}/{total}：{label} =====\n"
        f"本资料约 {token_count} tokens，已完整拼接。\n"
        f"{content}"
    ).strip()
    return section, token_count


async def build_material_digest(
    material_context: DigestMaterialContext,
) -> MaterialDigestResult:
    """Return concatenated raw context for planner prompts.

    Planner 不再先走摘要模型，也不在 prompt 准备层静默截断资料。
    如果后续需要控量，应在资料选择、切片召回或模型上下文策略层显式处理。
    """

    packets = [
        packet
        for packet in list(material_context.source_documents)
        if (packet.normalized_content or "").strip()
    ]
    if not packets:
        return MaterialDigestResult(
            digest="",
            total_chars=0,
            total_tokens=0,
            source_count=0,
            llm_used=False,
        )

    total_chars = sum(len((packet.normalized_content or "").strip()) for packet in packets)
    results = [
        _render_packet_context(packet, index=index, total=len(packets))
        for index, packet in enumerate(packets)
    ]
    sections = [section for section, _token_count in results if section]
    return MaterialDigestResult(
        digest="\n\n".join(sections),
        total_chars=total_chars,
        total_tokens=sum(token_count for _section, token_count in results),
        source_count=len(packets),
        llm_used=False,
    )


__all__ = [
    "MaterialDigestResult",
    "build_material_digest",
]
