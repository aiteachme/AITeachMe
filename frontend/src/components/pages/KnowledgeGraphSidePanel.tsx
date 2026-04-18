import { lazy, Suspense, useMemo, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  AlertTriangle,
  Loader2,
  Network,
  Orbit,
  Trash2,
} from "lucide-react";

import { knowledgeClearApiV1SubjectsSubjectKnowledgeClearPost } from "../../api/generated/knowledge";
import { getApiErrorMessage } from "../../api/client";
import {
  OVERVIEW_INCLUDE_PRESETS,
  buildKnowledgeOverviewQueryKey,
  fetchKnowledgeOverview,
} from "../../lib/knowledgeOverview";
import { DigestBuildProgress } from "./DigestBuildPanel";
import { GraphBuildButton } from "./GraphBuildButton";
import { SubjectVectorNotice } from "./SubjectVectorNotice";
import { Button } from "../ui/Button";
import { Modal } from "../ui/Modal";

const SemanticUniverse = lazy(() =>
  import("./SemanticUniverse").then((module) => ({ default: module.SemanticUniverse })),
);
const KnowledgeGraphView = lazy(() =>
  import("./KnowledgeGraphView").then((module) => ({ default: module.KnowledgeGraphView })),
);

type KnowledgeViewTab = "semantic-universe" | "knowledge-graph";

const VIEW_TABS: Array<{
  id: KnowledgeViewTab;
  label: string;
  icon: ReactNode;
  desc: string;
}> = [
  {
    id: "semantic-universe",
    label: "语义宇宙",
    icon: <Orbit className="h-4 w-4" />,
    desc: "稳定的语义星图。",
  },
  {
    id: "knowledge-graph",
    label: "知识图谱",
    icon: <Network className="h-4 w-4" />,
    desc: "底层节点与关系图谱。",
  },
];

function TabFallback({ message }: { message: string }) {
  return (
    <div className="flex h-[360px] items-center justify-center rounded-2xl border border-slate-200 bg-white text-sm text-slate-500">
      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
      {message}
    </div>
  );
}

export function KnowledgeGraphSidePanel({
  subjectId,
}: {
  subjectId: string;
}) {
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState<KnowledgeViewTab>("semantic-universe");
  const [showClearConfirm, setShowClearConfirm] = useState(false);

  const overviewInclude = useMemo(() => OVERVIEW_INCLUDE_PRESETS.wordCloud, []);

  const {
    data: overview,
    isLoading: overviewLoading,
    isError: overviewIsError,
    error: overviewError,
  } = useQuery({
    queryKey: buildKnowledgeOverviewQueryKey(subjectId, overviewInclude),
    queryFn: () => fetchKnowledgeOverview(subjectId, overviewInclude),
    enabled: Boolean(subjectId),
    retry: false,
  });

  const clearMutation = useMutation({
    mutationFn: () => knowledgeClearApiV1SubjectsSubjectKnowledgeClearPost(subjectId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["knowledge-overview", subjectId] });
      queryClient.invalidateQueries({ queryKey: ["graph-node-detail", subjectId] });
      queryClient.invalidateQueries({ queryKey: ["docgen-content", subjectId] });
      queryClient.invalidateQueries({ queryKey: ["knowledge-doc-build", subjectId] });
      setShowClearConfirm(false);
    },
  });

  const subjectLabel = useMemo(() => {
    if (/^subj_[a-z0-9]+$/i.test(subjectId)) {
      return "知识宇宙";
    }
    return subjectId || "知识宇宙";
  }, [subjectId]);

  return (
    <div className="flex h-full w-full flex-col bg-white">
      <div className="flex items-center justify-between gap-3 border-b border-slate-200 bg-white px-3 py-2">
          <div className="flex items-center gap-1 rounded-lg bg-slate-100 p-1">
            {VIEW_TABS.map((tab) => (
              <button
                key={tab.id}
                type="button"
                onClick={() => setActiveTab(tab.id)}
                className={`flex items-center justify-center gap-1.5 rounded-md px-3 py-1.5 text-[13px] font-medium transition-all ${
                  activeTab === tab.id
                    ? "bg-white text-slate-900 shadow-sm ring-1 ring-slate-200/70"
                    : "text-slate-500 hover:text-slate-800"
                }`}
                title={tab.desc}
              >
                {tab.icon}
                <span className="hidden lg:inline">{tab.label}</span>
              </button>
            ))}
          </div>

          <div className="flex items-center gap-1.5">
            <GraphBuildButton subject={subjectId} />
            <div className="mx-1 h-4 w-px bg-slate-200" />
            <button
              type="button"
              onClick={() => setShowClearConfirm(true)}
              className="rounded-md p-1.5 text-slate-400 transition-colors hover:bg-rose-50 hover:text-rose-500"
              title="清空当前学科知识结构"
            >
              <Trash2 className="h-4 w-4" />
            </button>
          </div>
        </div>

      <div className="grid gap-3 border-b border-slate-200 bg-slate-50/70 p-3">
          <DigestBuildProgress subject={subjectId} compact />
          <SubjectVectorNotice status={overview?.vector_status} />
        </div>

      <div className="flex-1 overflow-auto bg-white p-3">
          {overviewLoading ? (
            <div className="flex min-h-full items-center justify-center px-6 py-10 text-sm text-slate-500">
              <Loader2 className="mr-2 h-5 w-5 animate-spin" />
              正在加载知识结构...
            </div>
          ) : null}

          {overviewIsError ? (
            <div className="rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">
              <div className="flex items-start gap-2">
                <AlertCircle className="mt-0.5 h-5 w-5 shrink-0" />
                <div>
                  <p className="mb-1 font-semibold">加载失败</p>
                  <p>{getApiErrorMessage(overviewError, "获取知识概览时发生错误。")}</p>
                </div>
              </div>
            </div>
          ) : null}

          {!overviewLoading && !overviewIsError ? (
            <>
              {activeTab === "semantic-universe" ? (
                <Suspense fallback={<TabFallback message="正在加载语义宇宙..." />}>
                  <SemanticUniverse
                    subjectLabel={subjectLabel}
                    overviewGraph={overview?.graph ?? null}
                    height="calc(100vh - 20rem)"
                  />
                </Suspense>
              ) : null}

              {activeTab === "knowledge-graph" ? (
                <Suspense fallback={<TabFallback message="正在加载知识图谱..." />}>
                  <KnowledgeGraphView subject={subjectId} overviewGraph={overview?.graph ?? null} />
                </Suspense>
              ) : null}
            </>
          ) : null}
        </div>

      <Modal open={showClearConfirm} onClose={() => setShowClearConfirm(false)} title="确认清空知识数据">
          <div className="space-y-4">
            <div className="flex items-start gap-3 rounded-lg bg-rose-50 p-3">
              <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-rose-500" />
              <div className="text-sm text-rose-700">
                <p>这会删除当前学科已发布的知识文档和知识图谱相关结构。</p>
                <p className="mt-2 font-medium">原始上传文件不会被删除。</p>
              </div>
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <Button variant="outline" onClick={() => setShowClearConfirm(false)}>
                取消
              </Button>
              <Button
                onClick={() => clearMutation.mutate()}
                disabled={clearMutation.isPending}
                className="bg-rose-500 text-white hover:bg-rose-600"
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
  );
}
