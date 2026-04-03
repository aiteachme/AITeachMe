"""Study plan derivation and checklist persistence for digest outputs."""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict, deque
from datetime import datetime

from pydantic import BaseModel, Field
from sqlmodel import Session

from app.shared.infra.exceptions import NoPublishedDagError, NoPublishedTreeError
from app.schemas.knowledge import (
    StudyPlanItemResponse,
    StudyPlanPhaseResponse,
    StudyPlanRequest,
    StudyPlanResponse,
    ThemeTreeNodeResponse,
)
from app.services.knowledge.curriculum_service import (
    get_current_prereq_dag,
    get_current_theme_tree,
    get_teaching_units,
)
from app.utils.docgen_store import read_knowledge_build_status
from app.utils.path_helpers import build_knowledge_study_plan_progress_path
from app.utils.time import utcnow

_ANCHOR_RE = re.compile(r"[^\w\u4e00-\u9fff]+")


class StudyPlanProgressStore(BaseModel):
    """Persisted checklist completion state."""

    updated_at: datetime
    completed_items: dict[str, bool] = Field(default_factory=dict)


class _ThemeBucket(BaseModel):
    title: str
    summary: str = ""
    unit_ids: list[int] = Field(default_factory=list)
    theme_titles: list[str] = Field(default_factory=list)
    doc_anchor: str | None = None
    children: list["_ThemeBucket"] = Field(default_factory=list)


_ThemeBucket.model_rebuild()


def _anchorify(text: str) -> str:
    normalized = _ANCHOR_RE.sub("-", text.strip().lower()).strip("-")
    return normalized or "study-item"


def _stable_id(prefix: str, *parts: object) -> str:
    payload = "||".join(str(part) for part in parts if str(part).strip())
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:10]
    return f"{prefix}_{digest}"


def _read_progress(subject: str) -> StudyPlanProgressStore:
    path = build_knowledge_study_plan_progress_path(subject)
    if not path.exists():
        return StudyPlanProgressStore(updated_at=utcnow())
    try:
        return StudyPlanProgressStore.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception:
        return StudyPlanProgressStore(updated_at=utcnow())


def _write_progress(subject: str, progress: StudyPlanProgressStore) -> None:
    path = build_knowledge_study_plan_progress_path(subject)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(progress.model_dump_json(indent=2), encoding="utf-8")


def _collect_unit_ids(node: ThemeTreeNodeResponse) -> list[int]:
    unit_ids = [item.teaching_unit_id for item in node.units]
    for child in node.children:
        unit_ids.extend(_collect_unit_ids(child))
    deduped: list[int] = []
    seen: set[int] = set()
    for unit_id in unit_ids:
        if unit_id in seen:
            continue
        seen.add(unit_id)
        deduped.append(unit_id)
    return deduped


def _collect_theme_titles(node: ThemeTreeNodeResponse) -> list[str]:
    titles = [node.title]
    for child in node.children:
        titles.extend(_collect_theme_titles(child))
    deduped: list[str] = []
    seen: set[str] = set()
    for title in titles:
        key = title.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(title)
    return deduped


def _build_bucket(node: ThemeTreeNodeResponse) -> _ThemeBucket:
    return _ThemeBucket(
        title=node.title,
        summary=node.summary,
        unit_ids=_collect_unit_ids(node),
        theme_titles=_collect_theme_titles(node),
        doc_anchor=_anchorify(node.title),
        children=[_build_bucket(child) for child in node.children],
    )


