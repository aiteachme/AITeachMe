import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  AlertTriangle,
  FolderTree,
  GitBranch,
  Loader2,
  Network,
  Trash2
} from "lucide-react";

import { fetchKnowledgeOverview } from "../../api/knowledgeOverview";
import { knowledgeClearApiV1SubjectsSubjectKnowledgeClearPost } from "../../api/generated/knowledge";
import { getApiErrorMessage } from "../../api/client";

import { DigestBuildButton, DigestBuildProvider } from "./DigestBuildPanel";
import { KnowledgeGraphView } from "./KnowledgeGraphView";
import { PrereqDagView } from "./PrereqDagView";
import { ThemeTreeView } from "./ThemeTreeView";
import { Modal } from "../ui/Modal";
import { Button } from "../ui/Button";

type KnowledgeViewTab = "theme-tree" | "prereq-dag" | "knowledge-graph";

const VIEW_TABS: { id: KnowledgeViewTab; label: string; icon: React.ReactNode; desc: string }[] = [
  { id: "theme-tree", label: "主题树", icon: <FolderTree className="h-4 w-4" />, desc: "按章节与主题组织" },
  { id: "prereq-dag", label: "先修图", icon: <GitBranch className="h-4 w-4" />, desc: "展示学习顺序" },
  { id: "knowledge-graph", label: "图谱", icon: <Network className="h-4 w-4" />, desc: "展示节点关系" },
];

export function KnowledgeGraphSidePanel({ 
  subjectId,
}: { 
  subjectId: string;
}) {
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState<KnowledgeViewTab>("knowledge-graph");
  const [showClearConfirm, setShowClearConfirm] = useState(false);

  const {
    data: overview,
    isLoading: overviewLoading,
    isError: overviewIsError,
    error: overviewError,
  } = useQuery({
    queryKey: ["knowledge-overview", subjectId],
    queryFn: () => fetchKnowledgeOverview(subjectId),
    enabled: Boolean(subjectId), 
    retry: false,
  });

  const clearMutation = useMutation({
    mutationFn: () => knowledgeClearApiV1SubjectsSubjectKnowledgeClearPost(subjectId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["knowledge-overview", subjectId] });
      queryClient.invalidateQueries({ queryKey: ["graph-node-detail", subjectId] });
      setShowClearConfirm(false);
    },
  });

  return (
    <DigestBuildProvider subject={subjectId}>
      <div className="flex flex-col h-full w-full bg-white relative border-l border-slate-200/60 transition-colors duration-500">
        {/* Toolbar: Tabs & Actions */}
        <div className="flex items-center justify-between border-b border-slate-200 bg-white px-3 py-2 shrink-0 gap-4">
          
          {/* Left: View Tabs */}
          <div className="flex items-center gap-1 bg-slate-100/80 p-1 rounded-lg">
            {VIEW_TABS.map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`flex items-center justify-center gap-1.5 rounded-md px-3 py-1.5 text-[13px] font-medium transition-all ${
                  activeTab === tab.id
                    ? "bg-white text-slate-900 shadow-sm ring-1 ring-slate-200/50"
                    : "text-slate-500 hover:text-slate-800"
                }`}
                title={tab.desc}
              >
                {tab.icon}
                <span className="hidden lg:inline">{tab.label}</span>
              </button>
            ))}
          </div>
          
          {/* Right: Actions */}
          <div className="flex items-center gap-1.5 shrink-0 ml-auto">
            <DigestBuildButton />
            
            <div className="h-4 w-px bg-slate-200 mx-1" />

            <button
              onClick={() => setShowClearConfirm(true)}
              className="p-1.5 text-slate-400 hover:text-red-500 hover:bg-red-50 rounded-md transition-colors"
              title="清空重新生成"
            >
              <Trash2 className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* Content Area */}
        <div className="flex-1 relative overflow-auto bg-white transition-colors duration-500">
          {overviewLoading && (
            <div className="absolute inset-0 flex items-center justify-center text-sm text-slate-500 z-10">
              <Loader2 className="h-5 w-5 animate-spin mr-2" />
              正在加载知识结构...
            </div>
          )}

          {overviewIsError && (
            <div className="absolute inset-0 p-6">
              <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
                <AlertCircle className="mt-0.5 h-5 w-5 shrink-0" />
                <div>
                  <p className="font-semibold mb-1">加载失败</p>
                  <p>{getApiErrorMessage(overviewError, "获取知识概览时发生错误")}</p>
                </div>
              </div>
            </div>
          )}

          {!overviewLoading && !overviewIsError && (
            <div className="absolute inset-0">
              {activeTab === "theme-tree" && <ThemeTreeView overviewData={overview?.theme_tree ?? null} />}
              {activeTab === "prereq-dag" && (
                <PrereqDagView overviewDag={overview?.prereq_dag ?? null} overviewUnits={overview?.units ?? []} />
              )}
              {activeTab === "knowledge-graph" && (
                <KnowledgeGraphView subject={subjectId} overviewGraph={overview?.graph ?? null} />
              )}
            </div>
          )}
        </div>

        <Modal open={showClearConfirm} onClose={() => setShowClearConfirm(false)} title="确认清空知识数据">
          <div className="space-y-4">
            <div className="flex items-start gap-3 rounded-lg bg-red-50 p-3">
              <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-red-500" />
              <div className="text-sm text-red-700">
                <p>此操作会删除该学科下已经构建的知识数据，包括：</p>
                <ul className="mt-2 list-inside list-disc space-y-1 text-red-600">
                  <li>知识图谱节点、边和证据</li>
                  <li>教学单元、主题树和先修图</li>
                  <li>课程快照等派生知识结构</li>
                </ul>
                <p className="mt-2 font-medium">已经生成的文档也将因结构变更而失效。</p>
              </div>
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <Button variant="outline" onClick={() => setShowClearConfirm(false)}>
                取消
              </Button>
              <Button
                onClick={() => clearMutation.mutate()}
                disabled={clearMutation.isPending}
                className="bg-red-500 text-white hover:bg-red-600"
              >
                {clearMutation.isPending ? (
                  <>
                    <Loader2 className="mr-1 h-4 w-4 animate-spin" />
                    清空中...
                  </>
                ) : (
                  <>
                    <Trash2 className="mr-1 h-4 w-4" />
                    确认清空
                  </>
                )}
              </Button>
            </div>
          </div>
        </Modal>
      </div>
    </DigestBuildProvider>
  );
}
