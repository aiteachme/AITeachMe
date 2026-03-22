"""知识接口。"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Body, Depends, Path
from sqlmodel import Session

from app.api.deps import get_db, normalize_subject_slug
from app.api.openapi import build_error_responses
from app.schemas.common import ApiResponse, PaginatedData, ok_response
from app.schemas.knowledge import (
    ChunkContextRequest,
    ChunkContextResponse,
    ClearKnowledgeResponse,
    CurriculumSnapshotResponse,
    DigestBuildData,
    DigestBuildRequest,
    DigestStatusRequest,
    DigestStatusResponse,
    EvidenceContextRequest,
    EvidenceContextResponse,
    FullGraphResponse,
    GraphNodeDetailRequest,
    GraphNodesQueryRequest,
    KnowledgeNodeDetailResponse,
    KnowledgeNodeResponse,
    PrereqDagResponse,
    TaxonomyAnchorResponse,
    TeachingUnitDetailResponse,
    TeachingUnitResponse,
    ThemeTreeResponse,
    UnitDetailRequest,
    UnitsQueryRequest,
    AnchorManageRequest,
    DocGenBuildRequest,
    DocGenBuildData,
    DocGenGetResponse,
)
from app.services.knowledge.curriculum_service import (
    clear_subject_knowledge,
    get_current_curriculum_snapshot,
    get_current_prereq_dag,
    get_current_theme_tree,
    get_teaching_unit_detail,
    get_teaching_units,
    manage_taxonomy_anchors,
)
from app.services.knowledge.digest_service import (
    ensure_docgen_started,
    get_digest_status,
    get_docgen_result,
    run_graph_digest_background,
    trigger_digest_build,
    trigger_docgen_build,
    run_docgen_background,
)
from app.services.knowledge.graph_query_service import (
    get_evidence_context,
    get_full_graph,
    get_graph_node_detail,
    get_graph_nodes,
    get_chunk_context,
)
from app.services.subject_service import get_subject_record

router = APIRouter(prefix="/api/v1/subjects/{subject}/knowledge", tags=["knowledge"])


_MIDDLE_EAST_MOCK_SECTION = """
当前中东局势呈现出“高冲突密度、强外部介入、弱制度托底”的复合结构。加沙战事的外溢效应，已经从人道议题延伸到红海航运安全、能源价格预期、地区代理人博弈和全球供应链稳定性。地缘政治层面，地区国家普遍采取“安全优先+风险对冲”策略，一方面强化边境与内部安全体系，另一方面通过多边外交维持与主要外部力量的沟通通道，以避免局部冲突升级为系统性对抗。经济层面，海湾产油国仍有财政缓冲，但高强度安全投入与转型项目并行推进，财政结构更依赖油价中枢稳定与主权基金调节。社会层面，难民安置、基础设施受损、青年失业和公共服务承压形成长期治理负担，冲突记忆叠加社交媒体传播，使群体情绪更容易在短时间内被事件触发并放大。外交层面，停火、换俘、援助通道与重建安排彼此嵌套，任何单点突破都需要与更大框架联动，否则容易在执行阶段失效。军事层面，非对称打击、无人机与导弹威慑持续存在，低烈度高频互动提高了误判概率。总体看，中东正处于“战术层面反复拉扯、战略层面寻求再平衡”的过渡期，短期难以形成稳定终局，但各方对“失控升级”的共同担忧，仍为有限降温提供了现实空间。
""".strip()


def _build_mock_middle_east_markdown(subject: str) -> str:
    sections = [
        "冲突主轴与风险外溢",
        "加沙战事的人道与政治后果",
        "红海航道安全与全球物流扰动",
        "以色列安全政策与战略压力",
        "巴勒斯坦内部治理与重建难题",
        "黎巴嫩方向的边境摩擦与威慑平衡",
        "叙利亚战后碎片化治理现实",
        "伊拉克安全与国内政治博弈",
        "伊朗地区影响力与多线策略",
        "海湾国家的安全对冲与经济转型",
        "土耳其在周边事务中的角色调整",
        "埃及与约旦的边境与民生压力",
        "美国在中东的再平衡与约束",
        "欧洲立场分化与能源安全考量",
        "俄罗斯与中东事务的策略空间",
        "全球南方国家的外交姿态变化",
        "停火谈判机制与执行瓶颈",
        "冲突传播中的信息战与舆论战",
        "能源市场预期与财政脆弱性",
        "地区金融、贸易与投资信心",
        "无人机、导弹与非对称作战趋势",
        "跨境武装网络与治理挑战",
        "联合国与多边机制的行动边界",
        "战后重建融资与制度安排",
        "教育、医疗与公共服务恢复路径",
        "难民与内部流离失所问题治理",
        "青年就业与社会稳定联动",
        "宗派、民族与地方认同政治",
        "城市基础设施修复与数字治理",
        "网络空间安全与关键设施防护",
    ]

    lines: list[str] = [
        f"# {subject} 学科知识总 Markdown（Mock）",
        "",
        "> 说明：该内容为接口联调测试用 mock 文本，不代表实时新闻结论。",
        "> 截止时间：2026-03-22。",
        "",
        "## 全局概览",
        "",
        "中东局势的核心特征是多层冲突叠加：地面军事冲突、代理人博弈、能源与航运安全竞争、以及重建与治理能力不足相互强化。"
        "在这一框架下，任何局部事件都可能通过市场预期、舆论传播和联盟承诺传导到更大范围，形成超出单一区域的连锁影响。",
        "",
    ]

    for i in range(1, 31):
        title = sections[(i - 1) % len(sections)]
        lines.append(f"## 专题{i}：{title}")
        lines.append("")
        lines.append(_MIDDLE_EAST_MOCK_SECTION)
        lines.append("")
        lines.append(
            "### 本节要点\n"
            "1. 冲突降温依赖政治谈判、执行监督与人道通道三者协同。\n"
            "2. 航运与能源的安全预期会反向影响地区各方的战略选择。\n"
            "3. 治理恢复速度决定了战后稳定的上限与社会风险的下限。"
        )
        lines.append("")

    markdown = "\n".join(lines).strip()
    if len(markdown) < 10000:
        pad_block = (
            "\n\n## 附录：延伸观察\n"
            "中东局势的长期变量包括人口结构变化、气候与水资源压力、城市化与数字化治理能力差异，以及"
            "外部大国对地区安全架构的再塑。上述变量在不同国家以不同节奏显现，但都会通过财政空间、社会预期"
            "与国家能力传导到安全议题。"
        )
        while len(markdown) < 10000:
            markdown += pad_block

    return markdown


@router.post(
    "/digest/build",
    response_model=ApiResponse[DigestBuildData],
    summary="触发增量构建",
    responses=build_error_responses([400, 404, 409, 500]),
)
async def digest_build(
    background_tasks: BackgroundTasks,
    subject: str = Path(...),
    body: DigestBuildRequest = Body(...),
    session: Session = Depends(get_db),
) -> ApiResponse[DigestBuildData]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized)
    data = trigger_digest_build(
        session,
        subject=normalized,
        file_ids=body.file_ids,
        idempotency_key=body.idempotency_key,
    )
    if not data.is_existing:
        background_tasks.add_task(
            run_graph_digest_background,
            subject=normalized,
            job_id=data.job_id,
        )
    return ok_response(data)


@router.post(
    "/digest/status",
    response_model=ApiResponse[DigestStatusResponse],
    summary="查询增量构建聚合状态",
    responses=build_error_responses([400, 404, 500]),
)
async def digest_status(
    subject: str = Path(...),
    body: DigestStatusRequest = Body(...),
    session: Session = Depends(get_db),
) -> ApiResponse[DigestStatusResponse]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized)
    return ok_response(
        get_digest_status(session, subject=normalized, job_id=body.job_id)
    )


@router.post(
    "/docgen/build",
    response_model=ApiResponse[DocGenBuildData],
    summary="触发知识文档生成",
    responses=build_error_responses([400, 404, 500]),
)
async def docgen_build(
    background_tasks: BackgroundTasks,
    subject: str = Path(...),
    body: DocGenBuildRequest = Body(...),
    session: Session = Depends(get_db),
) -> ApiResponse[DocGenBuildData]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized)
    data = trigger_docgen_build(
        session,
        subject=normalized,
        file_ids=body.file_ids,
        prompt=body.prompt,
    )
    background_tasks.add_task(
        run_docgen_background,
        subject=normalized,
        job_id=data.job_id,
    )
    return ok_response(data)


@router.post(
    "/docgen/get",
    response_model=ApiResponse[DocGenGetResponse],
    summary="查询知识文档最终内容与最近生成状态",
    responses=build_error_responses([400, 404, 500]),
)
async def docgen_get(
    background_tasks: BackgroundTasks,
    subject: str = Path(...),
    session: Session = Depends(get_db),
) -> ApiResponse[DocGenGetResponse]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized)
    data = ensure_docgen_started(session, subject=normalized)
    if data is not None:
        background_tasks.add_task(
            run_docgen_background,
            subject=normalized,
            job_id=data.job_id,
        )
    return ok_response(get_docgen_result(session, subject=normalized))

@router.post(
    "/graph/nodes/query",
    response_model=ApiResponse[PaginatedData[KnowledgeNodeResponse]],
    summary="分页查询知识节点",
    responses=build_error_responses([400, 404, 500]),
)
async def graph_nodes_query(
    subject: str = Path(...),
    body: GraphNodesQueryRequest = Body(default=GraphNodesQueryRequest()),
    session: Session = Depends(get_db),
) -> ApiResponse[PaginatedData[KnowledgeNodeResponse]]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized)
    return ok_response(
        get_graph_nodes(
            session,
            subject=normalized,
            node_type=body.node_type,
            page=body.page,
            size=body.size,
        )
    )


@router.post(
    "/graph/nodes/detail",
    response_model=ApiResponse[KnowledgeNodeDetailResponse],
    summary="知识节点详情",
    responses=build_error_responses([400, 404, 500]),
)
async def graph_node_detail(
    subject: str = Path(...),
    body: GraphNodeDetailRequest = Body(...),
    session: Session = Depends(get_db),
) -> ApiResponse[KnowledgeNodeDetailResponse]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized)
    return ok_response(
        get_graph_node_detail(session, subject=normalized, node_id=body.node_id)
    )


@router.post(
    "/graph/full",
    response_model=ApiResponse[FullGraphResponse],
    summary="获取完整知识图谱（节点+边）",
    responses=build_error_responses([400, 404, 500]),
)
async def graph_full(
    subject: str = Path(...),
    session: Session = Depends(get_db),
) -> ApiResponse[FullGraphResponse]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized)
    return ok_response(
        get_full_graph(session, subject=normalized)
    )


@router.post(
    "/graph/evidence/context",
    response_model=ApiResponse[EvidenceContextResponse],
    summary="获取证据原文上下文",
    responses=build_error_responses([400, 404, 500]),
)
async def evidence_context(
    subject: str = Path(...),
    body: EvidenceContextRequest = Body(...),
    session: Session = Depends(get_db),
) -> ApiResponse[EvidenceContextResponse]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized)
    return ok_response(
        get_evidence_context(session, subject=normalized, evidence_id=body.evidence_id)
    )


@router.post(
    "/chunks/context",
    response_model=ApiResponse[ChunkContextResponse],
    summary="获取聊天引用原文上下文",
    responses=build_error_responses([400, 404, 500]),
)
async def chunk_context(
    subject: str = Path(...),
    body: ChunkContextRequest = Body(...),
    session: Session = Depends(get_db),
) -> ApiResponse[ChunkContextResponse]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized)
    return ok_response(
        get_chunk_context(session, subject=normalized, chunk_id=body.chunk_id)
    )



# ── Phase 2: 教学单元路由 ──


@router.post(
    "/units/query",
    response_model=ApiResponse[PaginatedData[TeachingUnitResponse]],
    summary="分页查询教学单元",
    responses=build_error_responses([400, 404, 500]),
)
async def units_query(
    subject: str = Path(...),
    body: UnitsQueryRequest = Body(default=UnitsQueryRequest()),
    session: Session = Depends(get_db),
) -> ApiResponse[PaginatedData[TeachingUnitResponse]]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized)
    return ok_response(
        get_teaching_units(
            session,
            subject=normalized,
            status=body.status,
            page=body.page,
            size=body.size,
        )
    )


@router.post(
    "/units/detail",
    response_model=ApiResponse[TeachingUnitDetailResponse],
    summary="教学单元详情",
    responses=build_error_responses([400, 404, 500]),
)
async def unit_detail(
    subject: str = Path(...),
    body: UnitDetailRequest = Body(...),
    session: Session = Depends(get_db),
) -> ApiResponse[TeachingUnitDetailResponse]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized)
    return ok_response(
        get_teaching_unit_detail(session, subject=normalized, unit_id=body.unit_id)
    )



# ── Phase 3: 主题树路由 ──


@router.post(
    "/theme-tree/current",
    response_model=ApiResponse[ThemeTreeResponse],
    summary="当前主题树",
    responses=build_error_responses([400, 404, 500]),
)
async def theme_tree_current(
    subject: str = Path(...),
    session: Session = Depends(get_db),
) -> ApiResponse[ThemeTreeResponse]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized)
    return ok_response(
        get_current_theme_tree(session, subject=normalized)
    )


@router.post(
    "/taxonomy/anchors",
    response_model=ApiResponse[list[TaxonomyAnchorResponse]],
    summary="锚点管理",
    responses=build_error_responses([400, 404, 422, 500]),
)
async def taxonomy_anchors(
    subject: str = Path(...),
    body: AnchorManageRequest = Body(...),
    session: Session = Depends(get_db),
) -> ApiResponse[list[TaxonomyAnchorResponse]]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized)
    return ok_response(
        manage_taxonomy_anchors(
            session,
            subject=normalized,
            action=body.action,
            anchor_id=body.anchor_id,
            title=body.title,
            anchor_type=body.anchor_type,
            parent_anchor_id=body.parent_anchor_id,
            order_index=body.order_index,
        )
    )



# ── Phase 4: 先修 DAG 路由 ──


@router.post(
    "/prereq-dag/current",
    response_model=ApiResponse[PrereqDagResponse],
    summary="当前先修 DAG",
    responses=build_error_responses([400, 404, 500]),
)
async def prereq_dag_current(
    subject: str = Path(...),
    session: Session = Depends(get_db),
) -> ApiResponse[PrereqDagResponse]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized)
    return ok_response(
        get_current_prereq_dag(session, subject=normalized)
    )


@router.post(
    "/curriculum/current",
    response_model=ApiResponse[CurriculumSnapshotResponse],
    summary="当前课程快照",
    responses=build_error_responses([400, 404, 500]),
)
async def curriculum_current(
    subject: str = Path(...),
    session: Session = Depends(get_db),
) -> ApiResponse[CurriculumSnapshotResponse]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized)
    return ok_response(
        get_current_curriculum_snapshot(session, subject=normalized)
    )


# ── 清空知识数据 ──


@router.post(
    "/clear",
    response_model=ApiResponse[ClearKnowledgeResponse],
    summary="清空学科所有知识数据",
    responses=build_error_responses([400, 404, 500]),
)
async def knowledge_clear(
    subject: str = Path(...),
    session: Session = Depends(get_db),
) -> ApiResponse[ClearKnowledgeResponse]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized)
    counts = clear_subject_knowledge(session, subject=normalized)
    return ok_response(
        ClearKnowledgeResponse(subject=normalized, deleted_counts=counts)
    )
