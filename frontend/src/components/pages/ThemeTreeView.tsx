import { useState } from "react";
import {
  ChevronRight,
  ChevronDown,
  FolderTree,
  BookOpen,
} from "lucide-react";
import type {
  KnowledgeOverviewThemeNode as ThemeTreeNodeResponse,
  KnowledgeOverviewThemeTree as ThemeTreeResponse,
  KnowledgeOverviewThemeUnit as TreeUnitItem,
} from "../../api/knowledgeOverview";
import { Card, CardContent } from "../ui/Card";
import { MarkdownViewer } from "../ui/MarkdownViewer";

const NODE_TYPE_LABEL: Record<string, { label: string; color: string }> = {
  theme: { label: "主题", color: "bg-indigo-50 text-indigo-600" },
  THEME: { label: "主题", color: "bg-indigo-50 text-indigo-600" },
  chapter: { label: "章节", color: "bg-blue-50 text-blue-600" },
  CHAPTER: { label: "章节", color: "bg-blue-50 text-blue-600" },
  section: { label: "小节", color: "bg-cyan-50 text-cyan-600" },
  SECTION: { label: "小节", color: "bg-cyan-50 text-cyan-600" },
  module: { label: "模块", color: "bg-purple-50 text-purple-600" },
  MODULE: { label: "模块", color: "bg-purple-50 text-purple-600" },
  uncategorized: { label: "待归类", color: "bg-slate-100 text-slate-500" },
};

const ROLE_LABEL: Record<string, string> = {
  primary: "核心",
  secondary: "辅助",
  reference: "参考",
};

function UnitCard({ unit }: { unit: TreeUnitItem }) {
  return (
    <div className="flex items-center gap-3 px-4 py-3 rounded-lg border border-emerald-100 bg-emerald-50/50 hover:bg-emerald-50 transition-colors">
      <BookOpen className="w-4 h-4 text-emerald-500 shrink-0" />
      <span className="text-sm text-slate-700 flex-1 [&_p]:mb-0 [&_p]:inline">
        <MarkdownViewer content={unit.canonical_name} />
      </span>
      <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-600 shrink-0">
        {ROLE_LABEL[unit.membership_role] ?? unit.membership_role}
      </span>
    </div>
  );
}

function TreeNode({ node, depth = 0 }: { node: ThemeTreeNodeResponse; depth?: number }) {
  const [expanded, setExpanded] = useState(depth < 2);
  const children = node.children ?? [];
  const units = node.units ?? [];
  const hasChildren = children.length > 0;
  const hasUnits = units.length > 0;
  const canExpand = hasChildren || hasUnits;
  const isUncategorized = node.node_type === "uncategorized";

  const typeInfo = NODE_TYPE_LABEL[node.node_type] ?? {
    label: node.node_type,
    color: "bg-slate-100 text-slate-600",
  };

  return (
    <li>
      <div
        className={`flex items-start gap-2 py-2 px-3 rounded-lg transition-colors ${
          canExpand ? "cursor-pointer hover:bg-slate-50" : ""
        } ${depth === 0 ? "font-medium text-slate-800" : "text-slate-700"}`}
        style={{ paddingLeft: `${depth * 24 + 12}px` }}
        onClick={() => canExpand && setExpanded((v) => !v)}
      >
        {canExpand ? (
          expanded ? (
            <ChevronDown className="w-4 h-4 text-slate-400 mt-0.5 shrink-0" />
          ) : (
            <ChevronRight className="w-4 h-4 text-slate-400 mt-0.5 shrink-0" />
          )
        ) : (
          <span className="w-4 shrink-0" />
        )}
        <FolderTree className={`w-4 h-4 mt-0.5 shrink-0 ${isUncategorized ? "text-slate-400" : "text-indigo-400"}`} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm">{isUncategorized ? "学习内容" : node.title}</span>
            {!isUncategorized && (
              <span className={`text-[10px] px-1.5 py-0.5 rounded shrink-0 ${typeInfo.color}`}>
                {typeInfo.label}
              </span>
            )}
            {hasUnits && <span className="text-[10px] text-slate-400 shrink-0">{units.length} 个教学单元</span>}
          </div>
          {node.summary && expanded && (
            <div className="text-xs text-slate-500 mt-1 line-clamp-2">
              <MarkdownViewer content={node.summary} />
            </div>
          )}
        </div>
      </div>

      {expanded && (
        <div style={{ paddingLeft: `${(depth + 1) * 24 + 12}px` }}>
          {hasUnits && (
            <div className="space-y-2 py-2">
              {units.map((unit) => (
                <UnitCard key={unit.teaching_unit_id} unit={unit} />
              ))}
            </div>
          )}
          {hasChildren && (
            <ul className="space-y-0.5">
              {children.map((child) => (
                <TreeNode key={child.id} node={child} depth={depth + 1} />
              ))}
            </ul>
          )}
        </div>
      )}
    </li>
  );
}

export function ThemeTreeView({
  overviewData,
}: {
  overviewData: ThemeTreeResponse | null;
}) {
  const tree = overviewData?.tree ?? [];
  if (!overviewData || tree.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-slate-400">
        <FolderTree className="w-8 h-8 mb-2 text-slate-300" />
        <p className="text-sm">还没有可展示的主题树</p>
        <p className="text-xs mt-1">文件解析完成后，请触发 digest 构建生成课程结构</p>
      </div>
    );
  }

  const countUnits = (nodes: ThemeTreeNodeResponse[]): number =>
    nodes.reduce((sum, node) => sum + (node.units?.length ?? 0) + countUnits(node.children ?? []), 0);

  return (
    <Card>
      <CardContent className="pt-6">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3 text-sm text-slate-500">
            <span>版本 v{overviewData.version_no}</span>
            <span className={`text-xs px-1.5 py-0.5 rounded ${overviewData.status === "published" ? "bg-green-50 text-green-600" : "bg-yellow-50 text-yellow-600"}`}>
              {overviewData.status === "published" ? "已发布" : overviewData.status}
            </span>
            <span>{countUnits(tree)} 个教学单元</span>
          </div>
        </div>
        <ul className="space-y-1">
          {tree.map((node) => (
            <TreeNode key={node.id} node={node} />
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
