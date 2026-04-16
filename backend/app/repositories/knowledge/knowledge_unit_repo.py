"""KnowledgeUnit repository helpers."""

from __future__ import annotations

import json

from sqlmodel import Session, func, select

from app.models.knowledge_unit import KnowledgeAlias, KnowledgeRevision, KnowledgeUnit
from app.models.knowledge_taxonomy import normalize_knowledge_unit_type, normalize_type_source
from app.utils.time import utcnow


def _load_json_list(raw: str) -> list[dict[str, object]]:
    try:
        payload = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def _dump_json_list(payload: list[dict[str, object]]) -> str:
    return json.dumps(payload, ensure_ascii=False)


def create_knowledge_unit(
    session: Session,
    knowledge_unit: KnowledgeUnit,
    *,
    auto_commit: bool = True,
) -> KnowledgeUnit:
    knowledge_unit.node_type = normalize_knowledge_unit_type(knowledge_unit.node_type)
    knowledge_unit.type_source = normalize_type_source(getattr(knowledge_unit, "type_source", None))
    knowledge_unit.type_confidence = max(0.0, min(1.0, float(knowledge_unit.type_confidence)))
    session.add(knowledge_unit)
    if auto_commit:
        session.commit()
        session.refresh(knowledge_unit)
    else:
        session.flush()
    return knowledge_unit


def get_knowledge_unit_by_id(session: Session, knowledge_unit_id: int) -> KnowledgeUnit | None:
    return session.get(KnowledgeUnit, knowledge_unit_id)


def find_knowledge_unit_by_normalized_name(
    session: Session,
    subject: str,
    normalized_name: str,
    knowledge_unit_type: str,
    *,
    include_pending: bool = True,
) -> KnowledgeUnit | None:
    knowledge_unit_type = normalize_knowledge_unit_type(knowledge_unit_type)
    allowed = ["active"]
    if include_pending:
        allowed.append("pending")
    stmt = select(KnowledgeUnit).where(
        KnowledgeUnit.subject == subject,
        KnowledgeUnit.normalized_name == normalized_name,
        KnowledgeUnit.node_type == knowledge_unit_type,
        KnowledgeUnit.status.in_(allowed),
    )
    return session.exec(stmt).first()


def find_knowledge_units_by_alias(
    session: Session,
    subject: str,
    normalized_alias: str,
    knowledge_unit_type: str,
) -> list[KnowledgeUnit]:
    knowledge_unit_type = normalize_knowledge_unit_type(knowledge_unit_type)
    stmt = select(KnowledgeUnit).where(
        KnowledgeUnit.subject == subject,
        KnowledgeUnit.node_type == knowledge_unit_type,
        KnowledgeUnit.status.in_(["active", "pending"]),
    )
    rows = list(session.exec(stmt).all())
    matched: list[KnowledgeUnit] = []
    for item in rows:
        aliases = _load_json_list(item.aliases_json)
        if any(alias.get("normalized_alias") == normalized_alias for alias in aliases):
            matched.append(item)
    return matched


def list_knowledge_units_by_subject(
    session: Session,
    subject: str,
    *,
    knowledge_unit_type: str | None = None,
    status: str | None = "active",
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[KnowledgeUnit], int]:
    base = select(KnowledgeUnit).where(KnowledgeUnit.subject == subject)
    count_base = select(func.count(KnowledgeUnit.id)).where(KnowledgeUnit.subject == subject)

    if status is not None:
        base = base.where(KnowledgeUnit.status == status)
        count_base = count_base.where(KnowledgeUnit.status == status)
    if knowledge_unit_type is not None:
        knowledge_unit_type = normalize_knowledge_unit_type(knowledge_unit_type)
        base = base.where(KnowledgeUnit.node_type == knowledge_unit_type)
        count_base = count_base.where(KnowledgeUnit.node_type == knowledge_unit_type)

    total: int = session.exec(count_base).one()
    rows = list(session.exec(base.offset(offset).limit(limit).order_by(KnowledgeUnit.id)).all())
    return rows, total


