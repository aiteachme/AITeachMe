import type * as d3 from "d3";

import type { GraphEdgeResponse } from "../../api/generated/model";

export type NodeVisualRole = "assessment_core" | "support" | "context";

export type NodeVisualStyle = {
  fill: string;
  dark: string;
  soft: string;
  label: string;
  role: NodeVisualRole;
  roleLabel: string;
};

export type GraphLayer = {
  label: string;
  description: string;
};

export type RelationFilterItem = {
  type: string;
  label: string;
  color: string;
  count: number;
  active: boolean;
};

export interface GraphNode extends d3.SimulationNodeDatum {
  id: number;
  canonical_name: string;
  knowledge_unit_type: string;
  confidence: number;
  degree: number;
  label_rank: number;
  component_id: number;
  component_size: number;
  component_rank: number;
  layout_layer: number;
  layout_rank: number;
}

export interface GraphLink extends d3.SimulationLinkDatum<GraphNode> {
  id: number;
  edge_type: string;
  relation_label: string;
  label_width: number;
  source_node_id: number;
  target_node_id: number;
  weight: number;
  confidence: number;
  source_degree: number;
  target_degree: number;
  pair_index: number;
  pair_total: number;
  curvature: number;
  is_backbone: boolean;
}

export const NODE_COLORS: Record<string, NodeVisualStyle> = {
  core_knowledge: { fill: "#2563eb", dark: "#1d4ed8", soft: "#dbeafe", label: "核心知识", role: "assessment_core", roleLabel: "必须知道" },
  method_demo: { fill: "#f97316", dark: "#ea580c", soft: "#ffedd5", label: "方法示范", role: "assessment_core", roleLabel: "怎么做" },
  explanation_support: { fill: "#64748b", dark: "#475569", soft: "#f1f5f9", label: "解释辅助", role: "support", roleLabel: "帮助理解" },
  principle_reasoning: { fill: "#0f766e", dark: "#115e59", soft: "#ccfbf1", label: "原理推理", role: "assessment_core", roleLabel: "为什么" },
  practice_assessment: { fill: "#ef4444", dark: "#dc2626", soft: "#fee2e2", label: "练习评估", role: "assessment_core", roleLabel: "练会了吗" },
  knowledge_organization: { fill: "#7c3aed", dark: "#6d28d9", soft: "#ede9fe", label: "知识组织", role: "context", roleLabel: "怎么安排" },
  application_extension: { fill: "#a855f7", dark: "#9333ea", soft: "#f3e8ff", label: "应用拓展", role: "support", roleLabel: "能做什么" },
};

export const DEFAULT_COLOR: NodeVisualStyle = {
  fill: "#94a3b8",
  dark: "#64748b",
  soft: "#f1f5f9",
  label: "其他",
  role: "context",
  roleLabel: "补充信息",
};

export const RELATION_LABELS: Record<string, string> = {
  prerequisite: "前置",
  contains: "包含",
  reasoning: "推理",
  application: "应用",
  explanation: "说明",
  training: "训练",
  contrast: "对比",
  similar: "相似",
};

export const RELATION_COLORS: Record<string, string> = {
  prerequisite: "#64748b",
  contains: "#94a3b8",
  reasoning: "#0f766e",
  application: "#60a5fa",
  explanation: "#64748b",
  training: "#ef4444",
  contrast: "#f97316",
  similar: "#14b8a6",
};

export const GRAPH_LAYERS: GraphLayer[] = [
  { label: "组织", description: "目标 / 框架 / 路径" },
  { label: "知识", description: "概念 / 规则 / 事实" },
  { label: "原理", description: "推理 / 机制 / 条件" },
  { label: "方法", description: "例题 / 步骤 / 操作" },
  { label: "训练", description: "练习 / 应用 / 拓展" },
];

export const EDGE_TYPE_PRIORITY: Record<string, number> = {
  prerequisite: 8,
  contains: 7,
  reasoning: 6,
  application: 5,
  explanation: 4,
  training: 4,
  contrast: 2,
  similar: 1,
};

const NODE_TYPE_LAYER: Record<string, number> = {
  knowledge_organization: 0,
  core_knowledge: 1,
  principle_reasoning: 2,
  method_demo: 3,
  explanation_support: 3,
  practice_assessment: 4,
  application_extension: 4,
};

export function truncateGraphLabel(value: string, maxChars = 12): string {
  const text = String(value || "").trim();
  if (text.length <= maxChars) return text;
  return `${text.slice(0, maxChars - 1)}...`;
}

export function relationLabel(edgeType: string): string {
  return RELATION_LABELS[edgeType] ?? edgeType.replace(/_/g, " ");
}

export function relationTone(edgeType: string): string {
  return RELATION_COLORS[edgeType] ?? "#94a3b8";
}

