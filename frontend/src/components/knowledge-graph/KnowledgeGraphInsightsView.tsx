import { Fragment, useMemo, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  BarChart3,
  CheckCircle2,
  GitBranch,
  Loader2,
  Network,
  Route,
  Sparkles,
} from "lucide-react";

import { graphFullApiV1CoursesCourseIdKnowledgeGraphFullPost } from "../../api/generated/knowledge";
import type { FullGraphResponse, GraphEdgeResponse, KnowledgeUnitResponse } from "../../api/generated/model";
import { unwrapOrvalResponse } from "../../lib/unwrapOrvalResponse";
import {
  DEFAULT_COLOR,
  NODE_COLORS,
  nodeBaseLayer,
  relationTone,
  truncateGraphLabel,
} from "./knowledgeGraphVisual";

type InsightMode = "atlas" | "peer" | "flow" | "matrix";
type HealthTone = "good" | "warn" | "bad" | "neutral";

type LayerInsight = {
  index: number;
  label: string;
  description: string;
  color: string;
  count: number;
  percent: number;
  topTypes: Array<{ type: string; label: string; count: number; color: string }>;
};

type RelationInsight = {
  type: string;
  label: string;
  color: string;
  count: number;
  percent: number;
  averageConfidence: number;
  purpose: string;
};

type TypeInsight = {
  type: string;
  label: string;
  color: string;
  soft: string;
  count: number;
  percent: number;
};

type FlowInsight = {
  sourceLayer: number;
  targetLayer: number;
  count: number;
  relationTypes: Array<{ type: string; count: number; label: string; color: string }>;
};

type TypePairFlow = {
  sourceType: string;
  targetType: string;
  count: number;
  relationType: string;
  relationLabel: string;
  color: string;
};