def _topological_unit_order(subject: str, session: Session) -> dict[int, int]:
    try:
        dag = get_current_prereq_dag(session, subject=subject)
    except NoPublishedDagError:
        return {}

    adjacency: dict[int, list[int]] = defaultdict(list)
    indegree: dict[int, int] = defaultdict(int)
    node_ids: set[int] = set()
    for dependency in dag.dependencies:
        source_id = dependency.source_unit_id
        target_id = dependency.target_unit_id
        adjacency[source_id].append(target_id)
        indegree[target_id] += 1
        node_ids.add(source_id)
        node_ids.add(target_id)
        indegree.setdefault(source_id, 0)

    queue = deque(sorted(node_id for node_id in node_ids if indegree[node_id] == 0))
    order: dict[int, int] = {}
    index = 0
    while queue:
        current = queue.popleft()
        order[current] = index
        index += 1
        for neighbor in sorted(adjacency.get(current, [])):
            indegree[neighbor] -= 1
            if indegree[neighbor] == 0:
                queue.append(neighbor)

    for unit_id in sorted(node_ids):
        order.setdefault(unit_id, index)
        index += 1
    return order


def _group_sort_key(bucket: _ThemeBucket, unit_order: dict[int, int], fallback_index: int) -> tuple[int, str]:
    orders = [unit_order[unit_id] for unit_id in bucket.unit_ids if unit_id in unit_order]
    return (min(orders) if orders else fallback_index, bucket.title)


def _fallback_buckets(session: Session, subject: str) -> list[_ThemeBucket]:
    units = get_teaching_units(session, subject=subject, status="active", page=1, size=5000).items
    if not units:
        return []
    return [
        _ThemeBucket(
            title=unit.canonical_name,
            summary="从已发布教学单元生成的学习任务。",
            unit_ids=[unit.id],
            theme_titles=[unit.canonical_name],
            doc_anchor=_anchorify(unit.canonical_name),
        )
        for unit in units
    ]


def _load_theme_buckets(session: Session, subject: str) -> list[_ThemeBucket]:
    try:
        theme_tree = get_current_theme_tree(session, subject=subject)
    except NoPublishedTreeError:
        return _fallback_buckets(session, subject)

    if not theme_tree.tree:
        return _fallback_buckets(session, subject)
    return [_build_bucket(node) for node in theme_tree.tree]


def _bucket_duration_minutes(bucket: _ThemeBucket, digest_mode: str | None) -> int:
    base = 35 if digest_mode == "sprint" else 50
    multiplier = max(1, len(bucket.unit_ids) or len(bucket.children) or 1)
    return max(25, min(180, base * multiplier))


def _bucket_summary(bucket: _ThemeBucket, digest_mode: str | None) -> str:
    if digest_mode == "sprint":
        return bucket.summary or f"集中攻克 {bucket.title} 的题型、方法和易错点。"
    return bucket.summary or f"系统梳理 {bucket.title} 的概念链路、定义与关联主题。"


def _bucket_items(bucket: _ThemeBucket, *, digest_mode: str | None) -> list[_ThemeBucket]:
    if bucket.children:
        child_items = [child for child in bucket.children if child.unit_ids or child.children]
        if child_items:
            return child_items[: (3 if digest_mode == "sprint" else 6)]
    return [bucket]


def _chunk_buckets(buckets: list[_ThemeBucket], chunk_count: int) -> list[list[_ThemeBucket]]:
    if not buckets:
        return []
    chunk_count = max(1, min(chunk_count, len(buckets)))
    base, remainder = divmod(len(buckets), chunk_count)
    groups: list[list[_ThemeBucket]] = []
    cursor = 0
    for index in range(chunk_count):
        take = base + (1 if index < remainder else 0)
        group = buckets[cursor : cursor + take]
        cursor += take
        if group:
            groups.append(group)
    return groups


def _target_phase_count(bucket_count: int, digest_mode: str | None) -> int:
    if bucket_count <= 1:
        return 1
    if digest_mode == "sprint":
        return min(5, max(3, min(bucket_count, 4)))
    return min(8, max(3, bucket_count))


def _phase_title(index: int, digest_mode: str | None, group: list[_ThemeBucket]) -> str:
    lead_title = group[0].title if group else f"阶段 {index}"
    if digest_mode == "sprint":
        prefixes = ["摸底与框架", "方法突破", "题型巩固", "综合联结", "冲刺回看"]
        return f"阶段 {index}: {prefixes[min(index - 1, len(prefixes) - 1)]}"
    return f"阶段 {index}: {lead_title}"


