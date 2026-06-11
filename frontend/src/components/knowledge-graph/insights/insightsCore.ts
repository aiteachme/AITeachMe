import type { FullGraphResponse, GraphEdgeResponse, KnowledgeUnitResponse } from "../../../api/generated/model";
import {
  DEFAULT_COLOR,
  NODE_COLORS,
  nodeBaseLayer,
  relationTone,
} from "../knowledgeGraphVisual";

export type HealthTone = "good" | "warn" | "bad" | "neutral";

export type LayerInsight = {
  index: number;
  label: string;
  description: string;
  color: string;
  count: number;
  percent: number;
  topTypes: Array<{ type: string; label: string; count: number; color: string }>;
};

export type RelationInsight = {
  type: string;
  label: string;
  color: string;
  count: number;
  percent: number;
  averageConfidence: number;
  purpose: string;
};

export type TypeInsight = {
  type: string;
  label: string;
  color: string;
  soft: string;
  dark: string;
  count: number;
  percent: number;
};

export type FlowInsight = {
  sourceLayer: number;
  targetLayer: number;
  count: number;
  relationTypes: Array<{ type: string; count: number; label: string; color: string }>;
};

export type TypePairFlow = {
  sourceType: string;
  targetType: string;
  count: number;
  relationType: string;
  relationLabel: string;
  color: string;
  relationCounts: Array<{ type: string; label: string; color: string; count: number }>;
};

export type NodeInsight = KnowledgeUnitResponse & {
  degree: number;
  inDegree: number;
  outDegree: number;
  layer: number;
  componentId: number;
  componentSize: number;
  methodReachable: boolean;
  practiceReachable: boolean;
  principleReachable: boolean;
  impactScore: number;
  issueScore: number;
  issueReasons: string[];
};

export type GraphIssue = {
  title: string;
  detail: string;
  tone: HealthTone;
  hint?: string;
};

export type ComponentInsight = {
  id: number;
  size: number;
  dominantType: string;
  dominantTypeLabel: string;
  dominantColor: string;
  nodeIds: number[];
  isMainline: boolean;
};

export type GraphInsightModel = {
  nodes: NodeInsight[];
  edges: GraphEdgeResponse[];
  layerItems: LayerInsight[];
  relationItems: RelationInsight[];
  typeItems: TypeInsight[];
  flowItems: FlowInsight[];
  typePairFlows: TypePairFlow[];
  matrix: number[][];
  matrixMax: number;
  issues: GraphIssue[];
  bottleneckNodes: NodeInsight[];
  gapNodes: NodeInsight[];
  isolatedNodes: NodeInsight[];
  components: ComponentInsight[];
  degreeDistribution: number[];
  degreeMax: number;
  nodeCount: number;
  edgeCount: number;
  avgDegree: number;
  densityPct: number;
  isolatedCount: number;
  componentCount: number;
  largestComponentCount: number;
  largestComponentPct: number;
  relationConfidenceAvg: number;
  lowConfidenceRelationCount: number;
  lowConfidenceRelationPct: number;
  practiceCoveragePct: number;
  methodCoveragePct: number;
  principleCoveragePct: number;
  loopCoveragePct: number;
  diagnosisScore: number;
  diagnosisTone: HealthTone;
};

export const LEARNING_LAYERS = [
  { label: "组织", description: "目标 / 框架 / 路径", color: "#6366f1" },
  { label: "知识", description: "概念 / 公式 / 事实", color: "#2563eb" },
  { label: "原理", description: "推理 / 机制 / 条件", color: "#0f766e" },
  { label: "方法", description: "步骤 / 技能 / 纠错", color: "#f59e0b" },
  { label: "应用", description: "案例 / 迁移 / 资源", color: "#f43f5e" },
] as const;

export const TYPE_LABELS: Record<string, string> = {
  topic: "主题模块",
  concept: "概念术语",
  principle: "原理性质",
  formula_model: "公式模型",
  procedure: "方法步骤",
  skill: "解题技能",
  misconception: "易错辨析",
  application_case: "应用案例",
  resource: "学习资源",
};

