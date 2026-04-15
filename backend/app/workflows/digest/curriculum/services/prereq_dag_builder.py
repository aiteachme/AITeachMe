"""鍏堜慨 DAG 鏋勫缓鍣細浠庣煡璇嗗浘璋变緷璧栬竟鑱氬悎鍑烘暀瀛﹀崟鍏冪骇鍒殑鍏堜慨 DAG銆?
绠楁硶娴佺▼锛? 姝ワ級锛?1. 鏀堕泦鑺傜偣绾т緷璧栬竟锛坧rerequisite_of + part_of 绾︽潫浼犳挱 + defined_by 淇濆畧绛栫暐锛?2. 鑱氬悎涓哄崟鍏冪骇渚濊禆锛堝悓涓€ unit 鍐呴儴鐨勪緷璧栬竟涓嶄骇鐢?UnitDependency锛?3. 鍘荤幆澶勭悊锛圱arjan SCC + 鏂紑 confidence 鏈€浣庤竟锛?4. 浼犻€掔害绠€锛坱ransitive reduction锛岀Щ闄ゅ啑浣欓棿鎺ヤ緷璧栵級
5. 鐢熸垚 PrereqDagVersion(status="draft")

纭鍒欙細
- 鍏堝幓鐜啀绾︾畝锛坱ransitive reduction 瀹氫箟鍩轰簬 DAG锛屽鍚幆鍥捐涓烘湭瀹氫箟锛?- 绂佹璋冪敤浠讳綍 publish/archive helper锛涘彧鑳藉垱寤?draft version + UnitDependency
- 鏂板缓璁板綍涓嶅啀鍐欏叆浠讳綍 *_job_id 瀛楁
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field

import structlog
from sqlmodel import Session, select

from app.workflows.digest.knowledge_graph.services.impact_analyzer import ImpactSet
from app.models.curriculum import (
    PrereqDagVersion,
    TeachingUnit,
    TeachingUnitMembership,
    UnitDependency,
)
from app.models.knowledge_graph import KnowledgeEdge
from app.repositories import curriculum_repo, kg_repo

logger = structlog.get_logger(__name__)

# 鈹€鈹€ 閰嶇疆甯搁噺 鈹€鈹€

DEFINED_BY_CONFIDENCE_THRESHOLD = 0.7
"""defined_by 杈圭敓鎴愯法 unit 渚濊禆鐨勬渶浣庣疆淇″害闃堝€笺€?""


# 鈹€鈹€ 鏁版嵁绫?鈹€鈹€