def _phase_summary(group: list[_ThemeBucket], digest_mode: str | None) -> str:
    titles = "、".join(bucket.title for bucket in group[:3])
    if digest_mode == "sprint":
        return f"围绕 {titles} 压缩出最短闭环，优先方法、题型与错因。"
    return f"按依赖顺序系统推进 {titles}，同步沉淀概念与核心例题。"


def build_study_plan(session: Session, *, subject: str) -> StudyPlanResponse:
    """Derive a learner-facing study plan from published curriculum views."""

    build_status = read_knowledge_build_status(subject)
    digest_mode = build_status.digest_mode if build_status is not None else None
    mode_reason = build_status.mode_reason if build_status is not None else None
    progress = _read_progress(subject)
    unit_order = _topological_unit_order(subject, session)
    buckets = _load_theme_buckets(session, subject)
    sorted_buckets = sorted(
        buckets,
        key=lambda bucket: _group_sort_key(bucket, unit_order, len(unit_order) + buckets.index(bucket)),
    )
    phase_groups = _chunk_buckets(
        sorted_buckets,
        _target_phase_count(len(sorted_buckets), digest_mode),
    )

    phases: list[StudyPlanPhaseResponse] = []
    total_items = 0
    completed_items = 0

    for phase_index, bucket_group in enumerate(phase_groups, start=1):
        phase_items: list[StudyPlanItemResponse] = []
        for bucket in bucket_group:
            for item_bucket in _bucket_items(bucket, digest_mode=digest_mode):
                item_id = _stable_id(
                    "plan",
                    subject,
                    item_bucket.title,
                    ",".join(str(unit_id) for unit_id in item_bucket.unit_ids),
                )
                completed = bool(progress.completed_items.get(item_id, False))
                if completed:
                    completed_items += 1
                total_items += 1
                phase_items.append(
                    StudyPlanItemResponse(
                        id=item_id,
                        title=item_bucket.title,
                        summary=_bucket_summary(item_bucket, digest_mode),
                        duration_minutes=_bucket_duration_minutes(item_bucket, digest_mode),
                        depends_on_ids=[] if phase_index == 1 else [phases[-1].items[-1].id] if phases and phases[-1].items else [],
                        theme_titles=item_bucket.theme_titles[:6],
                        unit_ids=item_bucket.unit_ids,
                        doc_anchor=item_bucket.doc_anchor,
                        completed=completed,
                    )
                )

        phases.append(
            StudyPlanPhaseResponse(
                id=_stable_id("phase", subject, phase_index, ",".join(item.id for item in phase_items)),
                title=_phase_title(phase_index, digest_mode, bucket_group),
                summary=_phase_summary(bucket_group, digest_mode),
                duration_minutes=sum(item.duration_minutes for item in phase_items),
                completed_items=sum(1 for item in phase_items if item.completed),
                total_items=len(phase_items),
                items=phase_items,
            )
        )

    return StudyPlanResponse(
        subject=subject,
        generated_at=utcnow(),
        digest_mode=digest_mode,
        mode_reason=mode_reason,
        total_items=total_items,
        completed_items=completed_items,
        phases=phases,
    )


def handle_study_plan_request(
    session: Session,
    *,
    subject: str,
    payload: StudyPlanRequest | None = None,
) -> StudyPlanResponse:
    """Read or update the study plan through one shared request shape."""

    if payload is not None and payload.item_id and payload.completed is not None:
        progress = _read_progress(subject)
        progress.completed_items[payload.item_id] = payload.completed
        progress.updated_at = utcnow()
        _write_progress(subject, progress)
    return build_study_plan(session, subject=subject)


__all__ = [
    "build_study_plan",
    "handle_study_plan_request",
]
