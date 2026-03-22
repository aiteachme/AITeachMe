import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Loader2,
  AlertCircle,
  GitBranch,
  ArrowRight,
  BookOpen,
} from "lucide-react";
import { getApiErrorMessage } from "../../api/client";
import { fetchPrereqDag, fetchTeachingUnits, type UnitDependencyItem } from "../../api/graphApi";
import { Card, CardContent } from "../ui/Card";
import { MarkdownViewer } from "../ui/MarkdownViewer";

/* ---------- 辅助：构建拓扑层级 ---------- */

interface DagNode {
  id: number;
  name: string;
  layer: number;
  deps: number[];       // 依赖的 unit ids（先修）
  dependents: number[]; // 被谁依赖
}

function buildLayers(dependencies: UnitDependencyItem[]): DagNode[] {
  // 收集所有 unit
  const nodeMap = new Map<number, DagNode>();
  for (const dep of dependencies) {
    if (!nodeMap.has(dep.source_unit_id)) {
      nodeMap.set(dep.source_unit_id, {
        id: dep.source_unit_id,
        name: dep.source_unit_name,
        layer: 0,
        deps: [],
        dependents: [],
      });
    }
    if (!nodeMap.has(dep.target_unit_id)) {
      nodeMap.set(dep.target_unit_id, {
        id: dep.target_unit_id,
        name: dep.target_unit_name,
        layer: 0,
        deps: [],
        dependents: [],
      });
    }
    // source 依赖 target（target 是先修）
    nodeMap.get(dep.source_unit_id)!.deps.push(dep.target_unit_id);
    nodeMap.get(dep.target_unit_id)!.dependents.push(dep.source_unit_id);
  }

  // 拓扑排序分层
  const inDegree = new Map<number, number>();
  for (const [id, node] of nodeMap) {
    inDegree.set(id, node.deps.length);
  }

  let currentLayer = 0;
  let queue = [...inDegree.entries()].filter(([, d]) => d === 0).map(([id]) => id);

  while (queue.length > 0) {
    const nextQueue: number[] = [];
    for (const id of queue) {
      const node = nodeMap.get(id)!;
      node.layer = currentLayer;
      for (const depId of node.dependents) {
        const deg = (inDegree.get(depId) ?? 1) - 1;
        inDegree.set(depId, deg);
        if (deg === 0) nextQueue.push(depId);
      }
    }
    currentLayer++;
    queue = nextQueue;
  }

  return [...nodeMap.values()].sort((a, b) => a.layer - b.layer || a.name.localeCompare(b.name));
}

/* ---------- 依赖类型标签 ---------- */

const DEP_TYPE_LABEL: Record<string, { label: string; color: string }> = {
  prerequisite_of: { label: "先修", color: "bg-blue-50 text-blue-600" },
  part_of: { label: "组成", color: "bg-purple-50 text-purple-600" },
  related_to: { label: "关联", color: "bg-slate-100 text-slate-600" },
};

/* ---------- 无依赖时展示教学单元 ---------- */

import type { PrereqDagResponse } from "../../api/graphApi";