export const RELATION_LABELS: Record<string, string> = {
  part_of: "归属",
  prerequisite_for: "前置",
  derives_to: "推导",
  applies_to: "应用",
  uses_method: "用方法",
  assesses: "考察",
  explains: "解释",
  remediates: "补救",
  confuses_with: "易混",
  similar_to: "相似",
  extends_to: "拓展",
};

export const RELATION_PURPOSES: Record<string, string> = {
  part_of: "表达知识归属，决定课程结构是否清楚。",
  prerequisite_for: "决定先学什么，是学习路径的主干。",
  derives_to: "连接为什么成立，发现推导链是否完整。",
  applies_to: "连接概念与用法，判断能否迁移到例题。",
  uses_method: "连接任务与方法，帮助形成可执行步骤。",
  assesses: "连接技能与考点，决定能不能形成做题闭环。",
  explains: "补充直观解释和证据，降低理解门槛。",
  remediates: "连接易错点与补救路径，帮助定位薄弱处。",
  confuses_with: "帮助区分相似概念，防止混淆。",
  similar_to: "聚合同类知识，扩展复习入口。",
  extends_to: "指向迁移和综合应用。",
};

const ASSESSMENT_SOURCE_TYPES = new Set(["concept", "principle", "formula_model", "procedure", "skill", "misconception", "application_case"]);
const PATH_RELATIONS = new Set(["prerequisite_for", "part_of", "derives_to", "applies_to", "uses_method", "assesses"]);
const METHOD_RELATIONS = new Set(["part_of", "derives_to", "applies_to", "uses_method"]);
const PRACTICE_RELATIONS = new Set(["applies_to", "uses_method", "assesses", "part_of"]);

export function ratio(count: number, total: number): number {
  if (!total) return 0;
  return Math.max(0, Math.min(1, count / total));
}

export function percentText(value: number): string {
  return `${Math.round(Math.max(0, Math.min(1, value)) * 100)}%`;
}

export function scoreTone(value: number, warn = 0.62, good = 0.78): HealthTone {
  if (value >= good) return "good";
  if (value >= warn) return "warn";
  return "bad";
}

export function nodeStyle(type: string) {
  return NODE_COLORS[type] ?? DEFAULT_COLOR;
}

export function nodeTypeLabel(type: string): string {
  return TYPE_LABELS[type] ?? nodeStyle(type).label ?? type.replace(/_/g, " ");
}

export function relationLabel(type: string): string {
  return RELATION_LABELS[type] ?? type.replace(/_/g, " ");
}

