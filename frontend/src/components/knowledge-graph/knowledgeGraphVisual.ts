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
  topic: { fill: "#6366f1", dark: "#4f46e5", soft: "#e0e7ff", label: "主题模块", role: "context", roleLabel: "结构" },
  concept: { fill: "#2563eb", dark: "#1d4ed8", soft: "#dbeafe", label: "核心概念", role: "assessment_core", roleLabel: "知识点" },
  principle: { fill: "#0f766e", dark: "#115e59", soft: "#ccfbf1", label: "原理性质", role: "assessment_core", roleLabel: "为什么" },
  formula_model: { fill: "#0891b2", dark: "#0e7490", soft: "#cffafe", label: "公式模型", role: "assessment_core", roleLabel: "怎么算" },
  procedure: { fill: "#f59e0b", dark: "#d97706", soft: "#fef3c7", label: "方法步骤", role: "assessment_core", roleLabel: "怎么做" },
  skill: { fill: "#f43f5e", dark: "#e11d48", soft: "#ffe4e6", label: "解题技能", role: "assessment_core", roleLabel: "练会了吗" },
  misconception: { fill: "#dc2626", dark: "#b91c1c", soft: "#fee2e2", label: "易错辨析", role: "assessment_core", roleLabel: "别踩坑" },
  application_case: { fill: "#a855f7", dark: "#9333ea", soft: "#f3e8ff", label: "应用案例", role: "support", roleLabel: "能做什么" },
};

export const SUPPRESSED_GRAPH_NODE_TYPES = new Set(["resource"]);

export function isSuppressedGraphNodeType(unitType: string | null | undefined): boolean {
  return SUPPRESSED_GRAPH_NODE_TYPES.has(String(unitType || "").trim());
}