function NoDependenciesView({ subject, dagData }: { subject: string; dagData: PrereqDagResponse | null | undefined }) {
  const { data: unitsData } = useQuery({
    queryKey: ["teaching-units-dag", subject],
    queryFn: () => fetchTeachingUnits(subject),
    enabled: !!subject,
  });

  const units = unitsData?.items ?? [];

  return (
    <div className="space-y-4">
      {dagData && (
        <Card>
          <CardContent className="pt-6">
            <div className="flex items-center gap-3 text-sm text-slate-500 mb-2">
              <span>版本 v{dagData.version_no}</span>
              <span className="text-xs px-1.5 py-0.5 rounded bg-green-50 text-green-600">
                {dagData.status === "published" ? "已发布" : dagData.status}
              </span>
            </div>
            <p className="text-sm text-slate-500">
              当前教学单元之间暂未发现先修依赖关系，所有单元可以按任意顺序学习。
            </p>
          </CardContent>
        </Card>
      )}

      {units.length > 0 && (
        <Card>
          <CardContent className="pt-6">
            <h3 className="text-sm font-medium text-slate-700 mb-3">
              教学单元（{units.length} 个，无先后顺序）
            </h3>
            <div className="space-y-2">
              {units.map((unit) => (
                <div
                  key={unit.id}
                  className="flex items-center gap-2 px-3 py-2 rounded-lg bg-slate-50 text-sm"
                >
                  <BookOpen className="w-4 h-4 text-emerald-500 shrink-0" />
                  <span className="text-slate-700 flex-1 [&_p]:mb-0 [&_p]:inline"><MarkdownViewer content={unit.canonical_name} /></span>
                  <span className="text-[10px] text-slate-400">
                    {Math.round(unit.confidence * 100)}%
                  </span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {!dagData && units.length === 0 && (
        <div className="flex flex-col items-center justify-center py-16 text-slate-400">
          <GitBranch className="w-8 h-8 mb-2 text-slate-300" />
          <p className="text-sm">暂无先修依赖关系</p>
          <p className="text-xs mt-1">请先上传资料并触发知识图谱构建</p>
        </div>
      )}
    </div>
  );
}

/* ---------- 主组件 ---------- */

export function PrereqDagView({ subject }: { subject: string }) {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["prereq-dag", subject],
    queryFn: () => fetchPrereqDag(subject),
    enabled: !!subject,
    retry: false,
  });

  const layers = useMemo(() => {
    if (!data?.dependencies.length) return [];
    return buildLayers(data.dependencies);
  }, [data]);

  // 按层分组
  const layerGroups = useMemo(() => {
    const groups = new Map<number, DagNode[]>();
    for (const node of layers) {
      const arr = groups.get(node.layer) ?? [];
      arr.push(node);
      groups.set(node.layer, arr);
    }
    return [...groups.entries()].sort(([a], [b]) => a - b);
  }, [layers]);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-16 text-slate-400">
        <Loader2 className="w-5 h-5 animate-spin mr-2" />加载先修关系...
      </div>
    );
  }

  if (isError) {
    const msg = getApiErrorMessage(error, "加载先修关系失败");
    return (
      <div className="flex flex-col items-center justify-center py-16 text-slate-400">
        <AlertCircle className="w-8 h-8 mb-2 text-slate-300" />
        <p className="text-sm">{msg}</p>
        <p className="text-xs mt-1">请稍后重试，或先确认学科与构建状态</p>
      </div>
    );
  }

  if (!data || data.dependencies.length === 0) {
    return <NoDependenciesView subject={subject} dagData={data} />;
  }

  return (
    <div className="space-y-6">
      {/* 版本信息 */}
      <Card>
        <CardContent className="pt-6">
          <div className="flex items-center gap-3 text-sm text-slate-500 mb-4">
            <span>版本 v{data.version_no}</span>
            <span className={`text-xs px-1.5 py-0.5 rounded ${
              data.status === "published"
                ? "bg-green-50 text-green-600"
                : "bg-yellow-50 text-yellow-600"
            }`}>
              {data.status === "published" ? "已发布" : data.status}
            </span>
            <span>{data.dependencies.length} 条依赖关系</span>
          </div>

          {/* 拓扑层级视图 */}
          <div className="space-y-4">
            {layerGroups.map(([layer, nodes]) => (
              <div key={layer}>
                <div className="text-xs text-slate-400 mb-2 font-medium">
                  第 {layer + 1} 层 {layer === 0 ? "（基础知识）" : ""}
                </div>
                <div className="flex flex-wrap gap-2">
                  {nodes.map((node) => (
                    <div
                      key={node.id}
                      className="px-3 py-2 rounded-lg border border-slate-200 bg-white text-sm text-slate-700 hover:shadow-sm transition-shadow"
                    >
                      {node.name}
                      {node.deps.length > 0 && (
                        <span className="text-[10px] text-slate-400 ml-1.5">
                          ← {node.deps.length} 先修
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* 依赖边列表 */}
      <Card>
        <CardContent className="pt-6">
          <h3 className="text-sm font-medium text-slate-700 mb-3">依赖关系明细</h3>
          <div className="space-y-2 max-h-96 overflow-y-auto">
            {data.dependencies.map((dep) => {
              const typeInfo = DEP_TYPE_LABEL[dep.dependency_type] ?? {
                label: dep.dependency_type,
                color: "bg-slate-100 text-slate-600",
              };
              return (
                <div
                  key={dep.id}
                  className="flex items-center gap-2 px-3 py-2 rounded-lg bg-slate-50 text-sm"
                >
                  <span className="text-slate-700 truncate flex-1">{dep.target_unit_name}</span>
                  <ArrowRight className="w-3.5 h-3.5 text-slate-400 shrink-0" />
                  <span className="text-slate-700 truncate flex-1">{dep.source_unit_name}</span>
                  <span className={`text-[10px] px-1.5 py-0.5 rounded shrink-0 ${typeInfo.color}`}>
                    {typeInfo.label}
                  </span>
                  <span className="text-[10px] text-slate-400 shrink-0">
                    {Math.round(dep.confidence * 100)}%
                  </span>
                </div>
              );
            })}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
