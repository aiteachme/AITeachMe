import { useState } from "react";
import { useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  AlertTriangle,
  FolderTree,
  GitBranch,
  Loader2,
  Network,
  Trash2,
} from "lucide-react";

import { knowledgeClearApiV1SubjectsSubjectKnowledgeClearPost } from "../api/generated/knowledge";
import { fetchKnowledgeOverview } from "../api/knowledgeOverview";
import { getApiErrorMessage } from "../api/client";
import { DigestBuildButton, DigestBuildProvider } from "../components/pages/DigestBuildPanel";
import { KnowledgeGraphView } from "../components/pages/KnowledgeGraphView";
import { PrereqDagView } from "../components/pages/PrereqDagView";
import { ThemeTreeView } from "../components/pages/ThemeTreeView";
import { Button } from "../components/ui/Button";
import { Modal } from "../components/ui/Modal";

type KnowledgeViewTab = "theme-tree" | "prereq-dag" | "knowledge-graph";

const VIEW_TABS: { id: KnowledgeViewTab; label: string; icon: React.ReactNode; desc: string }[] = [
  { id: "theme-tree", label: "主题树", icon: <FolderTree className="h-4 w-4" />, desc: "按章节与主题组织的课程结构" },
  { id: "prereq-dag", label: "先修图", icon: <GitBranch className="h-4 w-4" />, desc: "展示学习顺序和依赖关系" },
  { id: "knowledge-graph", label: "知识图谱", icon: <Network className="h-4 w-4" />, desc: "展示底层知识节点与连接关系" },
];

export function KnowledgeGraphPage() {
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
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold text-slate-900">知识图谱</h1>
            <p className="mt-2 text-slate-500">这里展示主题树、先修依赖和知识图谱视图。点击开始知识构建会同时刷新知识文档与图谱。</p>
          </div>
          <div className="flex items-center gap-2">
            <DigestBuildButton />
            <Button
              variant="outline"
              size="sm"
              onClick={() => setShowClearConfirm(true)}
              className="text-red-500 hover:bg-red-50 hover:text-red-600"
            >
              <Trash2 className="mr-1 h-4 w-4" />
              清空知识
            </Button>
          </div>
        </div>

        {overviewLoading ? (
          <div className="flex items-center gap-2 text-sm text-slate-500">
            <Loader2 className="h-4 w-4 animate-spin" />
            正在加载知识概览...
          </div>
        ) : null}

        {overviewIsError ? (
          <div className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-700">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            {getApiErrorMessage(overviewError, "知识概览加载失败")}
          </div>
        ) : null}

        <div className="flex gap-1 rounded-xl bg-slate-100 p-1">
          {VIEW_TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex flex-1 items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm transition-all ${
                activeTab === tab.id
                  ? "bg-white font-medium text-slate-900 shadow-sm"
                  : "text-slate-500 hover:text-slate-700"
              }`}
              title={tab.desc}
            >
              {tab.icon}
              <span>{tab.label}</span>
            </button>
          ))}
        </div>

        {activeTab === "theme-tree" ? <ThemeTreeView overviewData={overview?.theme_tree ?? null} /> : null}

        {activeTab === "prereq-dag" ? (
          <PrereqDagView overviewDag={overview?.prereq_dag ?? null} overviewUnits={overview?.units ?? []} />
        ) : null}

        {activeTab === "knowledge-graph" ? (
          <KnowledgeGraphView subject={subjectId} overviewGraph={overview?.graph ?? null} />
        ) : null}

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
                <p className="mt-2 font-medium">已上传的原始文件不会被删除。</p>
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