export function buildInsightModel(payload: FullGraphResponse | null | undefined): GraphInsightModel {
  const rawNodes = payload?.nodes ?? [];
  const nodeById = new Map(rawNodes.map((node) => [node.id, node]));
  const edges = (payload?.edges ?? []).filter(
    (edge) => nodeById.has(edge.source_node_id) && nodeById.has(edge.target_node_id),
  );
  const degree = new Map<number, number>();
  const inDegree = new Map<number, number>();
  const outDegree = new Map<number, number>();
  const directedAdj = new Map<number, GraphEdgeResponse[]>();
  const undirectedAdj = new Map<number, Set<number>>();
  const typeCounts = new Map<string, number>();
  const layerCounts = new Map<number, number>();
  const typeCountsByLayer = new Map<number, Map<string, number>>();
  const relationCounts = new Map<string, { count: number; confidenceSum: number }>();
  const matrix = LEARNING_LAYERS.map(() => LEARNING_LAYERS.map(() => 0));
  const flowCounts = new Map<string, FlowInsight>();
  const pairCounts = new Map<string, { count: number; relationCounts: Map<string, number> }>();

  for (const node of rawNodes) {
    const type = String(node.knowledge_unit_type || "other");
    const layer = nodeBaseLayer(type);
    degree.set(node.id, 0);
    inDegree.set(node.id, 0);
    outDegree.set(node.id, 0);
    undirectedAdj.set(node.id, new Set());
    typeCounts.set(type, (typeCounts.get(type) ?? 0) + 1);
    layerCounts.set(layer, (layerCounts.get(layer) ?? 0) + 1);
    const typeLayerMap = typeCountsByLayer.get(layer) ?? new Map<string, number>();
    typeLayerMap.set(type, (typeLayerMap.get(type) ?? 0) + 1);
    typeCountsByLayer.set(layer, typeLayerMap);
  }

  for (const edge of edges) {
    const source = nodeById.get(edge.source_node_id);
    const target = nodeById.get(edge.target_node_id);
    if (!source || !target) continue;
    const sourceType = String(source.knowledge_unit_type || "other");
    const targetType = String(target.knowledge_unit_type || "other");
    const sourceLayer = nodeBaseLayer(sourceType);
    const targetLayer = nodeBaseLayer(targetType);
    const relationType = String(edge.edge_type || "related");
    const confidence = Math.max(0, Math.min(1, Number(edge.confidence || 0)));
    const relation = relationCounts.get(relationType) ?? { count: 0, confidenceSum: 0 };
    relationCounts.set(relationType, {
      count: relation.count + 1,
      confidenceSum: relation.confidenceSum + confidence,
    });
    matrix[sourceLayer][targetLayer] += 1;
    degree.set(edge.source_node_id, (degree.get(edge.source_node_id) ?? 0) + 1);
    degree.set(edge.target_node_id, (degree.get(edge.target_node_id) ?? 0) + 1);
    outDegree.set(edge.source_node_id, (outDegree.get(edge.source_node_id) ?? 0) + 1);
    inDegree.set(edge.target_node_id, (inDegree.get(edge.target_node_id) ?? 0) + 1);
    directedAdj.set(edge.source_node_id, [...(directedAdj.get(edge.source_node_id) ?? []), edge]);
    undirectedAdj.get(edge.source_node_id)?.add(edge.target_node_id);
    undirectedAdj.get(edge.target_node_id)?.add(edge.source_node_id);

    const flowKey = `${sourceLayer}:${targetLayer}`;
    const flow = flowCounts.get(flowKey) ?? {
      sourceLayer,
      targetLayer,
      count: 0,
      relationTypes: [],
    };
    const relationItem = flow.relationTypes.find((item) => item.type === relationType);
    if (relationItem) {
      relationItem.count += 1;
    } else {
      flow.relationTypes.push({
        type: relationType,
        count: 1,
        label: relationLabel(relationType),
        color: relationTone(relationType),
      });
    }
    flow.count += 1;
    flowCounts.set(flowKey, flow);

    const pairKey = `${sourceType}:${targetType}`;
    const pair = pairCounts.get(pairKey) ?? { count: 0, relationCounts: new Map<string, number>() };
    pair.count += 1;
    pair.relationCounts.set(relationType, (pair.relationCounts.get(relationType) ?? 0) + 1);
    pairCounts.set(pairKey, pair);
  }

  // Connected components via BFS on undirected adjacency.
  const componentByNode = new Map<number, number>();
  const componentSizes: number[] = [];
  const componentMembers: number[][] = [];
  for (const node of rawNodes) {
    if (componentByNode.has(node.id)) continue;
    const componentId = componentSizes.length;
    const queue = [node.id];
    componentByNode.set(node.id, componentId);
    const members: number[] = [];
    let size = 0;
    for (let index = 0; index < queue.length; index += 1) {
      const current = queue[index];
      members.push(current);
      size += 1;
      for (const next of undirectedAdj.get(current) ?? []) {
        if (componentByNode.has(next)) continue;
        componentByNode.set(next, componentId);
        queue.push(next);
      }
    }
    componentSizes.push(size);
    componentMembers.push(members);
  }

  const reachable = (
    startNodeId: number,
    predicate: (node: KnowledgeUnitResponse) => boolean,
    maxDepth: number,
    allowedRelations: Set<string>,
  ) => {
    const seen = new Set<number>([startNodeId]);
    const queue: Array<{ id: number; depth: number }> = [{ id: startNodeId, depth: 0 }];
    for (let index = 0; index < queue.length; index += 1) {
      const current = queue[index];
      if (current.depth >= maxDepth) continue;
      for (const edge of directedAdj.get(current.id) ?? []) {
        if (!allowedRelations.has(String(edge.edge_type || ""))) continue;
        const target = nodeById.get(edge.target_node_id);
        if (!target || seen.has(target.id)) continue;
        if (predicate(target)) return true;
        seen.add(target.id);
        queue.push({ id: target.id, depth: current.depth + 1 });
      }
    }
    return false;
  };

  const nodes: NodeInsight[] = rawNodes.map((node) => {
    const type = String(node.knowledge_unit_type || "other");
    const layer = nodeBaseLayer(type);
    const nodeDegree = degree.get(node.id) ?? 0;
    const nodeInDegree = inDegree.get(node.id) ?? 0;
    const nodeOutDegree = outDegree.get(node.id) ?? 0;
    const methodReachable =
      type === "procedure" ||
      reachable(node.id, (target) => target.knowledge_unit_type === "procedure", 2, METHOD_RELATIONS);
    const practiceReachable =
      type === "skill" ||
      reachable(node.id, (target) => target.knowledge_unit_type === "skill", 2, PRACTICE_RELATIONS);
    const principleReachable =
      type === "principle" ||
      reachable(node.id, (target) => target.knowledge_unit_type === "principle", 2, PATH_RELATIONS);
    const issueReasons: string[] = [];
    if (nodeDegree === 0) issueReasons.push("孤立");
    if (type === "concept" && !methodReachable) issueReasons.push("缺方法");
    if (ASSESSMENT_SOURCE_TYPES.has(type) && !practiceReachable) issueReasons.push("缺练习");
    if (Number(node.confidence || 0) < 0.72) issueReasons.push("低置信");
    const issueScore =
      (nodeDegree === 0 ? 5 : 0) +
      (type === "concept" && !methodReachable ? 2.2 : 0) +
      (ASSESSMENT_SOURCE_TYPES.has(type) && !practiceReachable ? 2.8 : 0) +
      (Number(node.confidence || 0) < 0.72 ? 1.2 : 0);
    const impactScore =
      nodeDegree * 1.35 +
      nodeOutDegree * 0.6 +
      nodeInDegree * 0.25 +
      (type === "concept" ? 2.2 : 0) +
      (type === "procedure" || type === "principle" ? 1.2 : 0) +
      Math.max(0, Math.min(1, Number(node.confidence || 0))) * 0.8;
    const componentId = componentByNode.get(node.id) ?? 0;
    return {
      ...node,
      degree: nodeDegree,
      inDegree: nodeInDegree,
      outDegree: nodeOutDegree,
      layer,
      componentId,
      componentSize: componentSizes[componentId] ?? 1,
      methodReachable,
      practiceReachable,
      principleReachable,
      impactScore,
      issueScore,
      issueReasons,
    };
  });

  const nodeCount = nodes.length;
  const edgeCount = edges.length;
  const largestComponentCount = Math.max(0, ...componentSizes);
  const largestComponentPct = ratio(largestComponentCount, nodeCount);
  const isolatedNodes = nodes.filter((node) => node.degree === 0);
  const isolatedCount = isolatedNodes.length;
  const relationConfidenceAvg = edgeCount
    ? edges.reduce((sum, edge) => sum + Math.max(0, Math.min(1, Number(edge.confidence || 0))), 0) / edgeCount
    : 0;
  const lowConfidenceRelationCount = edges.filter((edge) => Number(edge.confidence || 0) < 0.72).length;
  const lowConfidenceRelationPct = ratio(lowConfidenceRelationCount, edgeCount);
  const avgDegree = nodeCount ? (edgeCount * 2) / nodeCount : 0;
  const densityPct = nodeCount > 1 ? (edgeCount / (nodeCount * (nodeCount - 1))) * 100 : 0;

  const coreNodes = nodes.filter((node) => node.knowledge_unit_type === "concept");
  const assessmentSourceNodes = nodes.filter((node) => ASSESSMENT_SOURCE_TYPES.has(String(node.knowledge_unit_type || "")));
  const methodCoverageCount = coreNodes.filter((node) => node.methodReachable).length;
  const principleCoverageCount = coreNodes.filter((node) => node.principleReachable).length;
  const practiceCoverageCount = assessmentSourceNodes.filter((node) => node.practiceReachable).length;
  const loopCoverageCount = coreNodes.filter((node) => (node.methodReachable || node.principleReachable) && node.practiceReachable).length;
  const methodCoveragePct = ratio(methodCoverageCount, coreNodes.length);
  const principleCoveragePct = ratio(principleCoverageCount, coreNodes.length);
  const practiceCoveragePct = ratio(practiceCoverageCount, assessmentSourceNodes.length);
  const loopCoveragePct = ratio(loopCoverageCount, coreNodes.length);

  const typeItems: TypeInsight[] = Array.from(typeCounts.entries())
    .map(([type, count]) => {
      const style = nodeStyle(type);
      return {
        type,
        label: nodeTypeLabel(type),
        color: style.fill,
        soft: style.soft,
        dark: style.dark,
        count,
        percent: ratio(count, nodeCount),
      };
    })
    .sort((left, right) => right.count - left.count || left.label.localeCompare(right.label));

  const layerItems = LEARNING_LAYERS.map((layer, index) => {
    const count = layerCounts.get(index) ?? 0;
    const typeMap = typeCountsByLayer.get(index) ?? new Map<string, number>();
    const topTypes = Array.from(typeMap.entries())
      .map(([type, typeCount]) => ({
        type,
        label: nodeTypeLabel(type),
        count: typeCount,
        color: nodeStyle(type).fill,
      }))
      .sort((left, right) => right.count - left.count)
      .slice(0, 3);
    return {
      index,
      label: layer.label,
      description: layer.description,
      color: layer.color,
      count,
      percent: ratio(count, nodeCount),
      topTypes,
    };
  });

  const relationItems = Array.from(relationCounts.entries())
    .map(([type, item]) => ({
      type,
      label: relationLabel(type),
      color: relationTone(type),
      count: item.count,
      percent: ratio(item.count, edgeCount),
      averageConfidence: item.count ? item.confidenceSum / item.count : 0,
      purpose: RELATION_PURPOSES[type] ?? "补充知识点之间的语义关系。",
    }))
    .sort((left, right) => right.count - left.count || left.label.localeCompare(right.label));

  const flowItems = Array.from(flowCounts.values())
    .map((flow) => ({
      ...flow,
      relationTypes: flow.relationTypes.sort((left, right) => right.count - left.count).slice(0, 3),
    }))
    .sort((left, right) => right.count - left.count);

  const typePairFlows: TypePairFlow[] = Array.from(pairCounts.entries())
    .map(([key, item]) => {
      const [sourceType, targetType] = key.split(":");
      const ranked = Array.from(item.relationCounts.entries()).sort((left, right) => right[1] - left[1]);
      const [relationType] = ranked[0] ?? ["related", 0];
      return {
        sourceType,
        targetType,
        count: item.count,
        relationType,
        relationLabel: relationLabel(relationType),
        color: relationTone(relationType),
        relationCounts: ranked.map(([type, count]) => ({
          type,
          label: relationLabel(type),
          color: relationTone(type),
          count,
        })),
      };
    })
    .sort((left, right) => right.count - left.count);

  // Component summary: dominant type per component.
  const components: ComponentInsight[] = componentMembers.map((memberIds, componentId) => {
    const typeBuckets = new Map<string, number>();
    for (const memberId of memberIds) {
      const node = nodeById.get(memberId);
      if (!node) continue;
      const type = String(node.knowledge_unit_type || "other");
      typeBuckets.set(type, (typeBuckets.get(type) ?? 0) + 1);
    }
    const ranked = Array.from(typeBuckets.entries()).sort((left, right) => right[1] - left[1]);
    const dominantType = ranked[0]?.[0] ?? "other";
    return {
      id: componentId,
      size: componentSizes[componentId] ?? memberIds.length,
      dominantType,
      dominantTypeLabel: nodeTypeLabel(dominantType),
      dominantColor: nodeStyle(dominantType).fill,
      nodeIds: memberIds,
      isMainline: componentSizes[componentId] === largestComponentCount && componentSizes[componentId] > 1,
    };
  }).sort((left, right) => right.size - left.size);

  // Degree distribution histogram (buckets 0..max).
  const degreeMax = Math.max(0, ...nodes.map((node) => node.degree));
  const degreeDistribution = new Array(degreeMax + 1).fill(0);
  for (const node of nodes) {
    degreeDistribution[node.degree] = (degreeDistribution[node.degree] ?? 0) + 1;
  }

  const issues: GraphIssue[] = [];
  if (isolatedCount > 0) {
    issues.push({
      title: `${isolatedCount} 个知识点没有关系`,
      detail: "这些点无法参与学习路径、问答追溯或练习推荐。",
      tone: isolatedCount / Math.max(1, nodeCount) > 0.12 ? "bad" : "warn",
      hint: "在文档中补充连接到核心概念的句式或案例，或合并到相近主题。",
    });
  }
  if (largestComponentPct < 0.72 && nodeCount > 0) {
    issues.push({
      title: `图谱被拆成 ${componentSizes.length} 个知识岛`,
      detail: "主干不够集中，用户可能学到碎片但看不到整体路径。",
      tone: largestComponentPct < 0.55 ? "bad" : "warn",
      hint: "建议补充跨章节的前置 / 包含关系，把零散小岛接到主干上。",
    });
  }
  if (coreNodes.length > 0 && loopCoveragePct < 0.56) {
    issues.push({
      title: "核心知识闭环不足",
      detail: "部分核心点只有概念，没有连到方法或练习。",
      tone: loopCoveragePct < 0.35 ? "bad" : "warn",
      hint: "为这些核心点补充 1 个方法示范 + 1 道练习，让概念可被检验。",
    });
  }
  if (lowConfidenceRelationPct > 0.22) {
    issues.push({
      title: "低置信关系偏多",
      detail: "需要复核来源，避免把弱关系当成学习路径主干。",
      tone: lowConfidenceRelationPct > 0.36 ? "bad" : "warn",
      hint: "在节点详情面板回看证据原文，确认或删除弱关系。",
    });
  }
  if (!issues.length) {
    issues.push({
      title: "图谱结构可用",
      detail: "主干、方法和训练关系已经比较完整，可以继续叠加掌握度。",
      tone: "good",
    });
  }

  const bottleneckNodes = [...nodes]
    .filter((node) => node.degree > 0)
    .sort((left, right) => right.impactScore - left.impactScore || right.degree - left.degree || left.id - right.id)
    .slice(0, 10);
  const gapNodes = [...nodes]
    .filter((node) => node.issueScore > 0)
    .sort((left, right) => right.issueScore - left.issueScore || right.impactScore - left.impactScore || left.id - right.id)
    .slice(0, 10);
  const matrixMax = Math.max(1, ...matrix.flat());
  const diagnosisScore = Math.round(
    largestComponentPct * 30 +
    practiceCoveragePct * 24 +
    loopCoveragePct * 24 +
    relationConfidenceAvg * 14 +
    principleCoveragePct * 4 +
    (1 - ratio(isolatedCount, nodeCount)) * 4,
  );
  const diagnosisTone: HealthTone = diagnosisScore >= 78 ? "good" : diagnosisScore >= 58 ? "warn" : "bad";

  return {
    nodes,
    edges,
    layerItems,
    relationItems,
    typeItems,
    flowItems,
    typePairFlows,
    matrix,
    matrixMax,
    issues,
    bottleneckNodes,
    gapNodes,
    isolatedNodes,
    components,
    degreeDistribution,
    degreeMax,
    nodeCount,
    edgeCount,
    avgDegree,
    densityPct,
    isolatedCount,
    componentCount: componentSizes.length,
    largestComponentCount,
    largestComponentPct,
    relationConfidenceAvg,
    lowConfidenceRelationCount,
    lowConfidenceRelationPct,
    practiceCoveragePct,
    methodCoveragePct,
    principleCoveragePct,
    loopCoveragePct,
    diagnosisScore,
    diagnosisTone,
  };
}