@dataclass
class UnitDependencyCandidate:
    """鍗曞厓绾т緷璧栧€欓€夈€?""

    source_unit_id: int  # 鍓嶇疆鍗曞厓
    target_unit_id: int  # 鍚庣画鍗曞厓
    dependency_type: str  # "prerequisite" | "corequisite"
    confidence: float
    supporting_edge_ids: list[int] = field(default_factory=list)
    supporting_edge_count: int = 0
    cycle_broken: bool = False  # 鏄惁鍥犲幓鐜绉婚櫎


# 鈹€鈹€ 鏍稿績绠楁硶鍑芥暟 鈹€鈹€


def _build_node_to_unit_map(
    session: Session,
    subject: str,
) -> dict[int, int]:
    """鏋勫缓 knowledge_node_id 鈫?unit_id 鏄犲皠锛堜粎 active units 鐨?core 鎴愬憳锛夈€?
    Returns:
        node_id 鈫?unit_id 鐨勬槧灏勫瓧鍏?    """
    # 鏌ヨ鎵€鏈?active 鍗曞厓
    active_units = session.exec(
        select(TeachingUnit).where(
            TeachingUnit.subject == subject,
            TeachingUnit.status == "active",
        )
    ).all()

    node_to_unit: dict[int, int] = {}
    for unit in active_units:
        memberships = curriculum_repo.list_memberships_by_unit(session, unit.id)  # type: ignore[arg-type]
        for m in memberships:
            # core 瑙掕壊浼樺厛锛泂upport/example/bridge 涔熻褰曪紙鐢ㄤ簬渚濊禆浼犳挱锛?            if m.knowledge_node_id not in node_to_unit or m.role == "core":
                node_to_unit[m.knowledge_node_id] = m.unit_id
    return node_to_unit


def _collect_dependency_edges(
    session: Session,
    subject: str,
    node_to_unit: dict[int, int],
) -> list[tuple[int, int, int, float, str]]:
    """Step 1锛氭敹闆嗚妭鐐圭骇渚濊禆杈癸紝杩斿洖 (source_node, target_node, edge_id, confidence, dep_type)銆?
    - prerequisite_of: A prerequisite_of B 鈫?A 鏄?B 鐨勫墠缃?鈫?UnitDep(source=unit_A, target=unit_B)
    - part_of: A part_of B 鈫?B 鐨勫墠缃篃鏄?A 鐨勫墠缃紙绾︽潫浼犳挱锛?    - defined_by: 淇濆畧绛栫暐锛孧VP 浠呭綋婊¤冻楂樼疆淇″害鏉′欢鏃舵墠鐢熸垚璺?unit 鍊欓€?    """
    result: list[tuple[int, int, int, float, str]] = []

    # prerequisite_of 杈癸細source 鏄墠缃紝target 鏄悗缁?    prereq_edges = kg_repo.list_edges_by_type(session, subject, "prerequisite_of")
    for edge in prereq_edges:
        result.append((
            edge.source_node_id,
            edge.target_node_id,
            edge.id,  # type: ignore[arg-type]
            edge.confidence,
            "prerequisite",
        ))

    # part_of 杈癸細A part_of B 鈫?B 鐨勫墠缃篃鏄?A 鐨勫墠缃?    # 瀹炵幇锛氬鏋?B 鏈?prerequisite_of 杈规寚鍚?C锛屽垯 A 涔熶緷璧?C
    part_of_edges = kg_repo.list_edges_by_type(session, subject, "part_of")
    # 鏋勫缓 child 鈫?parent 鏄犲皠
    child_to_parents: dict[int, list[int]] = defaultdict(list)
    for edge in part_of_edges:
        child_to_parents[edge.source_node_id].append(edge.target_node_id)

    # 瀵规瘡鏉?prerequisite 杈癸紝浼犳挱鍒?part_of 瀛愯妭鐐?    for edge in prereq_edges:
        source_id = edge.source_node_id
        # 濡傛灉 source 鏈?children锛堥€氳繃 part_of锛夛紝杩欎簺 children 涔熶緷璧?target
        # 浣嗚繖閲屾垜浠叧娉ㄧ殑鏄細濡傛灉 B 鏈夊墠缃?A锛屼笖 C part_of B锛屽垯 C 涔熶緷璧?A
        # 鍗?target 鐨?children 涔熼渶瑕?source 浣滀负鍓嶇疆
        # 鏌ユ壘 target 鐨?children
        pass  # part_of 浼犳挱鍦ㄤ笅闈㈢粺涓€澶勭悊

    # part_of 绾︽潫浼犳挱锛欰 part_of B 鈫?A 缁ф壙 B 鐨勬墍鏈夊墠缃緷璧?    # 鏋勫缓 parent 鈫?[prerequisite source nodes] 鏄犲皠
    parent_prereqs: dict[int, list[tuple[int, float]]] = defaultdict(list)
    for edge in prereq_edges:
        parent_prereqs[edge.target_node_id].append((
            edge.source_node_id, edge.confidence,
        ))

    for po_edge in part_of_edges:
        child_id = po_edge.source_node_id
        parent_id = po_edge.target_node_id
        # child 缁ф壙 parent 鐨勫墠缃緷璧?        for prereq_source_id, prereq_conf in parent_prereqs.get(parent_id, []):
            # 缃俊搴﹀彇 part_of 杈瑰拰 prerequisite 杈圭殑杈冧綆鍊?            combined_conf = min(po_edge.confidence, prereq_conf)
            result.append((
                prereq_source_id,
                child_id,
                po_edge.id,  # type: ignore[arg-type]
                combined_conf,
                "prerequisite",
            ))

    # defined_by 杈癸細淇濆畧绛栫暐
    # MVP锛氫粎褰?Concept 涓?Definition 宸茶鍒嗗埌涓嶅悓 units 涓旀弧瓒抽珮缃俊搴︽椂
    defined_by_edges = kg_repo.list_edges_by_type(session, subject, "defined_by")
    for edge in defined_by_edges:
        if edge.confidence <= DEFINED_BY_CONFIDENCE_THRESHOLD:
            continue
        src_unit = node_to_unit.get(edge.source_node_id)
        tgt_unit = node_to_unit.get(edge.target_node_id)
        if src_unit is None or tgt_unit is None:
            continue
        if src_unit == tgt_unit:
            continue  # 鍚屼竴 unit 鍐咃紝涓嶇敓鎴愯法 unit 渚濊禆
        # defined_by: A defined_by B 鈫?B 瀹氫箟浜?A 鈫?B 鏄?A 鐨勫墠缃?        result.append((
            edge.target_node_id,  # 瀹氫箟鑰呮槸鍓嶇疆
            edge.source_node_id,  # 琚畾涔夎€呮槸鍚庣画
            edge.id,  # type: ignore[arg-type]
            edge.confidence * 0.8,  # 闄嶆潈锛屽洜涓?defined_by 涓嶅 prerequisite_of 寮?            "prerequisite",
        ))

    return result


def aggregate_unit_dependencies(
    dependency_edges: list[tuple[int, int, int, float, str]],
    node_to_unit: dict[int, int],
) -> list[UnitDependencyCandidate]:
    """Step 2锛氬皢鑺傜偣绾т緷璧栬竟鑱氬悎涓哄崟鍏冪骇渚濊禆銆?
    鍚屼竴 unit 鍐呴儴鐨勪緷璧栬竟涓嶄骇鐢?UnitDependency銆?    """
    # 鑱氬悎閿細(source_unit_id, target_unit_id, dep_type)
    agg: dict[tuple[int, int, str], UnitDependencyCandidate] = {}

    for src_node, tgt_node, edge_id, confidence, dep_type in dependency_edges:
        src_unit = node_to_unit.get(src_node)
        tgt_unit = node_to_unit.get(tgt_node)

        if src_unit is None or tgt_unit is None:
            continue  # 鑺傜偣涓嶅睘浜庝换浣?unit锛岃烦杩?        if src_unit == tgt_unit:
            continue  # 鍚屼竴 unit 鍐呴儴锛屼笉浜х敓 UnitDependency

        key = (src_unit, tgt_unit, dep_type)
        if key not in agg:
            agg[key] = UnitDependencyCandidate(
                source_unit_id=src_unit,
                target_unit_id=tgt_unit,
                dependency_type=dep_type,
                confidence=0.0,
                supporting_edge_ids=[],
                supporting_edge_count=0,
            )
        cand = agg[key]
        cand.supporting_edge_ids.append(edge_id)
        cand.supporting_edge_count += 1

    # 璁＄畻鑱氬悎 confidence锛氬姞鏉冨钩鍧?    for key, cand in agg.items():
        # 浠庡師濮嬭竟涓敹闆嗗搴旂殑 confidence 鍊?        edge_confidences = []
        for src_node, tgt_node, edge_id, confidence, dep_type in dependency_edges:
            if edge_id in cand.supporting_edge_ids:
                edge_confidences.append(confidence)
        if edge_confidences:
            # confidence = weighted_sum / max_possible
            cand.confidence = min(0.95, sum(edge_confidences) / max(len(edge_confidences), 1))

    return list(agg.values())


def break_cycles(
    edges: list[UnitDependencyCandidate],
) -> tuple[list[UnitDependencyCandidate], list[UnitDependencyCandidate]]:
    """Step 3锛氬幓鐜鐞嗭紙Tarjan SCC + 鏂紑 confidence 鏈€浣庤竟锛夈€?
    Returns:
        (acyclic_edges, broken_edges) 鈥?鏃犵幆杈瑰垪琛ㄥ拰琚柇寮€鐨勮竟鍒楄〃
    """
    if not edges:
        return [], []

    # 鏋勫缓閭绘帴琛?    graph: dict[int, list[int]] = defaultdict(list)
    edge_map: dict[tuple[int, int], UnitDependencyCandidate] = {}
    nodes: set[int] = set()

    for e in edges:
        graph[e.source_unit_id].append(e.target_unit_id)
        edge_map[(e.source_unit_id, e.target_unit_id)] = e
        nodes.add(e.source_unit_id)
        nodes.add(e.target_unit_id)

    # Tarjan SCC 绠楁硶
    sccs = _tarjan_scc(graph, nodes)

    broken: list[UnitDependencyCandidate] = []
    removed_keys: set[tuple[int, int]] = set()

    # 瀵规瘡涓ぇ灏?> 1 鐨?SCC锛岃凯浠ｆ柇寮€鏈€浣?confidence 杈圭洿鍒版棤鐜?    for scc in sccs:
        if len(scc) <= 1:
            continue

        scc_set = set(scc)
        # 鏀堕泦 SCC 鍐呴儴鐨勮竟
        scc_edges = [
            e for e in edges
            if e.source_unit_id in scc_set
            and e.target_unit_id in scc_set
            and (e.source_unit_id, e.target_unit_id) not in removed_keys
        ]

        # 杩唬鏂竟鐩村埌 SCC 鍐呮棤鐜?        while _has_cycle_in_subgraph(scc_edges):
            if not scc_edges:
                break
            # 鎵?confidence 鏈€浣庣殑杈?            weakest = min(scc_edges, key=lambda e: e.confidence)
            weakest.cycle_broken = True
            broken.append(weakest)
            removed_keys.add((weakest.source_unit_id, weakest.target_unit_id))
            scc_edges = [
                e for e in scc_edges
                if (e.source_unit_id, e.target_unit_id) not in removed_keys
            ]

    acyclic = [
        e for e in edges
        if (e.source_unit_id, e.target_unit_id) not in removed_keys
    ]

    if broken:
        logger.info(
            "dag_cycles_broken",
            broken_count=len(broken),
            broken_edges=[
                {"src": e.source_unit_id, "tgt": e.target_unit_id, "conf": e.confidence}
                for e in broken
            ],
        )

    return acyclic, broken


def _tarjan_scc(
    graph: dict[int, list[int]],
    nodes: set[int],
) -> list[list[int]]:
    """Tarjan 寮鸿繛閫氬垎閲忕畻娉曘€?""
    index_counter = [0]
    stack: list[int] = []
    on_stack: set[int] = set()
    index_map: dict[int, int] = {}
    lowlink: dict[int, int] = {}
    result: list[list[int]] = []

    def strongconnect(v: int) -> None:
        index_map[v] = index_counter[0]
        lowlink[v] = index_counter[0]
        index_counter[0] += 1
        stack.append(v)
        on_stack.add(v)

        for w in graph.get(v, []):
            if w not in index_map:
                strongconnect(w)
                lowlink[v] = min(lowlink[v], lowlink[w])
            elif w in on_stack:
                lowlink[v] = min(lowlink[v], index_map[w])

        if lowlink[v] == index_map[v]:
            component: list[int] = []
            while True:
                w = stack.pop()
                on_stack.discard(w)
                component.append(w)
                if w == v:
                    break
            result.append(component)

    for node in nodes:
        if node not in index_map:
            strongconnect(node)

    return result