export function deterministicEdgeBend(edge: Pick<GraphEdgeResponse, "id" | "source_node_id" | "target_node_id" | "edge_type">): number {
  const seed = `${edge.id}:${edge.source_node_id}:${edge.target_node_id}:${edge.edge_type}`;
  let hash = 0;
  for (let index = 0; index < seed.length; index += 1) {
    hash = Math.imul(31, hash) + seed.charCodeAt(index);
  }
  const sign = hash % 2 === 0 ? 1 : -1;
  const magnitude = 0.22 + (Math.abs(hash) % 4) * 0.035;
  return sign * magnitude;
}

export function clampGraphLayer(value: number): number {
  return Math.max(0, Math.min(GRAPH_LAYERS.length - 1, Math.round(value)));
}

export function nodeBaseLayer(nodeType: string): number {
  return NODE_TYPE_LAYER[nodeType] ?? 2;
}

export function isDirectionalLearningEdge(edgeType: string): boolean {
  return edgeType !== "similar" && edgeType !== "contrast";
}

export function getLearningEdgeDirection(edge: Pick<GraphLink, "source_node_id" | "target_node_id" | "edge_type">): {
  from: number;
  to: number;
} | null {
  if (!isDirectionalLearningEdge(edge.edge_type)) return null;
  return {
    from: edge.source_node_id,
    to: edge.target_node_id,
  };
}

export function edgePriority(edge: Pick<GraphLink, "edge_type" | "confidence" | "weight">): number {
  return (EDGE_TYPE_PRIORITY[edge.edge_type] ?? 0) + Math.max(0, edge.confidence || 0) + Math.max(0, edge.weight || 0) * 0.1;
}

export function isBackboneEdge(edge: Pick<GraphLink, "edge_type" | "confidence" | "weight" | "source_degree" | "target_degree">): boolean {
  if (edge.edge_type === "prerequisite" || edge.edge_type === "contains" || edge.edge_type === "reasoning") return true;
  if (edge.edge_type === "application" || edge.edge_type === "training") {
    return Math.max(edge.source_degree, edge.target_degree) >= 2 || edgePriority(edge) >= 4.8;
  }
  return edgePriority(edge) >= 3.1 && Math.min(edge.source_degree, edge.target_degree) <= 4;
}

export function nodeStyle(unitType: string): NodeVisualStyle {
  return NODE_COLORS[unitType] ?? DEFAULT_COLOR;
}

export function isAssessmentCoreNode(node: Pick<GraphNode, "knowledge_unit_type">): boolean {
  return nodeStyle(node.knowledge_unit_type).role === "assessment_core";
}

export function graphNodePriority(node: Pick<GraphNode, "knowledge_unit_type" | "degree" | "confidence">): number {
  const roleScore = nodeStyle(node.knowledge_unit_type).role === "assessment_core"
    ? 1.45
    : nodeStyle(node.knowledge_unit_type).role === "support"
      ? 1.08
      : 0.9;
  const degreeScore = Math.min(0.42, Math.sqrt(Math.max(0, node.degree)) * 0.11);
  const confidenceScore = Math.max(0, Math.min(1, node.confidence || 0)) * 0.12;
  return roleScore + degreeScore + confidenceScore;
}

export function graphNodeRadius(node: GraphNode): number {
  const style = nodeStyle(node.knowledge_unit_type);
  const roleBase = style.role === "assessment_core" ? 7.8 : style.role === "support" ? 7.0 : 6.4;
  const degreeBoost = Math.sqrt(Math.max(1, node.degree)) * (style.role === "assessment_core" ? 1.28 : 0.92);
  return Math.min(style.role === "assessment_core" ? 14.5 : 11.5, roleBase + degreeBoost);
}

export function graphNodeLabelLimit(node: GraphNode, selectedNodeId: number | null): number {
  if (node.id === selectedNodeId) return 24;
  if (isAssessmentCoreNode(node)) return node.degree >= 3 ? 20 : 17;
  return node.degree >= 4 ? 17 : 14;
}

export function estimateGraphLabelWidth(label: string, maxChars: number): number {
  const text = truncateGraphLabel(label, maxChars);
  let width = 0;
  for (const char of text) {
    width += /[\u4e00-\u9fff]/.test(char) ? 12 : 6.8;
  }
  return Math.min(170, Math.max(34, width + 18));
}

export function estimateRelationLabelWidth(label: string): number {
  let width = 0;
  for (const char of label) {
    width += /[\u4e00-\u9fff]/.test(char) ? 10 : 6;
  }
  return Math.min(74, Math.max(30, width + 14));
}

export function shouldShowSmartNodeLabel(
  node: GraphNode,
  selectedNodeId: number | null,
  selectedNeighbors: Set<number>,
  showAllNodeLabels: boolean,
): boolean {
  if (showAllNodeLabels) return true;
  if (node.id === selectedNodeId || selectedNeighbors.has(node.id)) return true;
  if (isAssessmentCoreNode(node)) {
    if (node.label_rank <= 34) return true;
    return node.degree >= 4 && node.label_rank <= 52;
  }
  return node.degree >= 5 && node.label_rank <= 42;
}