export type SankeyNode = {
  layer: number;
  label: string;
  color: string;
  description: string;
  nodeCount: number;
  inflow: number;
  outflow: number;
  selfLoop: number;
  x: number;
  y: number;
  width: number;
  height: number;
};

export type SankeyLink = {
  sourceLayer: number;
  targetLayer: number;
  count: number;
  width: number;
  sourceY: number;
  targetY: number;
  color: string;
  dominantRelation: string;
  dominantRelationLabel: string;
  relationCounts: Array<{ type: string; label: string; color: string; count: number }>;
};

/** Build a precise Sankey-style layout for the 5 learning layers. */
export function buildSankeyLayout(
  model: GraphInsightModel,
  width: number,
  height: number,
  margin = { top: 36, right: 56, bottom: 60, left: 56, columnWidth: 22 },
): { nodes: SankeyNode[]; links: SankeyLink[] } {
  const innerWidth = width - margin.left - margin.right;
  const innerHeight = height - margin.top - margin.bottom;
  const layers = LEARNING_LAYERS;
  const layerCount = layers.length;
  const xStep = innerWidth / Math.max(1, layerCount - 1);

  const flowAggregate = new Map<string, FlowInsight>();
  for (const flow of model.flowItems) {
    const key = `${flow.sourceLayer}:${flow.targetLayer}`;
    flowAggregate.set(key, flow);
  }

  const sankeyLinks: SankeyLink[] = [];
  for (const flow of model.flowItems) {
    if (flow.sourceLayer === flow.targetLayer) continue;
    const dominant = flow.relationTypes[0];
    sankeyLinks.push({
      sourceLayer: flow.sourceLayer,
      targetLayer: flow.targetLayer,
      count: flow.count,
      width: 0,
      sourceY: 0,
      targetY: 0,
      color: dominant?.color ?? "#94a3b8",
      dominantRelation: dominant?.type ?? "related",
      dominantRelationLabel: dominant?.label ?? "关系",
      relationCounts: flow.relationTypes,
    });
  }

  const totalEdges = Math.max(1, model.edgeCount);
  const totalThickness = innerHeight * 0.62;
  const scale = totalThickness / totalEdges;

  const nodeStats = layers.map((layer, layerIndex) => {
    let inflow = 0;
    let outflow = 0;
    let selfLoop = 0;
    for (const link of sankeyLinks) {
      if (link.sourceLayer === layerIndex) outflow += link.count;
      if (link.targetLayer === layerIndex) inflow += link.count;
    }
    const self = flowAggregate.get(`${layerIndex}:${layerIndex}`);
    if (self) selfLoop = self.count;
    return { layer, layerIndex, inflow, outflow, selfLoop };
  });

  const sankeyNodes: SankeyNode[] = nodeStats.map((stat) => {
    const layerInfo = model.layerItems[stat.layerIndex];
    const flowThrough = Math.max(stat.inflow, stat.outflow, 1);
    const heightValue = Math.max(28, flowThrough * scale * 1.5);
    const color = stat.layer.color;
    const x = margin.left + stat.layerIndex * xStep - margin.columnWidth / 2;
    const y = margin.top + (innerHeight - heightValue) / 2;
    return {
      layer: stat.layerIndex,
      label: stat.layer.label,
      color,
      description: stat.layer.description,
      nodeCount: layerInfo?.count ?? 0,
      inflow: stat.inflow,
      outflow: stat.outflow,
      selfLoop: stat.selfLoop,
      x,
      y,
      width: margin.columnWidth,
      height: heightValue,
    };
  });

  // Distribute outgoing/incoming offsets along the node bar to avoid overlap.
  const outgoingPositions = new Map<number, number>();
  const incomingPositions = new Map<number, number>();
  for (const link of [...sankeyLinks].sort((left, right) => left.targetLayer - right.targetLayer)) {
    const sourceNode = sankeyNodes[link.sourceLayer];
    const targetNode = sankeyNodes[link.targetLayer];
    if (!sourceNode || !targetNode) continue;
    const linkHeight = Math.max(2, link.count * scale);
    const outgoingOffset = outgoingPositions.get(link.sourceLayer) ?? 0;
    const incomingOffset = incomingPositions.get(link.targetLayer) ?? 0;
    link.width = linkHeight;
    link.sourceY = sourceNode.y + outgoingOffset + linkHeight / 2;
    link.targetY = targetNode.y + incomingOffset + linkHeight / 2;
    outgoingPositions.set(link.sourceLayer, outgoingOffset + linkHeight);
    incomingPositions.set(link.targetLayer, incomingOffset + linkHeight);
  }

  return { nodes: sankeyNodes, links: sankeyLinks };
}

