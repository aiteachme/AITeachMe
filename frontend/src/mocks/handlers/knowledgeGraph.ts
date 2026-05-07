import { HttpResponse, http } from "msw";

const nowIso = new Date().toISOString();

const layerSeeds = [
  {
    type: "knowledge_organization",
    names: ["数据库学习路线", "SQL 模块划分", "事务学习目标", "索引优化路径", "性能排查框架", "权限治理框架"],
  },
  {
    type: "core_knowledge",
    names: ["查询执行顺序", "关系模型", "规范化", "连接", "子查询", "聚合", "窗口函数", "执行计划", "隔离级别", "死锁", "权限模型", "备份恢复"],
  },
  {
    type: "method_demo",
    names: ["SELECT 查询模板", "JOIN 分析步骤", "GROUP BY 使用流程", "执行计划分析", "慢查询定位", "索引优化", "分页优化", "锁等待排查"],
  },
  {
    type: "principle_reasoning",
    names: ["事务 ACID 机制", "两阶段锁协议", "索引命中原则", "查询重写依据", "代价估算模型", "并发一致性分析"],
  },
  {
    type: "explanation_support",
    names: ["NULL 比较陷阱", "隐式转换提醒", "LIKE 前缀提醒", "大事务风险", "过度索引提醒", "权限泄露风险"],
  },
  {
    type: "practice_assessment",
    names: ["查询改写练习", "索引设计练习", "事务隔离练习", "执行计划练习", "锁冲突诊断", "备份恢复自测"],
  },
  {
    type: "application_extension",
    names: ["订单查询案例", "用户统计案例", "库存扣减场景", "批量导入任务", "权限审计任务", "报表分页项目", "死锁复现案例", "备份演练任务"],
  },
];

const mockGraphNodes = layerSeeds.flatMap((group, groupIndex) =>
  group.names.map((name, index) => ({
    id: groupIndex * 100 + index + 1,
    course_id: "mock",
    knowledge_unit_type: group.type,
    canonical_name: name,
    status: "active",
    confidence: 0.72 + ((index + groupIndex) % 5) * 0.05,
    created_at: nowIso,
    updated_at: nowIso,
  })),
);

function nodeIdsByType(type: string) {
  return mockGraphNodes.filter((node) => node.knowledge_unit_type === type).map((node) => node.id);
}

function buildMockGraphEdges() {
  const edges: Array<{
    id: number;
    source_node_id: number;
    target_node_id: number;
    edge_type: string;
    weight: number;
    confidence: number;
  }> = [];
  let nextId = 1;
  const connect = (from: number[], to: number[], edgeType: string, stride = 1) => {
    from.forEach((source, index) => {
      const target = to[(index * stride) % to.length];
      edges.push({
        id: nextId++,
        source_node_id: source,
        target_node_id: target,
        edge_type: edgeType,
        weight: 1,
        confidence: 0.78 + (index % 4) * 0.04,
      });
    });
  };

  connect(nodeIdsByType("knowledge_organization"), nodeIdsByType("core_knowledge"), "contains");
  connect(nodeIdsByType("core_knowledge"), nodeIdsByType("method_demo"), "application");
  connect(nodeIdsByType("principle_reasoning"), nodeIdsByType("core_knowledge"), "reasoning", 2);
  connect(nodeIdsByType("core_knowledge"), nodeIdsByType("explanation_support"), "explanation");
  connect(nodeIdsByType("method_demo"), nodeIdsByType("practice_assessment"), "training", 2);
  connect(nodeIdsByType("method_demo"), nodeIdsByType("application_extension"), "application");
  connect(nodeIdsByType("explanation_support"), nodeIdsByType("method_demo"), "contrast");
  connect(nodeIdsByType("core_knowledge").slice(0, 6), nodeIdsByType("core_knowledge").slice(6), "similar");
  return edges;
}

const mockGraphEdges = buildMockGraphEdges();

function collectNeighborIds(centerId: number, limit: number) {
  const nodeIds = new Set<number>([centerId]);

  for (const edge of mockGraphEdges) {
    if (edge.source_node_id === centerId || edge.target_node_id === centerId) {
      nodeIds.add(edge.source_node_id);
      nodeIds.add(edge.target_node_id);
    }
    if (nodeIds.size >= limit) break;
  }

  return nodeIds;
}

function paginatedNodes(page: number, size: number, nodeType?: string | null) {
  const filtered = nodeType
    ? mockGraphNodes.filter((node) => node.knowledge_unit_type === nodeType)
    : mockGraphNodes;
  const safePage = Math.max(1, page);
  const safeSize = Math.max(1, Math.min(100, size));
  const total = filtered.length;
  const pages = Math.max(1, Math.ceil(total / safeSize));
  const start = (safePage - 1) * safeSize;

  return {
    items: filtered.slice(start, start + safeSize),
    page: safePage,
    size: safeSize,
    total,
    pages,
  };
}