def _has_cycle_in_subgraph(edges: list[UnitDependencyCandidate]) -> bool:
    """妫€娴嬭竟鍒楄〃鏋勬垚鐨勫瓙鍥炬槸鍚﹀惈鐜紙DFS 妫€娴嬶級銆?""
    if not edges:
        return False

    graph: dict[int, list[int]] = defaultdict(list)
    nodes: set[int] = set()
    for e in edges:
        graph[e.source_unit_id].append(e.target_unit_id)
        nodes.add(e.source_unit_id)
        nodes.add(e.target_unit_id)

    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[int, int] = {n: WHITE for n in nodes}

    def dfs(u: int) -> bool:
        color[u] = GRAY
        for v in graph.get(u, []):
            if color.get(v, WHITE) == GRAY:
                return True
            if color.get(v, WHITE) == WHITE and dfs(v):
                return True
        color[u] = BLACK
        return False

    return any(color[n] == WHITE and dfs(n) for n in nodes)


def transitive_reduction(
    edges: list[UnitDependencyCandidate],
) -> list[UnitDependencyCandidate]:
    """Step 4锛氫紶閫掔害绠€锛圱ransitive Reduction锛夈€?
    瀵瑰凡纭鏃犵幆鐨?DAG 鎵ц浼犻€掔害绠€锛?    濡傛灉 A 鈫?B 鈫?C 涓?A 鈫?C 鍚屾椂瀛樺湪锛岀Щ闄?A 鈫?C锛堝啑浣欒竟锛夈€?
    绠楁硶锛氬姣忔潯杈?(u, v)锛屾鏌ユ槸鍚﹀瓨鍦ㄤ笉缁忚繃璇ヨ竟鐨?u 鈫?v 璺緞銆?    鑻ュ瓨鍦紝鍒欒杈瑰啑浣欙紝鍙Щ闄ゃ€?    """
    if not edges:
        return []

    # 鏋勫缓閭绘帴琛?    graph: dict[int, set[int]] = defaultdict(set)
    for e in edges:
        graph[e.source_unit_id].add(e.target_unit_id)

    # 瀵规瘡鏉¤竟妫€鏌ユ槸鍚﹀啑浣?    edge_set = {(e.source_unit_id, e.target_unit_id) for e in edges}
    redundant: set[tuple[int, int]] = set()

    for e in edges:
        u, v = e.source_unit_id, e.target_unit_id
        # 妫€鏌ユ槸鍚﹀瓨鍦?u 鈫?... 鈫?v 鐨勮矾寰勶紙涓嶇洿鎺ョ粡杩?u 鈫?v锛?        if _has_indirect_path(graph, u, v, edge_set):
            redundant.add((u, v))

    if redundant:
        logger.info(
            "dag_transitive_reduction",
            removed_count=len(redundant),
            removed_edges=list(redundant),
        )

    return [
        e for e in edges
        if (e.source_unit_id, e.target_unit_id) not in redundant
    ]


def _has_indirect_path(
    graph: dict[int, set[int]],
    source: int,
    target: int,
    all_edges: set[tuple[int, int]],
) -> bool:
    """妫€鏌ヤ粠 source 鍒?target 鏄惁瀛樺湪涓嶇洿鎺ヤ娇鐢?source鈫抰arget 杈圭殑璺緞銆?
    BFS 浠?source 鐨勫叾浠栭偦灞呭嚭鍙戯紝鐪嬭兘鍚﹀埌杈?target銆?    """
    # 浠?source 鐨勯偦灞呭嚭鍙戯紙鎺掗櫎鐩存帴鍒?target 鐨勮竟锛?    start_nodes = graph.get(source, set()) - {target}
    if not start_nodes:
        return False

    visited: set[int] = {source}
    queue = list(start_nodes)
    visited.update(start_nodes)

    while queue:
        current = queue.pop(0)
        if current == target:
            return True
        for neighbor in graph.get(current, set()):
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append(neighbor)

    return False


# 鈹€鈹€ 涓诲叆鍙?鈹€鈹€


async def derive_prereq_dag(
    session: Session,
    subject: str,
    impact_set: ImpactSet,
    curriculum_job_id: int,
    prev_dag_version: PrereqDagVersion | None = None,
) -> PrereqDagVersion:
    """鍏堜慨 DAG 娲剧敓涓诲嚱鏁般€?
    鎸?Step 1-5 鎵ц锛氭敹闆?鈫?鑱氬悎 鈫?鍘荤幆 鈫?绾︾畝 鈫?鐢熸垚鐗堟湰銆?    MVP 閲囩敤"閫昏緫灞€閮ㄩ噸绠?+ 瀛樺偍鍏ㄩ噺蹇収"鐗堟湰绛栫暐銆?
    Args:
        session: 鏁版嵁搴撲細璇?        subject: 瀛︾鏍囪瘑
        impact_set: 褰卞搷闆?        curriculum_job_id: 褰撳墠 CurriculumDeriveJob ID
        prev_dag_version: 涓婁竴涓?DAG 鐗堟湰锛堢敤浜庣‘瀹氱増鏈彿锛?
    Returns:
        鏂板垱寤虹殑 PrereqDagVersion锛坰tatus="draft"锛?    """
    logger.info(
        "prereq_dag_derive_start",
        subject=subject,
        curriculum_job_id=curriculum_job_id,
        affected_units=len(impact_set.affected_unit_ids),
    )

    # Step 1锛氭瀯寤?node 鈫?unit 鏄犲皠 & 鏀堕泦鑺傜偣绾т緷璧栬竟
    node_to_unit = _build_node_to_unit_map(session, subject)
    dependency_edges = _collect_dependency_edges(session, subject, node_to_unit)

    logger.info(
        "prereq_dag_step1_edges_collected",
        total_dependency_edges=len(dependency_edges),
    )

    # Step 2锛氳仛鍚堜负鍗曞厓绾т緷璧?    unit_deps = aggregate_unit_dependencies(dependency_edges, node_to_unit)

    logger.info(
        "prereq_dag_step2_aggregated",
        unit_dependency_candidates=len(unit_deps),
    )

    # Step 3锛氬幓鐜紙纭鍒欙細鍏堝幓鐜啀绾︾畝锛?    acyclic_edges, broken_edges = break_cycles(unit_deps)

    logger.info(
        "prereq_dag_step3_cycles_broken",
        acyclic_count=len(acyclic_edges),
        broken_count=len(broken_edges),
    )

    # Step 4锛氫紶閫掔害绠€
    reduced_edges = transitive_reduction(acyclic_edges)

    logger.info(
        "prereq_dag_step4_reduced",
        final_edge_count=len(reduced_edges),
        removed_by_reduction=len(acyclic_edges) - len(reduced_edges),
    )

    # Step 5锛氬垱寤?PrereqDagVersion(status="draft") + UnitDependency 璁板綍
    prev_version_no = prev_dag_version.version_no if prev_dag_version else 0
    dag_version = curriculum_repo.create_prereq_dag_version_with_optimistic_lock(
        session, subject, prev_version_no,
    )
    # 鍐欏叆 UnitDependency 璁板綍
    for edge_cand in reduced_edges:
        # 鏋勫缓 derivation_metadata
        metadata = {
            "supporting_edge_ids": edge_cand.supporting_edge_ids,
            "confidence_details": {
                "aggregated_confidence": edge_cand.confidence,
                "supporting_edge_count": edge_cand.supporting_edge_count,
            },
        }

        dep = UnitDependency(
            subject=subject,
            dag_version_id=dag_version.id,  # type: ignore[arg-type]
            source_unit_id=edge_cand.source_unit_id,
            target_unit_id=edge_cand.target_unit_id,
            dependency_type=edge_cand.dependency_type,
            confidence=edge_cand.confidence,
            supporting_edge_count=edge_cand.supporting_edge_count,
            derivation_metadata_json=json.dumps(metadata, ensure_ascii=False),
        )
        curriculum_repo.create_unit_dependency(session, dep)

    # 璁板綍琚柇寮€鐨勭幆璺竟鍒版棩蹇楋紙渚涗汉宸ュ鏌ワ級
    if broken_edges:
        for be in broken_edges:
            logger.warning(
                "prereq_dag_cycle_edge_broken",
                source_unit_id=be.source_unit_id,
                target_unit_id=be.target_unit_id,
                confidence=be.confidence,
                supporting_edge_ids=be.supporting_edge_ids,
            )

    logger.info(
        "prereq_dag_derive_complete",
        subject=subject,
        dag_version_id=dag_version.id,
        version_no=dag_version.version_no,
        total_dependencies=len(reduced_edges),
        cycles_broken=len(broken_edges),
    )

    return dag_version