/** Squarified treemap for component visualization (simplified single-level). */
export type TreemapRect = {
  id: number;
  size: number;
  dominantType: string;
  dominantTypeLabel: string;
  color: string;
  isMainline: boolean;
  x: number;
  y: number;
  width: number;
  height: number;
};

export function buildTreemap(
  components: ComponentInsight[],
  totalNodes: number,
  width: number,
  height: number,
): TreemapRect[] {
  if (!components.length || !totalNodes) return [];
  const items = components.map((component) => ({ ...component, area: 0 }));
  const total = items.reduce((sum, item) => sum + item.size, 0) || totalNodes;
  const totalArea = width * height;
  for (const item of items) {
    item.area = (item.size / total) * totalArea;
  }

  const rects: TreemapRect[] = [];
  let remaining = items.slice();
  let x0 = 0;
  let y0 = 0;
  let w = width;
  let h = height;

  const layoutRow = (row: typeof remaining, side: "h" | "v", offsetX: number, offsetY: number, length: number) => {
    const rowSum = row.reduce((sum, item) => sum + item.area, 0);
    let cursor = 0;
    for (const item of row) {
      const fraction = rowSum > 0 ? item.area / rowSum : 1 / row.length;
      let rect: TreemapRect;
      if (side === "h") {
        const segment = length * fraction;
        rect = {
          id: item.id,
          size: item.size,
          dominantType: item.dominantType,
          dominantTypeLabel: item.dominantTypeLabel,
          color: item.dominantColor,
          isMainline: item.isMainline,
          x: offsetX + cursor,
          y: offsetY,
          width: segment,
          height: rowSum > 0 ? rowSum / length : 0,
        };
        cursor += segment;
      } else {
        const segment = length * fraction;
        rect = {
          id: item.id,
          size: item.size,
          dominantType: item.dominantType,
          dominantTypeLabel: item.dominantTypeLabel,
          color: item.dominantColor,
          isMainline: item.isMainline,
          x: offsetX,
          y: offsetY + cursor,
          width: rowSum > 0 ? rowSum / length : 0,
          height: segment,
        };
        cursor += segment;
      }
      rects.push(rect);
    }
  };

  while (remaining.length) {
    const shortSide = Math.min(w, h);
    const horizontal = w >= h;
    const length = horizontal ? h : w;
    let rowArea = 0;
    let row: typeof remaining = [];
    let bestWorst = Infinity;
    let i = 0;
    while (i < remaining.length) {
      const item = remaining[i];
      const candidate = [...row, item];
      const candidateArea = rowArea + item.area;
      const candidateRowLength = candidateArea / length;
      const worst = candidate.reduce((maxValue, current) => {
        const breadth = current.area / candidateRowLength;
        return Math.max(maxValue, Math.max(candidateRowLength / breadth, breadth / candidateRowLength));
      }, 0);
      if (worst > bestWorst && row.length > 0) break;
      row = candidate;
      rowArea = candidateArea;
      bestWorst = worst;
      i += 1;
      if (length === 0) break;
    }
    const rowLength = rowArea / Math.max(1, length);
    if (horizontal) {
      layoutRow(row, "v", x0, y0, length);
      x0 += rowLength;
      w -= rowLength;
    } else {
      layoutRow(row, "h", x0, y0, length);
      y0 += rowLength;
      h -= rowLength;
    }
    remaining = remaining.slice(row.length);
    if (shortSide <= 0.001) break;
  }

  return rects;
}