def get_knowledge_unit_with_current_revision(
    session: Session,
    knowledge_unit_id: int,
) -> tuple[KnowledgeUnit, KnowledgeRevision] | None:
    knowledge_unit = session.get(KnowledgeUnit, knowledge_unit_id)
    if knowledge_unit is None:
        return None
    revision = KnowledgeRevision(
        id=knowledge_unit.current_revision_id,
        node_id=knowledge_unit.id or 0,
        revision_no=1,
        title=knowledge_unit.canonical_name,
        summary=knowledge_unit.summary,
        body=knowledge_unit.body_markdown or knowledge_unit.body,
        revision_reason="materialized",
        is_current=True,
        created_at=knowledge_unit.updated_at,
    )
    return knowledge_unit, revision


def create_alias(
    session: Session,
    alias: KnowledgeAlias,
    *,
    auto_commit: bool = True,
) -> KnowledgeAlias:
    node = session.get(KnowledgeUnit, alias.node_id)
    if node is None:
        return alias

    payload = _load_json_list(node.aliases_json)
    payload.append(
        {
            "alias": alias.alias,
            "normalized_alias": alias.normalized_alias,
            "language": alias.language,
            "source": alias.source,
            "confidence": alias.confidence,
            "is_primary": alias.is_primary,
            "status": alias.status,
        }
    )
    node.aliases_json = _dump_json_list(payload)
    session.add(node)
    if auto_commit:
        session.commit()
    return alias


def find_alias(session: Session, subject: str, normalized_alias: str) -> list[KnowledgeAlias]:
    nodes = list(
        session.exec(
            select(KnowledgeUnit).where(
                KnowledgeUnit.subject == subject,
                KnowledgeUnit.status.in_(["active", "pending"]),
            )
        ).all()
    )
    matched: list[KnowledgeAlias] = []
    synthetic_id = 1
    for node in nodes:
        for alias in _load_json_list(node.aliases_json):
            if alias.get("normalized_alias") != normalized_alias:
                continue
            matched.append(
                KnowledgeAlias(
                    id=synthetic_id,
                    node_id=node.id or 0,
                    alias=str(alias.get("alias", "")),
                    normalized_alias=str(alias.get("normalized_alias", "")),
                    language=str(alias.get("language", "zh")),
                    source=str(alias.get("source", "llm")),
                    confidence=float(alias.get("confidence", 1.0)),
                    is_primary=bool(alias.get("is_primary", False)),
                    status=str(alias.get("status", "active")),
                )
            )
            synthetic_id += 1
    return matched


def list_aliases_by_knowledge_unit(session: Session, knowledge_unit_id: int) -> list[KnowledgeAlias]:
    knowledge_unit = session.get(KnowledgeUnit, knowledge_unit_id)
    if knowledge_unit is None:
        return []

    items: list[KnowledgeAlias] = []
    for index, alias in enumerate(_load_json_list(knowledge_unit.aliases_json), start=1):
        items.append(
            KnowledgeAlias(
                id=index,
                node_id=knowledge_unit_id,
                alias=str(alias.get("alias", "")),
                normalized_alias=str(alias.get("normalized_alias", "")),
                language=str(alias.get("language", "zh")),
                source=str(alias.get("source", "llm")),
                confidence=float(alias.get("confidence", 1.0)),
                is_primary=bool(alias.get("is_primary", False)),
                status=str(alias.get("status", "active")),
            )
        )
    return items


def create_knowledge_revision(
    session: Session,
    revision: KnowledgeRevision,
    *,
    auto_commit: bool = True,
) -> KnowledgeRevision:
    node = session.get(KnowledgeUnit, revision.node_id)
    if node is None:
        return revision

    revision.id = node.id
    node.summary = revision.summary
    node.body = revision.body
    node.body_markdown = revision.body
    node.current_revision_id = revision.id
    node.updated_at = utcnow()
    session.add(node)
    if auto_commit:
        session.commit()
    return revision


def deactivate_old_knowledge_unit_revisions(session: Session, knowledge_unit_id: int) -> None:
    del session, knowledge_unit_id