function buildNodeDetail(nodeId: number) {
  const node = mockGraphNodes.find((item) => item.id === nodeId) ?? mockGraphNodes[0];
  const incidentEdges = mockGraphEdges
    .filter((edge) => edge.source_node_id === node.id || edge.target_node_id === node.id)
    .slice(0, 8)
    .map((edge) => {
      const isOutgoing = edge.source_node_id === node.id;
      const otherNodeId = isOutgoing ? edge.target_node_id : edge.source_node_id;
      const otherNode = mockGraphNodes.find((item) => item.id === otherNodeId);

      return {
        id: edge.id,
        edge_type: edge.edge_type,
        direction: isOutgoing ? "outgoing" : "incoming",
        other_node_id: otherNodeId,
        other_node_name: otherNode?.canonical_name ?? "关联知识点",
        other_node_type: otherNode?.knowledge_unit_type ?? "core_knowledge",
        confidence: edge.confidence,
      };
    });

  return {
    ...node,
    normalized_name: node.canonical_name.toLowerCase(),
    type_confidence: 0.86,
    type_source: "mock",
    aliases: [
      {
        id: node.id * 10 + 1,
        alias: node.canonical_name,
        language: "zh",
        source: "mock",
        confidence: node.confidence,
        is_primary: true,
      },
    ],
    current_revision: {
      title: node.canonical_name,
      summary: `${node.canonical_name} 是当前课程图谱中的一个关键知识点，适合作为练习、讲解和复习的锚点。`,
      body: `- 类型：${node.knowledge_unit_type}\n- 建议：先确认定义边界，再沿关联关系查看前置知识和应用场景。`,
    },
    evidence: [
      {
        id: node.id * 10 + 2,
        file_id: "mock-file",
        chunk_id: node.id,
        quote_text: `资料中多次围绕「${node.canonical_name}」展开说明。`,
        evidence_role: "primary",
        field_scope: "summary",
        confidence: 0.82,
      },
    ],
    source_refs: [
      {
        id: node.id * 10 + 3,
        entity_type: "knowledge_unit",
        entity_id: node.id,
        knowledge_document_id: 1,
        chapter_index: 1,
        chapter_title: "Mock 知识图谱示例",
        doc_version_no: 1,
        graph_revision_no: 1,
        source_kind: "document",
        anchor: `node-${node.id}`,
        source_file_ids: ["mock-file"],
        quote_text: node.canonical_name,
        confidence: 0.82,
        created_at: nowIso,
      },
    ],
    incident_edges: incidentEdges,
  };
}

export const knowledgeGraphHandlers = [
  http.post("/api/v1/courses/:course/knowledge/build/runtime", () => {
    return HttpResponse.json({
      code: 0,
      data: {
        graph: {
          lane: "graph",
          status: "completed",
          progress_pct: 100,
          finished_at: nowIso,
        },
      },
    });
  }),

  http.post("/api/v1/courses/:course/knowledge/graph/full", () => {
    return HttpResponse.json({
      code: 0,
      data: {
        nodes: mockGraphNodes,
        edges: mockGraphEdges,
      },
    });
  }),

  http.post("/api/v1/courses/:course/knowledge/graph/knowledge-units", async ({ request }) => {
    const body = (await request.json().catch(() => ({}))) as {
      page?: number;
      size?: number;
      knowledge_unit_type?: string | null;
    };

    return HttpResponse.json({
      code: 0,
      data: paginatedNodes(body.page ?? 1, body.size ?? 30, body.knowledge_unit_type ?? null),
    });
  }),

  http.post("/api/v1/courses/:course/knowledge/graph/knowledge-units/detail", async ({ request }) => {
    const body = (await request.json().catch(() => ({}))) as { knowledge_unit_id?: number };

    return HttpResponse.json({
      code: 0,
      data: buildNodeDetail(Number(body.knowledge_unit_id ?? mockGraphNodes[0].id)),
    });
  }),

  http.post("/api/v1/courses/:course/knowledge/graph/subgraph", async ({ request }) => {
    const body = (await request.json().catch(() => ({}))) as {
      center_knowledge_unit_id?: number | null;
      edge_type?: string | null;
      limit?: number;
    };
    const centerId = Number(body.center_knowledge_unit_id ?? mockGraphNodes[0].id);
    const limit = Math.max(1, Math.min(300, body.limit ?? 80));
    const neighborIds = collectNeighborIds(centerId, limit);
    const edgeType = body.edge_type ?? null;
    const edges = mockGraphEdges.filter((edge) => {
      const inSubgraph = neighborIds.has(edge.source_node_id) && neighborIds.has(edge.target_node_id);
      return inSubgraph && (!edgeType || edge.edge_type === edgeType);
    });

    return HttpResponse.json({
      code: 0,
      data: {
        nodes: mockGraphNodes.filter((node) => neighborIds.has(node.id)).slice(0, limit),
        edges,
        center_knowledge_unit_id: centerId,
      },
    });
  }),
];
