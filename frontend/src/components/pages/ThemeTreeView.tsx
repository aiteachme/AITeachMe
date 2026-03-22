import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ChevronRight,
  ChevronDown,
  Loader2,
  FolderTree,
  BookOpen,
  AlertCircle,
} from "lucide-react";
import { getApiErrorMessage, isApiErrorStatus } from "../../api/client";
import { themeTreeCurrentApiV1SubjectsSubjectKnowledgeThemeTreeCurrentPost } from "../../api/generated/knowledge";
import type { ThemeTreeNodeResponse, TreeUnitItem } from "../../api/generated/model";
import { unwrapOrvalResponse } from "../../api/generated/utils";
import { Card, CardContent } from "../ui/Card";
import { MarkdownViewer } from "../ui/MarkdownViewer";

/* ---------- 节点类型映射 ---------- */

const NODE_TYPE_LABEL: Record<string, { label: string; color: string }> = {
  theme:         { label: "主题", color: "bg-indigo-50 text-indigo-600" },
  THEME:         { label: "主题", color: "bg-indigo-50 text-indigo-600" },
  chapter:       { label: "章节", color: "bg-blue-50 text-blue-600" },
  CHAPTER:       { label: "章节", color: "bg-blue-50 text-blue-600" },
  section:       { label: "小节", color: "bg-cyan-50 text-cyan-600" },
  SECTION:       { label: "小节", color: "bg-cyan-50 text-cyan-600" },
  module:        { label: "模块", color: "bg-purple-50 text-purple-600" },
  MODULE:        { label: "模块", color: "bg-purple-50 text-purple-600" },
  uncategorized: { label: "待归类", color: "bg-slate-100 text-slate-500" },
};

const ROLE_LABEL: Record<string, string> = {
  primary: "核心",
  secondary: "辅助",
  reference: "参考",
};

/* ---------- 教学单元卡片 ---------- */

function UnitCard({ unit }: { unit: TreeUnitItem }) {
  return (
    <div className="flex items-center gap-3 px-4 py-3 rounded-lg border border-emerald-100 bg-emerald-50/50 hover:bg-emerald-50 transition-colors">
      <BookOpen className="w-4 h-4 text-emerald-500 shrink-0" />
      <span className="text-sm text-slate-700 flex-1 [&_p]:mb-0 [&_p]:inline"><MarkdownViewer content={unit.canonical_name} /></span>
      <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-600 shrink-0">
        {ROLE_LABEL[unit.membership_role] ?? unit.membership_role}
      </span>
    </div>
  );
}

/* ---------- 递归树节点 ---------- */

function TreeNode({ node, depth = 0 }: { node: ThemeTreeNodeResponse; depth?: number }) {
  const [expanded, setExpanded] = useState(depth < 2);
  const children = node.children ?? [];
  const units = node.units ?? [];
  const hasChildren = children.length > 0;
  const hasUnits = units.length > 0;
  const isUncategorized = node.node_type === "uncategorized";
  const canExpand = hasChildren || hasUnits;

  const typeInfo = NODE_TYPE_LABEL[node.node_type] ?? {
    label: node.node_type,
    color: "bg-slate-100 text-slate-600",
  };

  // 对于 uncategorized 根节点，用更友好的标题
  const displayTitle = isUncategorized ? "学习内容" : node.title;

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
        <FolderTree className={`w-4 h-4 mt-0.5 shrink-0 ${
          isUncategorized ? "text-slate-400" : "text-indigo-400"
        }`} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm">{displayTitle}</span>
            {!isUncategorized && (
              <span className={`text-[10px] px-1.5 py-0.5 rounded shrink-0 ${typeInfo.color}`}>
                {typeInfo.label}
              </span>
            )}
            {hasUnits && (
              <span className="text-[10px] text-slate-400 shrink-0">
                {units.length} 个教学单元
              </span>
            )}
          </div>
          {node.summary && expanded && (
            <div className="text-xs text-slate-500 mt-1 line-clamp-2"><MarkdownViewer content={node.summary} /></div>
          )}
        </div>
      </div>

      {expanded && (
        <div style={{ paddingLeft: `${(depth + 1) * 24 + 12}px` }}>
          {/* 挂载的教学单元 */}
          {hasUnits && (
            <div className="space-y-2 py-2">
              {units.map((u: TreeUnitItem) => (
                <UnitCard key={u.teaching_unit_id} unit={u} />
              ))}
            </div>
          )}
          {/* 子节点 */}
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

/* ---------- 主组件 ---------- */

export function ThemeTreeView({ subject }: { subject: string }) {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["theme-tree", subject],
    queryFn: async () => {
      try {
        return unwrapOrvalResponse(
          await themeTreeCurrentApiV1SubjectsSubjectKnowledgeThemeTreeCurrentPost(subject),
        ) ?? null;
      } catch (queryError) {
        if (isApiErrorStatus(queryError, 404, "NO_PUBLISHED_TREE")) {
          return null;
        }
        throw queryError;
      }
    },
    enabled: !!subject,
    retry: false,
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-16 text-slate-400">
        <Loader2 className="w-5 h-5 animate-spin mr-2" />加载主题树...
      </div>
    );
  }

  if (isError) {
    const msg = getApiErrorMessage(error, "加载主题树失败");
    return (
      <div className="flex flex-col items-center justify-center py-16 text-slate-400">
        <AlertCircle className="w-8 h-8 mb-2 text-slate-300" />
        <p className="text-sm">{msg}</p>
        <p className="text-xs mt-1">请稍后重试，或先确认学科与构建状态</p>
      </div>
    );
  }

  const tree = data?.tree ?? [];

  if (!data || tree.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-slate-400">
        <FolderTree className="w-8 h-8 mb-2 text-slate-300" />
        <p className="text-sm">还没有可展示的主题树</p>
        <p className="text-xs mt-1">文件解析完成后，请触发 digest 构建生成课程结构</p>
      </div>
    );
  }

  // 统计总教学单元数
  const countUnits = (nodes: ThemeTreeNodeResponse[]): number =>
    nodes.reduce((sum, n) => sum + (n.units?.length ?? 0) + countUnits(n.children ?? []), 0);
  const totalUnits = countUnits(tree);

  return (
    <Card>
      <CardContent className="pt-6">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3 text-sm text-slate-500">
            <span>版本 v{data.version_no}</span>
            <span className={`text-xs px-1.5 py-0.5 rounded ${
              data.status === "published"
                ? "bg-green-50 text-green-600"
                : "bg-yellow-50 text-yellow-600"
            }`}>
              {data.status === "published" ? "已发布" : data.status}
            </span>
            <span>{totalUnits} 个教学单元</span>
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