export const DEFAULT_COLOR: NodeVisualStyle = {
  fill: "#94a3b8",
  dark: "#64748b",
  soft: "#f1f5f9",
  label: "其他",
  role: "context",
  roleLabel: "补充信息",
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

export const RELATION_COLORS: Record<string, string> = {
  part_of: "#94a3b8",
  prerequisite_for: "#64748b",
  derives_to: "#0f766e",
  applies_to: "#6366f1",
  uses_method: "#f59e0b",
  assesses: "#f43f5e",
  explains: "#64748b",
  remediates: "#dc2626",
  confuses_with: "#f97316",
  similar_to: "#14b8a6",
  extends_to: "#a855f7",
};

export const GRAPH_LAYERS: GraphLayer[] = [
  { label: "组织", description: "目标 / 框架 / 路径" },
  { label: "知识", description: "概念 / 公式 / 事实" },
  { label: "原理", description: "推理 / 机制 / 条件" },
  { label: "方法", description: "步骤 / 技能 / 纠错" },
  { label: "应用", description: "案例 / 迁移 / 练习" },
];

export const EDGE_TYPE_PRIORITY: Record<string, number> = {
  prerequisite_for: 8,
  part_of: 7,
  derives_to: 6,
  applies_to: 5,
  uses_method: 5,
  assesses: 4,
  explains: 3,
  remediates: 3,
  confuses_with: 2,
  similar_to: 1,
  extends_to: 1,
};

const NODE_TYPE_LAYER: Record<string, number> = {
  topic: 0,
  concept: 1,
  formula_model: 1,
  principle: 2,
  procedure: 3,
  skill: 3,
  misconception: 3,
  application_case: 4,
};

export function normalizeGraphTextLabel(value: string): string {
  return String(value || "")
    .replace(/\\\[([\s\S]*?)\\\]/g, "$1")
    .replace(/\\\(([\s\S]*?)\\\)/g, "$1")
    .replace(/\$\$([\s\S]*?)\$\$/g, "$1")
    .replace(/\$([^$]+)\$/g, "$1")
    .replace(/\\left\b|\\right\b/g, "")
    .replace(/\\times\b/g, "×")
    .replace(/\\cdot\b/g, "·")
    .replace(/\\div\b/g, "÷")
    .replace(/\\leq?\b/g, "≤")
    .replace(/\\geq?\b/g, "≥")
    .replace(/\\neq\b/g, "≠")
    .replace(/\\approx\b/g, "≈")
    .replace(/\\infty\b/g, "∞")
    .replace(/\\to\b/g, "→")
    .replace(/\\rightarrow\b/g, "→")
    .replace(/\\leftarrow\b/g, "←")
    .replace(/\\pm\b/g, "±")
    .replace(/\\sqrt\s*\{([^{}]+)\}/g, "√($1)")
    .replace(/\\frac\s*\{([^{}]+)\}\s*\{([^{}]+)\}/g, "$1/$2")
    .replace(/\\([a-zA-Z]+)\b/g, "$1")
    .replace(/[{}]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

export function truncateGraphLabel(value: string, maxChars = 12): string {
  const text = normalizeGraphTextLabel(value);
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
  return edgeType !== "similar_to" && edgeType !== "confuses_with";
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
  if (edge.edge_type === "prerequisite_for" || edge.edge_type === "part_of" || edge.edge_type === "derives_to") return true;
  if (edge.edge_type === "applies_to" || edge.edge_type === "uses_method" || edge.edge_type === "assesses") {
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
  const roleBase = style.role === "assessment_core" ? 9.2 : style.role === "support" ? 8.0 : 7.2;
  const degreeBoost = Math.sqrt(Math.max(1, node.degree)) * (style.role === "assessment_core" ? 1.34 : 1.0);
  return Math.min(style.role === "assessment_core" ? 16.2 : 13.2, roleBase + degreeBoost);
}

export function graphNodeLabelLimit(node: GraphNode, selectedNodeId: number | null): number {
  if (node.id === selectedNodeId) return 28;
  if (isAssessmentCoreNode(node)) return node.degree >= 3 ? 22 : 19;
  return node.degree >= 4 ? 19 : 16;
}

export function estimateGraphLabelWidth(label: string, maxChars: number): number {
  const text = truncateGraphLabel(label, maxChars);
  let width = 0;
  for (const char of text) {
    width += /[\u4e00-\u9fff]/.test(char) ? 13 : 7.4;
  }
  return Math.min(196, Math.max(42, width + 22));
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
  zoomScale = 1,
  visibleNodeCount = 0,
): boolean {
  const scale = Number.isFinite(zoomScale) ? zoomScale : 1;
  if (node.id === selectedNodeId || selectedNeighbors.has(node.id)) return true;
  const budget = graphNodeLabelBudget(visibleNodeCount, scale, showAllNodeLabels);
  if (showAllNodeLabels) {
    if (scale >= 0.9) return true;
    return scale >= 0.24 && node.label_rank <= budget;
  }
  if (scale >= 1.26) {
    if (visibleNodeCount <= 260) return true;
    return node.label_rank <= Math.max(budget, 180) || node.degree >= 2 || isAssessmentCoreNode(node);
  }
  if (scale >= 1.08) {
    if (visibleNodeCount <= 140) return true;
    return node.label_rank <= Math.max(budget, 96) || node.degree >= 3 || isAssessmentCoreNode(node);
  }
  if (node.label_rank > budget) return false;
  if (scale < 0.42) {
    return isAssessmentCoreNode(node) && node.label_rank <= Math.max(10, Math.min(18, budget));
  }
  if (scale < 0.68) {
    if (isAssessmentCoreNode(node)) return node.label_rank <= budget;
    return node.degree >= 5 && node.label_rank <= budget;
  }
  if (scale >= 1.12) {
    if (isAssessmentCoreNode(node)) return node.label_rank <= Math.max(42, budget) || node.degree >= 4;
    return (node.degree >= 3 || node.label_rank <= 48) && node.label_rank <= Math.max(64, budget);
  }
  if (isAssessmentCoreNode(node)) {
    if (node.label_rank <= 24) return true;
    return node.degree >= 5 && node.label_rank <= 36;
  }
  return node.degree >= 6 && node.label_rank <= 28;
}

export function graphNodeLabelBudget(
  visibleNodeCount: number,
  zoomScale = 1,
  showAllNodeLabels = false,
): number {
  const count = Math.max(1, Math.round(visibleNodeCount || 1));
  const scale = Number.isFinite(zoomScale) ? zoomScale : 1;
  const base = showAllNodeLabels
    ? Math.round(24 + scale * 36)
    : Math.round(20 + scale * 32);
  const densityPenalty = count > 220 ? 0.74 : count > 160 ? 0.82 : count > 100 ? 0.9 : 1;
  const maxByCount = showAllNodeLabels
    ? Math.min(count, Math.round(count * Math.min(1, 0.42 + scale * 0.32)))
    : Math.min(count, Math.round(28 + Math.sqrt(count) * 3.4 + scale * 18));
  return Math.max(showAllNodeLabels ? 18 : 14, Math.min(count, maxByCount, Math.round(base * densityPenalty)));
}

export function shouldShowSmartEdgeLabel(
  edge: GraphLink,
  selectedNodeId: number | null,
  showEdgeLabels: boolean,
  zoomScale = 1,
  visibleEdgeCount = 0,
): boolean {
  if (!showEdgeLabels) return false;
  const scale = Number.isFinite(zoomScale) ? zoomScale : 1;
  const connectedToSelection =
    selectedNodeId !== null && (edge.source_node_id === selectedNodeId || edge.target_node_id === selectedNodeId);
  if (connectedToSelection) return true;
  const count = Math.max(1, Math.round(visibleEdgeCount || 1));
  const crowded = count > 160;
  if (scale < (crowded ? 1.12 : 0.98)) return false;
  if (scale >= 1.72) return edge.is_backbone || edgePriority(edge) >= (crowded ? 5.2 : 4.6);
  if (scale >= 1.32) return edge.is_backbone && edgePriority(edge) >= (crowded ? 6.1 : 5.4);
  return edge.is_backbone && edgePriority(edge) >= 6.6;
}