type NodeInsight = KnowledgeUnitResponse & {
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

type GraphIssue = {
  title: string;
  detail: string;
  tone: HealthTone;
};

type GraphInsightModel = {
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

type Point = { x: number; y: number };

type AtlasNode = NodeInsight & {
  x: number;
  y: number;
  r: number;
  color: string;
  label: string;
  labelRank: number;
};

type AtlasCluster = {
  type: string;
  label: string;
  color: string;
  soft: string;
  x: number;
  y: number;
  rx: number;
  ry: number;
  count: number;
};

type PeerLayerInsight = {
  layer: number;
  label: string;
  color: string;
  nodeCount: number;
  edgeCount: number;
  density: number;
  relationCounts: Array<{ type: string; label: string; color: string; count: number }>;
};

type PeerPairInsight = {
  id: string;
  source: NodeInsight;
  target: NodeInsight;
  relationType: string;
  relationLabel: string;
  color: string;
  score: number;
};

const LEARNING_LAYERS = [
  { label: "组织", description: "目标 / 框架 / 路径", color: "#6366f1" },
  { label: "知识", description: "概念 / 规则 / 事实", color: "#2563eb" },
  { label: "原理", description: "推理 / 机制 / 条件", color: "#0f766e" },
  { label: "方法", description: "例题 / 步骤 / 操作", color: "#f59e0b" },
  { label: "训练", description: "练习 / 应用 / 拓展", color: "#f43f5e" },
];

const TYPE_LABELS: Record<string, string> = {
  core_knowledge: "核心知识",
  method_demo: "方法示范",
  explanation_support: "解释辅助",
  principle_reasoning: "原理推理",
  practice_assessment: "练习评估",
  knowledge_organization: "知识组织",
  application_extension: "应用拓展",
};

const RELATION_LABELS: Record<string, string> = {
  prerequisite: "前置",
  contains: "包含",
  reasoning: "推理",
  application: "应用",
  explanation: "说明",
  training: "训练",
  contrast: "对比",
  similar: "相似",
};

const RELATION_PURPOSES: Record<string, string> = {
  prerequisite: "决定先学什么，适合生成学习路径和补前置提醒。",
  contains: "表达模块与知识点归属，决定课程结构是否清楚。",
  reasoning: "连接为什么成立，适合发现推导链是否完整。",
  application: "连接概念与用法，适合判断能否迁移到例题。",
  explanation: "补充直观解释和易错点，适合降低理解门槛。",
  training: "连接练习与考点，决定能不能形成做题闭环。",
  contrast: "帮助区分相似概念，适合防止混淆。",
  similar: "聚合同类知识，适合扩展复习入口。",
};

const ASSESSMENT_SOURCE_TYPES = new Set(["core_knowledge", "method_demo", "principle_reasoning", "application_extension"]);
const PATH_RELATIONS = new Set(["prerequisite", "contains", "reasoning", "application", "training"]);
const METHOD_RELATIONS = new Set(["contains", "reasoning", "application"]);
const PRACTICE_RELATIONS = new Set(["application", "training", "contains"]);

const TYPE_ANCHORS: Record<string, Point> = {
  knowledge_organization: { x: 210, y: 245 },
  core_knowledge: { x: 500, y: 300 },
  principle_reasoning: { x: 540, y: 150 },
  method_demo: { x: 760, y: 370 },
  explanation_support: { x: 330, y: 480 },
  practice_assessment: { x: 890, y: 210 },
  application_extension: { x: 900, y: 505 },
};

function ratio(count: number, total: number): number {
  if (!total) return 0;
  return Math.max(0, Math.min(1, count / total));
}

function percentText(value: number): string {
  return `${Math.round(Math.max(0, Math.min(1, value)) * 100)}%`;
}

function scoreTone(value: number, warn = 0.62, good = 0.78): HealthTone {
  if (value >= good) return "good";
  if (value >= warn) return "warn";
  return "bad";
}

function toneClasses(tone: HealthTone): {
  bg: string;
  border: string;
  text: string;
  chip: string;
  bar: string;
} {
  if (tone === "good") {
    return {
      bg: "bg-emerald-50 dark:bg-emerald-500/10",
      border: "border-emerald-200 dark:border-emerald-500/30",
      text: "text-emerald-700 dark:text-emerald-300",
      chip: "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-200",
      bar: "bg-emerald-500",
    };
  }
  if (tone === "warn") {
    return {
      bg: "bg-amber-50 dark:bg-amber-500/10",
      border: "border-amber-200 dark:border-amber-500/30",
      text: "text-amber-700 dark:text-amber-300",
      chip: "bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-200",
      bar: "bg-amber-500",
    };
  }
  if (tone === "bad") {
    return {
      bg: "bg-rose-50 dark:bg-rose-500/10",
      border: "border-rose-200 dark:border-rose-500/30",
      text: "text-rose-700 dark:text-rose-300",
      chip: "bg-rose-100 text-rose-700 dark:bg-rose-500/15 dark:text-rose-200",
      bar: "bg-rose-500",
    };
  }
  return {
    bg: "bg-slate-50 dark:bg-slate-900/70",
    border: "border-slate-200 dark:border-slate-800",
    text: "text-slate-700 dark:text-slate-300",
    chip: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300",
    bar: "bg-slate-500",
  };
}

function nodeStyle(type: string) {
  return NODE_COLORS[type] ?? DEFAULT_COLOR;
}

function nodeTypeLabel(type: string): string {
  return TYPE_LABELS[type] ?? nodeStyle(type).label ?? type.replace(/_/g, " ");
}

function relationLabel(type: string): string {
  return RELATION_LABELS[type] ?? type.replace(/_/g, " ");
}

function hashNumber(seed: string | number): number {
  const text = String(seed);
  let hash = 2166136261;
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return Math.abs(hash >>> 0);
}

function polarPoint(cx: number, cy: number, radius: number, angle: number): Point {
  return {
    x: cx + Math.cos(angle) * radius,
    y: cy + Math.sin(angle) * radius,
  };
}

function curvedPath(source: Point, target: Point, seed: string | number, bendScale = 0.18): string {
  const dx = target.x - source.x;
  const dy = target.y - source.y;
  const distance = Math.max(1, Math.sqrt(dx * dx + dy * dy));
  const direction = hashNumber(seed) % 2 === 0 ? 1 : -1;
  const bend = Math.min(95, Math.max(22, distance * bendScale)) * direction;
  const nx = -dy / distance;
  const ny = dx / distance;
  const cx = (source.x + target.x) / 2 + nx * bend;
  const cy = (source.y + target.y) / 2 + ny * bend;
  return `M ${source.x.toFixed(1)} ${source.y.toFixed(1)} Q ${cx.toFixed(1)} ${cy.toFixed(1)} ${target.x.toFixed(1)} ${target.y.toFixed(1)}`;
}

function buildInsightModel(payload: FullGraphResponse | null | undefined): GraphInsightModel {
  const rawNodes = payload?.nodes ?? [];
  const nodeById = new Map(rawNodes.map((node) => [node.id, node]));
  const edges = (payload?.edges ?? []).filter((edge) => nodeById.has(edge.source_node_id) && nodeById.has(edge.target_node_id));
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

  const componentByNode = new Map<number, number>();
  const componentSizes: number[] = [];
  for (const node of rawNodes) {
    if (componentByNode.has(node.id)) continue;
    const componentId = componentSizes.length;
    const queue = [node.id];
    componentByNode.set(node.id, componentId);
    let size = 0;
    for (let index = 0; index < queue.length; index += 1) {
      const current = queue[index];
      size += 1;
      for (const next of undirectedAdj.get(current) ?? []) {
        if (componentByNode.has(next)) continue;
        componentByNode.set(next, componentId);
        queue.push(next);
      }
    }
    componentSizes.push(size);
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
      type === "method_demo" ||
      reachable(node.id, (target) => target.knowledge_unit_type === "method_demo", 2, METHOD_RELATIONS);
    const practiceReachable =
      type === "practice_assessment" ||
      reachable(node.id, (target) => target.knowledge_unit_type === "practice_assessment", 2, PRACTICE_RELATIONS);
    const principleReachable =
      type === "principle_reasoning" ||
      reachable(node.id, (target) => target.knowledge_unit_type === "principle_reasoning", 2, PATH_RELATIONS);
    const issueReasons: string[] = [];
    if (nodeDegree === 0) issueReasons.push("孤立");
    if (type === "core_knowledge" && !methodReachable) issueReasons.push("缺方法");
    if (ASSESSMENT_SOURCE_TYPES.has(type) && !practiceReachable) issueReasons.push("缺练习");
    if (Number(node.confidence || 0) < 0.72) issueReasons.push("低置信");
    const issueScore =
      (nodeDegree === 0 ? 5 : 0) +
      (type === "core_knowledge" && !methodReachable ? 2.2 : 0) +
      (ASSESSMENT_SOURCE_TYPES.has(type) && !practiceReachable ? 2.8 : 0) +
      (Number(node.confidence || 0) < 0.72 ? 1.2 : 0);
    const impactScore =
      nodeDegree * 1.35 +
      nodeOutDegree * 0.6 +
      nodeInDegree * 0.25 +
      (type === "core_knowledge" ? 2.2 : 0) +
      (type === "method_demo" || type === "principle_reasoning" ? 1.2 : 0) +
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

  const coreNodes = nodes.filter((node) => node.knowledge_unit_type === "core_knowledge");
  const assessmentSourceNodes = nodes.filter((node) => ASSESSMENT_SOURCE_TYPES.has(String(node.knowledge_unit_type || "")));
  const methodCoverageCount = coreNodes.filter((node) => node.methodReachable).length;
  const principleCoverageCount = coreNodes.filter((node) => node.principleReachable).length;
  const practiceCoverageCount = assessmentSourceNodes.filter((node) => node.practiceReachable).length;
  const loopCoverageCount = coreNodes.filter((node) => (node.methodReachable || node.principleReachable) && node.practiceReachable).length;
  const methodCoveragePct = ratio(methodCoverageCount, coreNodes.length);
  const principleCoveragePct = ratio(principleCoverageCount, coreNodes.length);
  const practiceCoveragePct = ratio(practiceCoverageCount, assessmentSourceNodes.length);
  const loopCoveragePct = ratio(loopCoverageCount, coreNodes.length);

  const typeItems = Array.from(typeCounts.entries())
    .map(([type, count]) => {
      const style = nodeStyle(type);
      return {
        type,
        label: nodeTypeLabel(type),
        color: style.fill,
        soft: style.soft,
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

  const typePairFlows = Array.from(pairCounts.entries())
    .map(([key, item]) => {
      const [sourceType, targetType] = key.split(":");
      const [relationType] = Array.from(item.relationCounts.entries()).sort((left, right) => right[1] - left[1])[0] ?? ["related", 0];
      return {
        sourceType,
        targetType,
        count: item.count,
        relationType,
        relationLabel: relationLabel(relationType),
        color: relationTone(relationType),
      };
    })
    .sort((left, right) => right.count - left.count)
    .slice(0, 48);

  const issues: GraphIssue[] = [];
  if (isolatedCount > 0) {
    issues.push({
      title: `${isolatedCount} 个知识点没有关系`,
      detail: "这些点无法参与学习路径、问答追溯或练习推荐。",
      tone: isolatedCount / Math.max(1, nodeCount) > 0.12 ? "bad" : "warn",
    });
  }
  if (largestComponentPct < 0.72 && nodeCount > 0) {
    issues.push({
      title: `图谱被拆成 ${componentSizes.length} 个知识岛`,
      detail: "主干不够集中，用户可能学到碎片但看不到整体路径。",
      tone: largestComponentPct < 0.55 ? "bad" : "warn",
    });
  }
  if (coreNodes.length > 0 && loopCoveragePct < 0.56) {
    issues.push({
      title: "核心知识闭环不足",
      detail: "部分核心点只有概念，没有连到方法或练习。",
      tone: loopCoveragePct < 0.35 ? "bad" : "warn",
    });
  }
  if (lowConfidenceRelationPct > 0.22) {
    issues.push({
      title: "低置信关系偏多",
      detail: "需要复核来源，避免把弱关系当成学习路径主干。",
      tone: lowConfidenceRelationPct > 0.36 ? "bad" : "warn",
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

function ChartPanel({
  title,
  meta,
  description,
  className = "",
  children,
}: {
  title: string;
  meta?: ReactNode;
  description?: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <section className={`overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-950 ${className}`}>
      <div className="flex items-start justify-between gap-3 border-b border-slate-100 px-4 py-3 dark:border-slate-800">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">{title}</p>
          {description ? <p className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">{description}</p> : null}
        </div>
        {meta ? <div className="shrink-0 text-xs font-medium tabular-nums text-slate-500 dark:text-slate-400">{meta}</div> : null}
      </div>
      {children}
    </section>
  );
}

function ProgressBar({ value, tone = "neutral", color }: { value: number; tone?: HealthTone; color?: string }) {
  return (
    <div className="h-2 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
      <div
        className={`h-full rounded-full ${color ? "" : toneClasses(tone).bar}`}
        style={{
          width: `${Math.round(Math.max(0.03, Math.min(1, value)) * 100)}%`,
          backgroundColor: color,
        }}
      />
    </div>
  );
}

function MetricPill({ label, value, tone = "neutral" }: { label: string; value: string; tone?: HealthTone }) {
  const classes = toneClasses(tone);
  return (
    <div className={`rounded-lg border px-3 py-2 ${classes.border} ${classes.bg}`}>
      <p className="text-[11px] font-medium text-slate-500 dark:text-slate-400">{label}</p>
      <p className="mt-1 text-lg font-semibold tabular-nums text-slate-950 dark:text-slate-50">{value}</p>
    </div>
  );
}

function buildAtlasLayout(model: GraphInsightModel): { clusters: AtlasCluster[]; nodes: AtlasNode[]; nodeById: Map<number, AtlasNode> } {
  const width = 1120;
  const height = 660;
  const sortedNodes = [...model.nodes].sort((left, right) => right.impactScore - left.impactScore || left.id - right.id);
  const rankByNode = new Map(sortedNodes.map((node, index) => [node.id, index + 1]));
  const nodesByType = new Map<string, NodeInsight[]>();
  for (const node of sortedNodes) {
    const type = String(node.knowledge_unit_type || "other");
    nodesByType.set(type, [...(nodesByType.get(type) ?? []), node]);
  }

  const clusters: AtlasCluster[] = model.typeItems.map((typeItem, index) => {
    const fallbackAngle = -Math.PI / 2 + (index / Math.max(1, model.typeItems.length)) * Math.PI * 2;
    const anchor = TYPE_ANCHORS[typeItem.type] ?? polarPoint(width / 2, height / 2, 250, fallbackAngle);
    const radius = 58 + Math.sqrt(typeItem.count) * 15;
    return {
      type: typeItem.type,
      label: typeItem.label,
      color: typeItem.color,
      soft: typeItem.soft,
      x: anchor.x,
      y: anchor.y,
      rx: radius * 1.12,
      ry: radius * 0.86,
      count: typeItem.count,
    };
  });
  const clusterByType = new Map(clusters.map((cluster) => [cluster.type, cluster]));
  const atlasNodes: AtlasNode[] = [];

  for (const [type, nodes] of nodesByType) {
    const cluster = clusterByType.get(type) ?? {
      type,
      label: nodeTypeLabel(type),
      color: nodeStyle(type).fill,
      soft: nodeStyle(type).soft,
      x: width / 2,
      y: height / 2,
      rx: 90,
      ry: 72,
      count: nodes.length,
    };
    nodes.forEach((node, index) => {
      const seed = hashNumber(`${node.id}:${node.canonical_name}`);
      const angle = (index * 2.399963229728653 + (seed % 37) * 0.017) % (Math.PI * 2);
      const ring = Math.sqrt((index + 0.45) / Math.max(1, nodes.length)) * Math.min(cluster.rx, cluster.ry) * 0.82;
      const jitterX = ((seed % 17) - 8) * 1.7;
      const jitterY = (((seed >> 4) % 17) - 8) * 1.45;
      const x = Math.max(42, Math.min(width - 42, cluster.x + Math.cos(angle) * ring * 1.1 + jitterX));
      const y = Math.max(42, Math.min(height - 42, cluster.y + Math.sin(angle) * ring * 0.92 + jitterY));
      const style = nodeStyle(String(node.knowledge_unit_type || ""));
      const roleBoost = String(node.knowledge_unit_type || "") === "core_knowledge" ? 1.8 : 0;
      const r = Math.min(19, 5.2 + Math.sqrt(Math.max(0, node.degree)) * 2.45 + roleBoost);
      atlasNodes.push({
        ...node,
        x,
        y,
        r,
        color: style.fill,
        label: truncateGraphLabel(node.canonical_name, node.degree >= 4 ? 13 : 10),
        labelRank: rankByNode.get(node.id) ?? 999,
      });
    });
  }

  return {
    clusters,
    nodes: atlasNodes,
    nodeById: new Map(atlasNodes.map((node) => [node.id, node])),
  };
}

function buildPeerInsights(model: GraphInsightModel): {
  layerItems: PeerLayerInsight[];
  relationItems: Array<{ type: string; label: string; color: string; count: number }>;
  topPairs: PeerPairInsight[];
  peerEdgeCount: number;
} {
  const nodeById = new Map(model.nodes.map((node) => [node.id, node]));
  const layerRelationCounts = new Map<number, Map<string, number>>();
  const relationCounts = new Map<string, number>();
  const pairs: PeerPairInsight[] = [];
  let peerEdgeCount = 0;

  for (const edge of model.edges) {
    const source = nodeById.get(edge.source_node_id);
    const target = nodeById.get(edge.target_node_id);
    if (!source || !target || source.layer !== target.layer) continue;
    const relationType = String(edge.edge_type || "related");
    const layerMap = layerRelationCounts.get(source.layer) ?? new Map<string, number>();
    layerMap.set(relationType, (layerMap.get(relationType) ?? 0) + 1);
    layerRelationCounts.set(source.layer, layerMap);
    relationCounts.set(relationType, (relationCounts.get(relationType) ?? 0) + 1);
    peerEdgeCount += 1;
    pairs.push({
      id: `${edge.id}`,
      source,
      target,
      relationType,
      relationLabel: relationLabel(relationType),
      color: relationTone(relationType),
      score: Number(edge.confidence || 0) * 2 + Number(edge.weight || 0) + Math.sqrt(source.degree + target.degree + 1),
    });
  }

  const layerItems = LEARNING_LAYERS.map((layer, index) => {
    const nodeCount = model.layerItems[index]?.count ?? 0;
    const edgeCount = Array.from((layerRelationCounts.get(index) ?? new Map()).values()).reduce((sum, count) => sum + count, 0);
    const possible = nodeCount > 1 ? (nodeCount * (nodeCount - 1)) / 2 : 0;
    return {
      layer: index,
      label: layer.label,
      color: layer.color,
      nodeCount,
      edgeCount,
      density: possible ? Math.min(1, edgeCount / possible) : 0,
      relationCounts: Array.from((layerRelationCounts.get(index) ?? new Map()).entries())
        .map(([type, count]) => ({
          type,
          label: relationLabel(type),
          color: relationTone(type),
          count,
        }))
        .sort((left, right) => right.count - left.count),
    };
  });

  const relationItems = Array.from(relationCounts.entries())
    .map(([type, count]) => ({
      type,
      label: relationLabel(type),
      color: relationTone(type),
      count,
    }))
    .sort((left, right) => right.count - left.count);

  return {
    layerItems,
    relationItems,
    topPairs: pairs.sort((left, right) => right.score - left.score).slice(0, 12),
    peerEdgeCount,
  };
}

function AtlasGraph({ model }: { model: GraphInsightModel }) {
  const layout = useMemo(() => buildAtlasLayout(model), [model]);
  const visibleEdges = useMemo(() => {
    const scored = model.edges
      .map((edge) => {
        const source = layout.nodeById.get(edge.source_node_id);
        const target = layout.nodeById.get(edge.target_node_id);
        if (!source || !target) return null;
        const score =
          Math.max(0, Number(edge.confidence || 0)) * 2 +
          Math.max(0, Number(edge.weight || 0)) +
          Math.sqrt(source.degree + target.degree + 1) * 0.28;
        return { edge, source, target, score };
      })
      .filter((item): item is { edge: GraphEdgeResponse; source: AtlasNode; target: AtlasNode; score: number } => Boolean(item))
      .sort((left, right) => right.score - left.score);
    return scored.slice(0, Math.min(scored.length, Math.max(80, Math.round(model.nodeCount * 1.9))));
  }, [layout.nodeById, model.edgeCount, model.edges, model.nodeCount]);

  const labeledNodes = layout.nodes
    .filter((node) => node.labelRank <= 18 || node.degree >= 5)
    .slice(0, 24);
  const dominantRelations = model.relationItems.slice(0, 6);

  return (
    <div className="grid gap-4">
      <ChartPanel
        title="图谱星云"
        meta={`${model.nodeCount} 节点 · ${model.edgeCount} 关系`}
        description="按知识类型聚成社区，节点越大代表连接越多，亮色标签是更适合作为讲解入口或复习锚点的知识点。"
        className="min-h-[720px]"
      >
        <div className="relative h-[720px] overflow-hidden bg-[#f6f8fb] dark:bg-slate-950">
          <svg viewBox="115 35 930 590" className="h-full w-full" role="img" aria-label="知识图谱星云可视化">
            <defs>
              <style>
                {`
                  @keyframes atm-kg-flow {
                    to { stroke-dashoffset: -56; }
                  }
                  @keyframes atm-kg-pulse {
                    0%, 100% { opacity: 0.16; transform: scale(1); }
                    50% { opacity: 0.34; transform: scale(1.18); }
                  }
                  @keyframes atm-kg-orbit {
                    to { stroke-dashoffset: -72; }
                  }
                  .atm-kg-flow {
                    stroke-dasharray: 9 13;
                    animation: atm-kg-flow 8s linear infinite;
                  }
                  .atm-kg-pulse {
                    transform-box: fill-box;
                    transform-origin: center;
                    animation: atm-kg-pulse 3.6s ease-in-out infinite;
                  }
                  .atm-kg-orbit {
                    animation: atm-kg-orbit 18s linear infinite;
                  }
                  @media (prefers-reduced-motion: reduce) {
                    .atm-kg-flow, .atm-kg-pulse, .atm-kg-orbit { animation: none; }
                  }
                `}
              </style>
              <pattern id="insight-grid" width="34" height="34" patternUnits="userSpaceOnUse">
                <circle cx="1" cy="1" r="0.8" fill="#93c5fd" opacity="0.28" />
              </pattern>
              <filter id="atlas-node-shadow" x="-60%" y="-60%" width="220%" height="220%">
                <feDropShadow dx="0" dy="6" stdDeviation="5" floodColor="#0f172a" floodOpacity="0.16" />
              </filter>
            </defs>
            <rect width="1120" height="660" fill="#f6f8fb" />
            <rect width="1120" height="660" fill="url(#insight-grid)" opacity="0.72" />
            <rect width="1120" height="660" fill="rgba(255,255,255,0.38)" />

            {layout.clusters.map((cluster) => (
              <g key={cluster.type}>
                <ellipse
                  cx={cluster.x}
                  cy={cluster.y}
                  rx={cluster.rx}
                  ry={cluster.ry}
                  fill={cluster.color}
                  opacity="0.09"
                />
                <ellipse
                  cx={cluster.x}
                  cy={cluster.y}
                  rx={cluster.rx}
                  ry={cluster.ry}
                  className="atm-kg-orbit"
                  fill="none"
                  stroke={cluster.color}
                  strokeWidth="1.4"
                  strokeOpacity="0.22"
                  strokeDasharray="8 10"
                />
                <text
                  x={cluster.x - cluster.rx + 14}
                  y={cluster.y - cluster.ry + 22}
                  fill="#334155"
                  fontSize="13"
                  fontWeight="700"
                >
                  {cluster.label}
                </text>
                <text
                  x={cluster.x - cluster.rx + 14}
                  y={cluster.y - cluster.ry + 40}
                  fill="#64748b"
                  fontSize="11"
                >
                  {cluster.count} 节点
                </text>
              </g>
            ))}

            <g>
              {visibleEdges.map(({ edge, source, target }) => (
                <path
                  key={edge.id}
                  className={edge.confidence >= 0.78 ? "atm-kg-flow" : undefined}
                  d={curvedPath(source, target, `${edge.id}:${edge.edge_type}`)}
                  fill="none"
                  stroke={relationTone(String(edge.edge_type || ""))}
                  strokeWidth={Math.min(3.8, 0.7 + Math.sqrt(Math.max(0.5, Number(edge.weight || 1))) * 1.05)}
                  strokeOpacity={edge.confidence >= 0.78 ? 0.28 : 0.14}
                  strokeLinecap="round"
                />
              ))}
            </g>

            <g>
              {layout.nodes.map((node) => (
                <g key={node.id} filter={node.degree >= 4 ? "url(#atlas-node-shadow)" : undefined}>
                  <circle className={node.degree >= 4 ? "atm-kg-pulse" : undefined} cx={node.x} cy={node.y} r={node.r + 5} fill={node.color} opacity={node.degree >= 4 ? 0.12 : 0.06} />
                  <circle cx={node.x} cy={node.y} r={node.r} fill={node.color} stroke="#ffffff" strokeWidth="2" />
                  {node.issueReasons.length ? (
                    <circle cx={node.x + node.r * 0.55} cy={node.y - node.r * 0.55} r="3.8" fill="#f59e0b" stroke="#fff" strokeWidth="1.2" />
                  ) : null}
                </g>
              ))}
            </g>

            <g>
              {labeledNodes.map((node) => (
                <g key={`label-${node.id}`}>
                  <rect
                    x={node.x + node.r + 6}
                    y={node.y - 11}
                    width={Math.max(42, node.label.length * 12 + 14)}
                    height="22"
                    rx="5"
                    fill="rgba(255,255,255,0.94)"
                    stroke={node.color}
                    strokeOpacity="0.22"
                  />
                  <text x={node.x + node.r + 13} y={node.y + 4} fill="#0f172a" fontSize="12" fontWeight="650">
                    {node.label}
                  </text>
                </g>
              ))}
            </g>
          </svg>
          <div className="pointer-events-none absolute right-4 top-4 w-[300px] rounded-lg border border-white/80 bg-white/88 p-3 shadow-lg shadow-slate-200/70 backdrop-blur dark:border-slate-700/80 dark:bg-slate-950/82 dark:shadow-black/30">
            <div className="grid grid-cols-2 gap-2">
              <MetricPill label="健康分" value={`${model.diagnosisScore}`} tone={model.diagnosisTone} />
              <MetricPill label="最大知识岛" value={percentText(model.largestComponentPct)} tone={scoreTone(model.largestComponentPct)} />
              <MetricPill label="练习闭环" value={percentText(model.loopCoveragePct)} tone={scoreTone(model.loopCoveragePct, 0.42, 0.68)} />
              <MetricPill label="平均连接" value={model.avgDegree.toFixed(1)} tone={model.avgDegree >= 2 ? "good" : model.avgDegree >= 1.2 ? "warn" : "bad"} />
            </div>
            <div className="mt-3 border-t border-slate-200 pt-3 dark:border-slate-800">
              <p className="mb-2 text-xs font-semibold text-slate-900 dark:text-slate-100">关系颜色</p>
              <div className="grid gap-1.5">
                {dominantRelations.map((item) => (
                  <div key={item.type} className="flex items-center justify-between gap-3 text-xs">
                    <span className="flex min-w-0 items-center gap-2 text-slate-600 dark:text-slate-300">
                      <span className="h-2 w-7 rounded-full" style={{ backgroundColor: item.color }} />
                      <span className="truncate">{item.label}</span>
                    </span>
                    <span className="font-semibold tabular-nums text-slate-500">{item.count}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
          <div className="pointer-events-none absolute bottom-4 left-4 max-w-[360px] rounded-lg border border-white/80 bg-white/88 p-3 shadow-lg shadow-slate-200/70 backdrop-blur dark:border-slate-700/80 dark:bg-slate-950/82 dark:shadow-black/30">
            <p className="text-xs font-semibold text-slate-900 dark:text-slate-100">当前最该看哪里</p>
            <div className="mt-2 grid gap-2">
              {model.issues.slice(0, 2).map((issue) => {
                const classes = toneClasses(issue.tone);
                return (
                  <div key={issue.title} className={`rounded-md border px-2 py-2 ${classes.border} ${classes.bg}`}>
                    <p className={`text-xs font-semibold ${classes.text}`}>{issue.title}</p>
                    <p className="mt-1 text-[11px] leading-4 text-slate-600 dark:text-slate-300">{issue.detail}</p>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </ChartPanel>

      <PeerMiniStrip model={model} />

      <div className="grid gap-4 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,0.75fr)_minmax(0,1fr)]">
        <ChartPanel title="图谱可读性" description="这些数值只解释旁边这张图，不抢主视觉。">
          <div className="grid gap-3 p-4">
            <MetricPill label="图谱健康分" value={`${model.diagnosisScore}`} tone={model.diagnosisTone} />
            <MetricPill label="最大知识岛" value={percentText(model.largestComponentPct)} tone={scoreTone(model.largestComponentPct)} />
            <MetricPill label="练习闭环" value={percentText(model.loopCoveragePct)} tone={scoreTone(model.loopCoveragePct, 0.42, 0.68)} />
            <MetricPill label="平均连接" value={model.avgDegree.toFixed(1)} tone={model.avgDegree >= 2 ? "good" : model.avgDegree >= 1.2 ? "warn" : "bad"} />
          </div>
        </ChartPanel>

        <ChartPanel title="关系颜色" description="不同颜色对应不同教学关系。">
          <div className="grid gap-2 p-4">
            {dominantRelations.map((item) => (
              <div key={item.type} className="flex items-center justify-between gap-3">
                <div className="flex min-w-0 items-center gap-2">
                  <span className="h-2.5 w-8 rounded-full" style={{ backgroundColor: item.color }} />
                  <span className="truncate text-xs font-medium text-slate-700 dark:text-slate-200">{item.label}</span>
                </div>
                <span className="text-xs font-semibold tabular-nums text-slate-500 dark:text-slate-400">{item.count}</span>
              </div>
            ))}
          </div>
        </ChartPanel>

        <IssueSummary model={model} />
      </div>
    </div>
  );
}

function PeerMiniStrip({ model }: { model: GraphInsightModel }) {
  const peer = useMemo(() => buildPeerInsights(model), [model]);
  const max = Math.max(1, ...peer.layerItems.map((item) => item.edgeCount));

  return (
    <ChartPanel
      title="同级结构速览"
      meta={`${peer.peerEdgeCount} 条同层关系`}
      description="同级关系能看出同一阶段的知识是否形成互相解释、对比和练习网络。"
    >
      <div className="grid gap-3 p-4 md:grid-cols-5">
        {peer.layerItems.map((item) => (
          <div key={item.layer} className="rounded-lg border border-slate-200 bg-slate-50 p-3 dark:border-slate-800 dark:bg-slate-900/60">
            <div className="flex items-center justify-between gap-2">
              <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">{item.label}</p>
              <span className="rounded-full px-2 py-0.5 text-xs font-semibold text-white" style={{ backgroundColor: item.color }}>
                {item.edgeCount}
              </span>
            </div>
            <div className="mt-3 h-2 overflow-hidden rounded-full bg-white dark:bg-slate-800">
              <div
                className="h-full rounded-full"
                style={{
                  width: `${Math.round((item.edgeCount / max) * 100)}%`,
                  backgroundColor: item.color,
                }}
              />
            </div>
            <p className="mt-2 text-[11px] text-slate-500 dark:text-slate-400">
              {item.nodeCount} 节点 · 密度 {percentText(item.density)}
            </p>
          </div>
        ))}
      </div>
    </ChartPanel>
  );
}

function IssueSummary({ model }: { model: GraphInsightModel }) {
  return (
    <ChartPanel title="当前最该看哪里">
      <div className="grid gap-2 p-4">
        {model.issues.slice(0, 3).map((issue) => {
          const classes = toneClasses(issue.tone);
          const Icon = issue.tone === "good" ? CheckCircle2 : AlertTriangle;
          return (
            <div key={issue.title} className={`rounded-lg border px-3 py-3 ${classes.border} ${classes.bg}`}>
              <div className="flex items-start gap-2">
                <Icon className={`mt-0.5 h-4 w-4 shrink-0 ${classes.text}`} />
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">{issue.title}</p>
                  <p className="mt-1 text-xs leading-5 text-slate-600 dark:text-slate-300">{issue.detail}</p>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </ChartPanel>
  );
}

function LayerFlowMap({ model }: { model: GraphInsightModel }) {
  const width = 1120;
  const height = 500;
  const top = 82;
  const bottom = 390;
  const maxLayerCount = Math.max(1, ...model.layerItems.map((item) => item.count));
  const maxFlow = Math.max(1, ...model.flowItems.map((item) => item.count));
  const layerX = (index: number) => 90 + index * ((width - 180) / (LEARNING_LAYERS.length - 1));
  const layerY = (index: number) => top + index * ((bottom - top) / (LEARNING_LAYERS.length - 1));
  const visibleFlows = model.flowItems.slice(0, 24);

  return (
    <ChartPanel
      title="学习路径流"
      meta={`${visibleFlows.length} 条主要流向`}
      description="看知识是否从组织、概念、原理，流到方法和训练。粗线代表这条教学路径更密集。"
      className="min-h-[520px]"
    >
      <div className="h-[520px] bg-slate-50 dark:bg-slate-950">
        <svg viewBox={`0 0 ${width} ${height}`} className="h-full w-full" role="img" aria-label="学习路径流可视化">
          <rect width={width} height={height} fill="#f8fafc" />
          {LEARNING_LAYERS.map((layer, index) => (
            <line
              key={`guide-${layer.label}`}
              x1={layerX(index)}
              x2={layerX(index)}
              y1="54"
              y2="430"
              stroke="#cbd5e1"
              strokeWidth="1"
              strokeDasharray="5 10"
              opacity="0.6"
            />
          ))}
          <g>
            {visibleFlows.map((flow, index) => {
              const sx = layerX(flow.sourceLayer);
              const tx = layerX(flow.targetLayer);
              const sameLayer = flow.sourceLayer === flow.targetLayer;
              const offset = ((index % 7) - 3) * 10;
              const sy = layerY(flow.sourceLayer) + offset;
              const ty = layerY(flow.targetLayer) - offset;
              const strokeWidth = Math.max(3, Math.min(20, 2 + Math.sqrt(flow.count / maxFlow) * 18));
              const sourceColor = LEARNING_LAYERS[flow.sourceLayer]?.color ?? "#64748b";
              const d = sameLayer
                ? `M ${sx - 24} ${sy} C ${sx - 90} ${sy - 58} ${sx + 90} ${sy - 58} ${sx + 24} ${sy}`
                : `M ${sx} ${sy} C ${(sx + tx) / 2} ${sy} ${(sx + tx) / 2} ${ty} ${tx} ${ty}`;
              return (
                <path
                  key={`${flow.sourceLayer}-${flow.targetLayer}-${index}`}
                  d={d}
                  fill="none"
                  stroke={sourceColor}
                  strokeWidth={strokeWidth}
                  strokeOpacity={0.16 + Math.min(0.34, flow.count / maxFlow)}
                  strokeLinecap="round"
                />
              );
            })}
          </g>
          <g>
            {model.layerItems.map((layer) => {
              const x = layerX(layer.index);
              const barHeight = 60 + (layer.count / maxLayerCount) * 150;
              const y = layerY(layer.index) - barHeight / 2;
              return (
                <g key={layer.index}>
                  <rect
                    x={x - 34}
                    y={y}
                    width="68"
                    height={barHeight}
                    rx="28"
                    fill={layer.color}
                    opacity="0.96"
                  />
                  <circle cx={x} cy={layerY(layer.index)} r="24" fill="#ffffff" opacity="0.95" />
                  <text x={x} y={layerY(layer.index) + 5} textAnchor="middle" fill={layer.color} fontSize="16" fontWeight="800">
                    {layer.count}
                  </text>
                  <text x={x} y="460" textAnchor="middle" fill="#0f172a" fontSize="14" fontWeight="750">
                    {layer.label}
                  </text>
                  <text x={x} y="480" textAnchor="middle" fill="#64748b" fontSize="11">
                    {layer.description}
                  </text>
                </g>
              );
            })}
          </g>
        </svg>
      </div>
    </ChartPanel>
  );
}

function RelationChordMap({ model }: { model: GraphInsightModel }) {
  const width = 620;
  const height = 430;
  const cx = width / 2;
  const cy = height / 2 + 8;
  const radius = 160;
  const types = model.typeItems.slice(0, 8);
  const angleByType = new Map<string, number>();
  types.forEach((item, index) => {
    angleByType.set(item.type, -Math.PI / 2 + (index / Math.max(1, types.length)) * Math.PI * 2);
  });
  const maxPair = Math.max(1, ...model.typePairFlows.map((flow) => flow.count));

  return (
    <ChartPanel
      title="知识类型关系弦图"
      meta={`${model.typePairFlows.length} 类连接`}
      description="不是看数量堆砌，而是看哪些类型之间真的发生了教学联系。"
    >
      <div className="h-[430px] bg-slate-50 dark:bg-slate-950">
        <svg viewBox={`0 0 ${width} ${height}`} className="h-full w-full" role="img" aria-label="知识类型关系弦图">
          <rect width={width} height={height} fill="#f8fafc" />
          <circle cx={cx} cy={cy} r={radius} fill="none" stroke="#e2e8f0" strokeWidth="1" strokeDasharray="5 9" />
          <g>
            {model.typePairFlows
              .filter((flow) => angleByType.has(flow.sourceType) && angleByType.has(flow.targetType))
              .slice(0, 42)
              .map((flow, index) => {
                const sourceAngle = angleByType.get(flow.sourceType) ?? 0;
                const targetAngle = angleByType.get(flow.targetType) ?? 0;
                const source = polarPoint(cx, cy, radius, sourceAngle);
                const target = polarPoint(cx, cy, radius, targetAngle);
                const widthValue = 1 + Math.sqrt(flow.count / maxPair) * 9;
                return (
                  <path
                    key={`${flow.sourceType}-${flow.targetType}-${index}`}
                    d={`M ${source.x.toFixed(1)} ${source.y.toFixed(1)} Q ${cx.toFixed(1)} ${cy.toFixed(1)} ${target.x.toFixed(1)} ${target.y.toFixed(1)}`}
                    fill="none"
                    stroke={flow.color}
                    strokeWidth={widthValue}
                    strokeOpacity={0.16 + Math.min(0.36, flow.count / maxPair)}
                    strokeLinecap="round"
                  />
                );
              })}
          </g>
          <circle cx={cx} cy={cy} r="56" fill="#0f172a" />
          <text x={cx} y={cy - 4} textAnchor="middle" fill="#ffffff" fontSize="22" fontWeight="800">
            {model.edgeCount}
          </text>
          <text x={cx} y={cy + 18} textAnchor="middle" fill="#cbd5e1" fontSize="12">
            总关系
          </text>
          <g>
            {types.map((item) => {
              const angle = angleByType.get(item.type) ?? 0;
              const point = polarPoint(cx, cy, radius, angle);
              const labelPoint = polarPoint(cx, cy, radius + 44, angle);
              return (
                <g key={item.type}>
                  <circle cx={point.x} cy={point.y} r={12 + Math.sqrt(item.count) * 2.4} fill={item.color} stroke="#fff" strokeWidth="3" />
                  <text
                    x={labelPoint.x}
                    y={labelPoint.y}
                    textAnchor={labelPoint.x > cx + 10 ? "start" : labelPoint.x < cx - 10 ? "end" : "middle"}
                    fill="#334155"
                    fontSize="12"
                    fontWeight="700"
                  >
                    {item.label}
                  </text>
                </g>
              );
            })}
          </g>
        </svg>
      </div>
    </ChartPanel>
  );
}

function RelationBars({ model }: { model: GraphInsightModel }) {
  const max = Math.max(1, ...model.relationItems.map((item) => item.count));
  return (
    <ChartPanel title="关系分布" description="看当前图谱主要靠哪些关系搭起来，避免只有包含关系、缺少推理和训练。">
      <div className="grid gap-3 p-4">
        {model.relationItems.map((item) => (
          <div key={item.type}>
            <div className="mb-1.5 flex items-center justify-between gap-3">
              <div className="flex min-w-0 items-center gap-2">
                <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: item.color }} />
                <span className="truncate text-xs font-semibold text-slate-700 dark:text-slate-200">{item.label}</span>
              </div>
              <span className="text-xs font-semibold tabular-nums text-slate-500 dark:text-slate-400">
                {item.count} · 置信 {percentText(item.averageConfidence)}
              </span>
            </div>
            <ProgressBar value={item.count / max} color={item.color} />
            <p className="mt-1 text-[11px] leading-4 text-slate-500 dark:text-slate-400">{item.purpose}</p>
          </div>
        ))}
      </div>
    </ChartPanel>
  );
}

function MatrixHeatmap({ model }: { model: GraphInsightModel }) {
  return (
    <ChartPanel
      title="层级关系矩阵"
      meta={`峰值 ${model.matrixMax}`}
      description="横向是流向哪里，纵向是从哪里出发。颜色越深，代表这条教学连接越密。"
    >
      <div className="overflow-x-auto p-4">
        <div
          className="grid min-w-[660px] gap-1.5"
          style={{ gridTemplateColumns: `100px repeat(${LEARNING_LAYERS.length}, minmax(86px, 1fr))` }}
        >
          <div />
          {LEARNING_LAYERS.map((layer) => (
            <div key={`head-${layer.label}`} className="px-2 py-1 text-center text-[11px] font-semibold text-slate-500 dark:text-slate-400">
              到 {layer.label}
            </div>
          ))}
          {model.layerItems.map((row) => (
            <Fragment key={`row-${row.index}`}>
              <div className="flex items-center px-2 text-[11px] font-semibold text-slate-500 dark:text-slate-400">
                从 {row.label}
              </div>
              {model.layerItems.map((column) => {
                const count = model.matrix[row.index][column.index] ?? 0;
                const intensity = count / model.matrixMax;
                return (
                  <div
                    key={`${row.index}:${column.index}`}
                    className="flex h-16 items-center justify-center rounded-lg border border-slate-200 text-sm font-semibold tabular-nums dark:border-slate-800"
                    style={{
                      backgroundColor: count ? `rgba(37, 99, 235, ${0.1 + intensity * 0.58})` : "rgba(248, 250, 252, 0.78)",
                      color: count && intensity > 0.55 ? "#ffffff" : "#334155",
                    }}
                    title={`${row.label} -> ${column.label}: ${count}`}
                  >
                    {count || ""}
                  </div>
                );
              })}
            </Fragment>
          ))}
        </div>
      </div>
    </ChartPanel>
  );
}

function TypeBubbleBoard({ model }: { model: GraphInsightModel }) {
  return (
    <ChartPanel title="知识类型社区" meta={`${model.typeItems.length} 类`} description="圆越大，说明该类知识在图谱里占比越高。">
      <div className="grid gap-3 p-4 sm:grid-cols-2 xl:grid-cols-3">
        {model.typeItems.map((item) => (
          <div key={item.type} className="flex items-center gap-3 rounded-lg border border-slate-200 bg-slate-50 px-3 py-3 dark:border-slate-800 dark:bg-slate-900/60">
            <span
              className="flex shrink-0 items-center justify-center rounded-full text-xs font-semibold text-white"
              style={{
                width: 38 + Math.sqrt(item.count) * 7,
                height: 38 + Math.sqrt(item.count) * 7,
                backgroundColor: item.color,
              }}
            >
              {item.count}
            </span>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-semibold text-slate-900 dark:text-slate-100">{item.label}</p>
              <ProgressBar value={item.percent} color={item.color} />
              <p className="mt-1 text-[11px] text-slate-500 dark:text-slate-400">{percentText(item.percent)} 节点</p>
            </div>
          </div>
        ))}
      </div>
    </ChartPanel>
  );
}

function NodeRankPanel({ title, nodes, emptyText }: { title: string; nodes: NodeInsight[]; emptyText: string }) {
  return (
    <ChartPanel title={title}>
      <div className="grid gap-2 p-4">
        {nodes.length ? (
          nodes.map((node, index) => {
            const style = nodeStyle(String(node.knowledge_unit_type || ""));
            return (
              <div key={node.id} className="flex items-center gap-3 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2.5 dark:border-slate-800 dark:bg-slate-900/60">
                <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-white text-xs font-semibold tabular-nums text-slate-500 ring-1 ring-slate-200 dark:bg-slate-950 dark:text-slate-400 dark:ring-slate-800">
                  {index + 1}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-semibold text-slate-900 dark:text-slate-100">{truncateGraphLabel(node.canonical_name, 26)}</p>
                  <div className="mt-1 flex flex-wrap items-center gap-1.5">
                    <span className="rounded-full px-2 py-0.5 text-[11px] font-medium" style={{ backgroundColor: style.soft, color: style.dark }}>
                      {nodeTypeLabel(String(node.knowledge_unit_type || ""))}
                    </span>
                    <span className="rounded-full bg-white px-2 py-0.5 text-[11px] text-slate-500 ring-1 ring-slate-200 dark:bg-slate-950 dark:text-slate-400 dark:ring-slate-800">
                      连接 {node.degree}
                    </span>
                    {node.issueReasons.slice(0, 2).map((reason) => (
                      <span key={reason} className="rounded-full bg-amber-50 px-2 py-0.5 text-[11px] text-amber-700 ring-1 ring-amber-100 dark:bg-amber-500/10 dark:text-amber-300 dark:ring-amber-500/20">
                        {reason}
                      </span>
                    ))}
                  </div>
                </div>
              </div>
            );
          })
        ) : (
          <div className="rounded-lg border border-dashed border-slate-200 bg-slate-50 px-4 py-8 text-center text-sm text-slate-500 dark:border-slate-800 dark:bg-slate-900/60 dark:text-slate-400">
            {emptyText}
          </div>
        )}
      </div>
    </ChartPanel>
  );
}

function PeerOrbitMap({ model }: { model: GraphInsightModel }) {
  const peer = useMemo(() => buildPeerInsights(model), [model]);
  const width = 1120;
  const height = 500;
  const maxEdge = Math.max(1, ...peer.layerItems.map((item) => item.edgeCount));
  const maxNode = Math.max(1, ...peer.layerItems.map((item) => item.nodeCount));
  const centers = peer.layerItems.map((item, index) => ({
    ...item,
    x: 130 + index * 215,
    y: 245,
    r: 46 + (item.nodeCount / maxNode) * 54,
  }));

  return (
    <ChartPanel
      title="同级知识轨道"
      meta={`${peer.peerEdgeCount} 条同级关系`}
      description="每个圆是一层学习阶段，圆越大节点越多，轨道越亮表示同一层内部的解释、对比、训练越密。"
      className="min-h-[520px]"
    >
      <div className="h-[520px] bg-[#f6f8fb] dark:bg-slate-950">
        <svg viewBox={`0 0 ${width} ${height}`} className="h-full w-full" role="img" aria-label="同级知识轨道图">
          <defs>
            <style>
              {`
                @keyframes atm-peer-dash { to { stroke-dashoffset: -68; } }
                @keyframes atm-peer-float {
                  0%, 100% { transform: translateY(0); }
                  50% { transform: translateY(-5px); }
                }
                .atm-peer-orbit { animation: atm-peer-dash 12s linear infinite; }
                .atm-peer-node { transform-box: fill-box; transform-origin: center; animation: atm-peer-float 4.8s ease-in-out infinite; }
                @media (prefers-reduced-motion: reduce) {
                  .atm-peer-orbit, .atm-peer-node { animation: none; }
                }
              `}
            </style>
          </defs>
          <rect width={width} height={height} fill="#f8fafc" />
          <g>
            {centers.map((item, layerIndex) => {
              const edgeRatio = item.edgeCount / maxEdge;
              const relationDots = item.relationCounts.slice(0, 7);
              return (
                <g key={item.layer}>
                  <circle
                    cx={item.x}
                    cy={item.y}
                    r={item.r + 24}
                    fill={item.color}
                    opacity={0.06 + edgeRatio * 0.08}
                  />
                  <circle
                    className="atm-peer-orbit"
                    cx={item.x}
                    cy={item.y}
                    r={item.r}
                    fill="none"
                    stroke={item.color}
                    strokeWidth={2 + edgeRatio * 8}
                    strokeOpacity={0.22 + edgeRatio * 0.36}
                    strokeDasharray="12 14"
                  />
                  {relationDots.map((relation, relationIndex) => {
                    const angle = -Math.PI / 2 + (relationIndex / Math.max(1, relationDots.length)) * Math.PI * 2 + layerIndex * 0.18;
                    const point = polarPoint(item.x, item.y, item.r, angle);
                    return (
                      <g key={`${item.layer}-${relation.type}`} className="atm-peer-node">
                        <circle cx={point.x} cy={point.y} r={7 + Math.sqrt(relation.count) * 1.4} fill={relation.color} stroke="#fff" strokeWidth="2" />
                        {relation.count >= 3 ? (
                          <text x={point.x} y={point.y + 3.5} textAnchor="middle" fill="#fff" fontSize="9" fontWeight="800">
                            {relation.count}
                          </text>
                        ) : null}
                      </g>
                    );
                  })}
                  <circle cx={item.x} cy={item.y} r="34" fill="#ffffff" stroke={item.color} strokeWidth="2" />
                  <text x={item.x} y={item.y - 3} textAnchor="middle" fill="#0f172a" fontSize="17" fontWeight="800">
                    {item.edgeCount}
                  </text>
                  <text x={item.x} y={item.y + 17} textAnchor="middle" fill="#64748b" fontSize="11">
                    同级关系
                  </text>
                  <text x={item.x} y="432" textAnchor="middle" fill="#0f172a" fontSize="15" fontWeight="800">
                    {item.label}
                  </text>
                  <text x={item.x} y="454" textAnchor="middle" fill="#64748b" fontSize="12">
                    {item.nodeCount} 节点 · {percentText(item.density)}
                  </text>
                </g>
              );
            })}
          </g>
        </svg>
      </div>
    </ChartPanel>
  );
}

function PeerRelationHeatmap({ model }: { model: GraphInsightModel }) {
  const peer = useMemo(() => buildPeerInsights(model), [model]);
  const relationItems = peer.relationItems.slice(0, 8);
  const max = Math.max(1, ...peer.layerItems.flatMap((layer) => layer.relationCounts.map((item) => item.count)));

  return (
    <ChartPanel title="同级关系热力" description="同一层内部到底是说明、应用、对比还是训练更多，一眼看出。">
      <div className="overflow-x-auto p-4">
        <div
          className="grid min-w-[680px] gap-1.5"
          style={{ gridTemplateColumns: `92px repeat(${peer.layerItems.length}, minmax(90px, 1fr))` }}
        >
          <div />
          {peer.layerItems.map((layer) => (
            <div key={layer.layer} className="px-2 py-1 text-center text-[11px] font-semibold text-slate-500 dark:text-slate-400">
              {layer.label}
            </div>
          ))}
          {relationItems.map((relation) => (
            <Fragment key={relation.type}>
              <div className="flex items-center gap-2 px-2 text-[11px] font-semibold text-slate-500 dark:text-slate-400">
                <span className="h-2 w-2 rounded-full" style={{ backgroundColor: relation.color }} />
                {relation.label}
              </div>
              {peer.layerItems.map((layer) => {
                const count = layer.relationCounts.find((item) => item.type === relation.type)?.count ?? 0;
                const intensity = count / max;
                return (
                  <div
                    key={`${relation.type}-${layer.layer}`}
                    className="flex h-14 items-center justify-center rounded-lg border border-slate-200 text-sm font-semibold tabular-nums dark:border-slate-800"
                    style={{
                      backgroundColor: count ? `color-mix(in srgb, ${relation.color} ${18 + intensity * 54}%, white)` : "rgba(248, 250, 252, 0.82)",
                      color: count && intensity > 0.56 ? "#ffffff" : "#334155",
                    }}
                  >
                    {count || ""}
                  </div>
                );
              })}
            </Fragment>
          ))}
        </div>
      </div>
    </ChartPanel>
  );
}

function PeerPairList({ model }: { model: GraphInsightModel }) {
  const peer = useMemo(() => buildPeerInsights(model), [model]);

  return (
    <ChartPanel title="同级连接榜" description="这些是同一学习层里最强的知识连接，适合做类比、辨析或成组复习。">
      <div className="grid gap-2 p-4">
        {peer.topPairs.length ? (
          peer.topPairs.map((pair, index) => (
            <div key={pair.id} className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2.5 dark:border-slate-800 dark:bg-slate-900/60">
              <div className="flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold text-slate-900 dark:text-slate-100">
                    {index + 1}. {truncateGraphLabel(pair.source.canonical_name, 12)}
                    <span className="mx-1.5 text-slate-400">↔</span>
                    {truncateGraphLabel(pair.target.canonical_name, 12)}
                  </p>
                  <p className="mt-1 text-[11px] text-slate-500 dark:text-slate-400">
                    {LEARNING_LAYERS[pair.source.layer]?.label ?? "同层"} · {pair.relationLabel}
                  </p>
                </div>
                <span className="h-2.5 w-10 shrink-0 rounded-full" style={{ backgroundColor: pair.color }} />
              </div>
            </div>
          ))
        ) : (
          <div className="rounded-lg border border-dashed border-slate-200 bg-slate-50 px-4 py-8 text-center text-sm text-slate-500 dark:border-slate-800 dark:bg-slate-900/60 dark:text-slate-400">
            暂无同级关系。
          </div>
        )}
      </div>
    </ChartPanel>
  );
}

function PeerMode({ model }: { model: GraphInsightModel }) {
  return (
    <div className="grid gap-4">
      <PeerOrbitMap model={model} />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.08fr)_minmax(0,0.92fr)]">
        <PeerRelationHeatmap model={model} />
        <PeerPairList model={model} />
      </div>
    </div>
  );
}

function FlowMode({ model }: { model: GraphInsightModel }) {
  return (
    <div className="grid gap-4">
      <LayerFlowMap model={model} />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)]">
        <RelationChordMap model={model} />
        <RelationBars model={model} />
      </div>
    </div>
  );
}

function MatrixMode({ model }: { model: GraphInsightModel }) {
  return (
    <div className="grid gap-4">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        <MetricPill label="知识类型" value={`${model.typeItems.length}`} tone="neutral" />
        <MetricPill label="知识岛" value={`${model.componentCount}`} tone={model.componentCount <= 2 ? "good" : model.componentCount <= 5 ? "warn" : "bad"} />
        <MetricPill label="孤立点" value={`${model.isolatedCount}`} tone={model.isolatedCount === 0 ? "good" : model.isolatedCount <= 3 ? "warn" : "bad"} />
        <MetricPill label="关系置信" value={percentText(model.relationConfidenceAvg)} tone={scoreTone(model.relationConfidenceAvg, 0.72, 0.84)} />
        <MetricPill label="图谱密度" value={`${model.densityPct.toFixed(2)}%`} tone="neutral" />
      </div>
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.08fr)_minmax(0,0.92fr)]">
        <MatrixHeatmap model={model} />
        <TypeBubbleBoard model={model} />
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        <NodeRankPanel title="关键枢纽" nodes={model.bottleneckNodes} emptyText="暂无可识别的关键枢纽。" />
        <NodeRankPanel title="补强清单" nodes={model.gapNodes} emptyText="暂时没有明显补强项。" />
      </div>
    </div>
  );
}

export function KnowledgeGraphInsightsView({
  course,
  toolbar,
}: {
  course: string;
  toolbar?: ReactNode;
}) {
  const [mode, setMode] = useState<InsightMode>("atlas");
  const { data, isLoading } = useQuery({
    queryKey: ["graph-insights-full", course],
    queryFn: async () =>
      unwrapOrvalResponse(
        await graphFullApiV1CoursesCourseIdKnowledgeGraphFullPost(course),
      ) ?? null,
    enabled: Boolean(course),
    retry: false,
  });
  const model = useMemo(() => buildInsightModel(data), [data]);

  if (isLoading) {
    return (
      <div className="flex h-full flex-col bg-slate-50 dark:bg-slate-950">
        <div className="flex items-center gap-3 border-b border-slate-200 bg-white px-3 py-2 dark:border-slate-800 dark:bg-slate-950">
          {toolbar}
        </div>
        <div className="flex flex-1 items-center justify-center text-sm text-slate-500 dark:text-slate-400">
          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          正在生成图谱可视化...
        </div>
      </div>
    );
  }

  if (!model.nodeCount) {
    return (
      <div className="flex h-full flex-col bg-slate-50 dark:bg-slate-950">
        <div className="flex items-center gap-3 border-b border-slate-200 bg-white px-3 py-2 dark:border-slate-800 dark:bg-slate-950">
          {toolbar}
        </div>
        <div className="flex flex-1 items-center justify-center text-sm text-slate-500 dark:text-slate-400">
          暂无可绘制的图谱数据
        </div>
      </div>
    );
  }

  const tabs: Array<{ id: InsightMode; label: string; icon: typeof Network }> = [
    { id: "atlas", label: "星云图", icon: Sparkles },
    { id: "peer", label: "同级图", icon: GitBranch },
    { id: "flow", label: "关系流", icon: Route },
    { id: "matrix", label: "结构矩阵", icon: BarChart3 },
  ];

  return (
    <div className="flex h-full min-h-0 flex-col bg-slate-50 text-slate-900 dark:bg-slate-950 dark:text-slate-100">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 bg-white px-3 py-2 dark:border-slate-800 dark:bg-slate-950">
        {toolbar}
        <div className="flex items-center gap-1 rounded-lg bg-slate-100 p-0.5 dark:bg-slate-900">
          {tabs.map((item) => {
            const Icon = item.icon;
            const active = mode === item.id;
            return (
              <button
                key={item.id}
                type="button"
                onClick={() => setMode(item.id)}
                className={`flex h-8 items-center gap-1.5 rounded-md px-2.5 text-xs font-medium transition-colors ${
                  active
                    ? "bg-white text-slate-900 shadow-sm dark:bg-slate-800 dark:text-slate-100"
                    : "text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200"
                }`}
              >
                <Icon className="h-3.5 w-3.5" />
                {item.label}
              </button>
            );
          })}
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {mode === "atlas" ? <AtlasGraph model={model} /> : null}
        {mode === "peer" ? <PeerMode model={model} /> : null}
        {mode === "flow" ? <FlowMode model={model} /> : null}
        {mode === "matrix" ? <MatrixMode model={model} /> : null}
      </div>
    </div>
  );
}
