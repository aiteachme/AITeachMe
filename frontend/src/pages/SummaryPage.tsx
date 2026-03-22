import { useState } from "react";
import { useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  FolderTree,
  GitBranch,
  Network,
  Trash2,
  Loader2,
  AlertTriangle,
  AlertCircle,
} from "lucide-react";
import { Button } from "../components/ui/Button";
import { Modal } from "../components/ui/Modal";
import { ThemeTreeView } from "../components/pages/ThemeTreeView";
import { PrereqDagView } from "../components/pages/PrereqDagView";
import { KnowledgeGraphView } from "../components/pages/KnowledgeGraphView";
import { DigestBuildProvider, DigestBuildButton } from "../components/pages/DigestBuildPanel";
import { knowledgeClearApiV1SubjectsSubjectKnowledgeClearPost } from "../api/generated/knowledge";
import { fetchKnowledgeOverview } from "../api/knowledgeOverview";
import { getApiErrorMessage } from "../api/client";

type KnowledgeViewTab = "theme-tree" | "prereq-dag" | "knowledge-graph";

const VIEW_TABS: { id: KnowledgeViewTab; label: string; icon: React.ReactNode; desc: string }[] = [
  { id: "theme-tree", label: "主题树", icon: <FolderTree className="w-4 h-4" />, desc: "层次化主题结构" },
  { id: "prereq-dag", label: "先修图", icon: <GitBranch className="w-4 h-4" />, desc: "学习路径依赖" },
  { id: "knowledge-graph", label: "知识图谱", icon: <Network className="w-4 h-4" />, desc: "底层知识节点" },
];

export function SummaryPage() {
  const { subjectId = "" } = useParams();
  const queryClient = useQueryClient();

  const [activeTab, setActiveTab] = useState<KnowledgeViewTab>("theme-tree");
  const [showClearConfirm, setShowClearConfirm] = useState(false);

  const {
    data: overview,
    isLoading: overviewLoading,
    isError: overviewIsError,
    error: overviewError,
  } = useQuery({
    queryKey: ["knowledge-overview", subjectId],
    queryFn: () => fetchKnowledgeOverview(subjectId),
    enabled: !!subjectId,
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
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold text-slate-900">知识总结</h1>
            <p className="text-slate-500 mt-2">AI 生成的知识点总结和思维导图</p>
          </div>
          <div className="flex items-center gap-2">
            <DigestBuildButton />
            <Button
              variant="outline"
              size="sm"
              onClick={() => setShowClearConfirm(true)}
              className="text-red-500 hover:text-red-600 hover:bg-red-50"
            >
              <Trash2 className="w-4 h-4 mr-1" />清空知识
            </Button>
          </div>
        </div>

        {overviewLoading && (
          <div className="flex items-center gap-2 text-sm text-slate-500">
            <Loader2 className="w-4 h-4 animate-spin" />正在加载知识概览...
          </div>
        )}

        {overviewIsError && (
          <div className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-amber-700 text-sm">
            <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
            {getApiErrorMessage(overviewError, "知识概览加载失败")}
          </div>
        )}

        <div className="flex gap-1 p-1 bg-slate-100 rounded-xl">
          {VIEW_TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm transition-all flex-1 justify-center ${
                activeTab === tab.id
                  ? "bg-white text-slate-900 shadow-sm font-medium"
                  : "text-slate-500 hover:text-slate-700"
              }`}
            >
              {tab.icon}
              <span>{tab.label}</span>
            </button>
          ))}
        </div>

        {activeTab === "theme-tree" && (
          <ThemeTreeView overviewData={overview?.theme_tree ?? null} />
        )}

        {activeTab === "prereq-dag" && (
          <PrereqDagView
            overviewDag={overview?.prereq_dag ?? null}
            overviewUnits={overview?.units ?? []}
          />
        )}

        {activeTab === "knowledge-graph" && (
          <KnowledgeGraphView subject={subjectId} overviewGraph={overview?.graph ?? null} />
        )}

        <Modal open={showClearConfirm} onClose={() => setShowClearConfirm(false)} title="确认清空知识数据">
          <div className="space-y-4">
            <div className="flex items-start gap-3 p-3 bg-red-50 rounded-lg">
              <AlertTriangle className="w-5 h-5 text-red-500 shrink-0 mt-0.5" />
              <div className="text-sm text-red-700">
                <p>此操作将清空该学科的所有知识数据，包括：</p>
                <ul className="list-disc list-inside mt-2 space-y-1 text-red-600">
                  <li>知识图谱（节点、边、证据）</li>
                  <li>教学单元及修订</li>
                  <li>主题树、先修图、课程快照</li>
                  <li>构建任务记录</li>
                </ul>
                <p className="mt-2 font-medium">此操作不可撤销，已上传的文件不受影响。</p>
              </div>
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <Button variant="outline" onClick={() => setShowClearConfirm(false)}>
                取消
              </Button>
              <Button
                onClick={() => clearMutation.mutate()}
                disabled={clearMutation.isPending}
                className="bg-red-500 hover:bg-red-600 text-white"
              >
                {clearMutation.isPending ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin mr-1" />清空中...
                  </>
                ) : (
                  <>
                    <Trash2 className="w-4 h-4 mr-1" />确认清空
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
