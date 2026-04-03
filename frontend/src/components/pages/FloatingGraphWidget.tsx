import { lazy, Suspense, useMemo, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  AlertTriangle,
  FolderTree,
  GitBranch,
  Loader2,
  Map,
  Maximize2,
  Minimize2,
  Network,
  Orbit,
  Trash2,
} from "lucide-react";
import { AnimatePresence, motion } from "framer-motion";

import { knowledgeClearApiV1SubjectsSubjectKnowledgeClearPost } from "../../api/generated/knowledge";
import { getApiErrorMessage } from "../../api/client";
import {
  OVERVIEW_INCLUDE_PRESETS,
  buildKnowledgeOverviewQueryKey,
  fetchKnowledgeOverview,
} from "../../lib/knowledgeOverview";
import {
  DigestBuildButton,
  DigestBuildProgress,
  DigestBuildProvider,
} from "./DigestBuildPanel";
import { StudyPlanPanel } from "./StudyPlanPanel";
import { Button } from "../ui/Button";
import { Modal } from "../ui/Modal";

const SemanticUniverse = lazy(() =>
  import("./SemanticUniverse").then((module) => ({ default: module.SemanticUniverse })),
);
const ThemeTreeView = lazy(() =>
  import("./ThemeTreeView").then((module) => ({ default: module.ThemeTreeView })),
);
const PrereqDagView = lazy(() =>
  import("./PrereqDagView").then((module) => ({ default: module.PrereqDagView })),
);
const KnowledgeGraphView = lazy(() =>
  import("./KnowledgeGraphView").then((module) => ({ default: module.KnowledgeGraphView })),
);

type KnowledgeViewTab = "semantic-universe" | "theme-tree" | "prereq-dag" | "knowledge-graph";

const VIEW_TABS: Array<{ id: KnowledgeViewTab; label: string; icon: ReactNode }> = [
  { id: "semantic-universe", label: "知识宇宙", icon: <Orbit className="h-4 w-4" /> },
  { id: "theme-tree", label: "主题树", icon: <FolderTree className="h-4 w-4" /> },
  { id: "prereq-dag", label: "先修图", icon: <GitBranch className="h-4 w-4" /> },
  { id: "knowledge-graph", label: "专家图谱", icon: <Network className="h-4 w-4" /> },
];

function PanelFallback({ message }: { message: string }) {
  return (
    <div className="flex h-[320px] items-center justify-center rounded-2xl border border-slate-200 bg-white text-sm text-slate-500">
      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
      {message}
    </div>
  );
}

export function FloatingGraphWidget({ subjectId }: { subjectId: string }) {
  const queryClient = useQueryClient();
  const [isOpen, setIsOpen] = useState(false);
  const [isMaximized, setIsMaximized] = useState(false);
  const [activeTab, setActiveTab] = useState<KnowledgeViewTab>("semantic-universe");
  const [showClearConfirm, setShowClearConfirm] = useState(false);

  const overviewInclude = useMemo(() => {
    switch (activeTab) {
      case "theme-tree":
        return OVERVIEW_INCLUDE_PRESETS.themeTree;
      case "prereq-dag":
        return OVERVIEW_INCLUDE_PRESETS.prereqDag;
      case "knowledge-graph":
      case "semantic-universe":
      default:
        return OVERVIEW_INCLUDE_PRESETS.wordCloud;
    }
  }, [activeTab]);

  const {
    data: overview,
    isLoading: overviewLoading,
    isError: overviewIsError,
    error: overviewError,
  } = useQuery({
    queryKey: buildKnowledgeOverviewQueryKey(subjectId, overviewInclude),
    queryFn: () => fetchKnowledgeOverview(subjectId, overviewInclude),
    enabled: Boolean(subjectId) && isOpen,
    retry: false,
  });

  const clearMutation = useMutation({
    mutationFn: () => knowledgeClearApiV1SubjectsSubjectKnowledgeClearPost(subjectId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["knowledge-overview", subjectId] });
      queryClient.invalidateQueries({ queryKey: ["graph-node-detail", subjectId] });
      queryClient.invalidateQueries({ queryKey: ["docgen-content", subjectId] });
      queryClient.invalidateQueries({ queryKey: ["knowledge-doc-build", subjectId] });
      queryClient.invalidateQueries({ queryKey: ["study-plan", subjectId] });
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
    <DigestBuildProvider subject={subjectId}>
      <AnimatePresence>
        {!isOpen ? (
          <motion.div
            initial={{ opacity: 0, scale: 0.84, y: 24 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.84, y: 24 }}
            transition={{ type: "spring", stiffness: 260, damping: 20 }}
            className="fixed bottom-6 right-8 z-[60]"
          >
            <button
              type="button"
              onClick={() => setIsOpen(true)}
              className="group flex h-14 items-center gap-3 overflow-hidden rounded-full border border-blue-200 bg-white/85 pl-4 pr-2.5 shadow-[0_8px_30px_rgb(0,0,0,0.12)] backdrop-blur-xl transition-all hover:border-blue-300 hover:bg-white hover:shadow-[0_8px_30px_rgb(59,130,246,0.2)]"
            >
              <div className="flex flex-col items-start pr-2">
                <span className="text-sm font-semibold text-slate-800">学习导航</span>
                <span className="text-[10px] font-medium text-slate-500">查看图谱、计划和依赖关系</span>
              </div>
              <div className="flex h-10 w-10 items-center justify-center rounded-full bg-blue-50 text-blue-600 transition-colors group-hover:bg-blue-100 group-hover:text-blue-700">
                <Map className="h-5 w-5" />
              </div>
            </button>
          </motion.div>
        ) : null}
      </AnimatePresence>

      <AnimatePresence>
        {isOpen ? (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.18 }}
            className="fixed inset-0 z-[70] flex items-end justify-center bg-slate-900/15 backdrop-blur-sm sm:items-center sm:p-6"
            onClick={(event) => {
              if (event.target === event.currentTarget) {
                setIsOpen(false);
              }
            }}
          >
            <motion.div
              initial={{ y: "100%", opacity: 0.6, scale: 0.96 }}
              animate={{ y: 0, opacity: 1, scale: 1 }}
              exit={{ y: "100%", opacity: 0, scale: 0.96 }}
              transition={{ type: "spring", damping: 26, stiffness: 300 }}
              className={`relative flex w-full flex-col overflow-hidden border border-slate-200 bg-white shadow-2xl ${
                isMaximized ? "h-[90vh] sm:h-[92vh] sm:w-[95vw]" : "h-[85vh] sm:h-[760px] sm:w-[980px]"
              } rounded-t-3xl sm:rounded-2xl`}
            >
              <div className="flex items-center justify-between border-b border-slate-100 bg-slate-50/85 px-4 py-3 backdrop-blur-md sm:px-6 sm:py-4">
                <div>
                  <h2 className="flex items-center gap-2 text-base font-bold text-slate-900 sm:text-lg">
                    <Map className="h-5 w-5 text-blue-500" />
                    知识图谱导航
                  </h2>
                  <p className="mt-1 text-xs text-slate-500">把构建进度、学习计划和知识结构放在同一个工作区里。</p>
                </div>

                <div className="flex items-center gap-2">
                  <div className="hidden sm:block">
                    <DigestBuildButton />
                  </div>
                  <button
                    type="button"
                    onClick={() => setShowClearConfirm(true)}
                    className="rounded-md p-1.5 text-slate-400 transition-colors hover:bg-rose-50 hover:text-rose-500"
                    title="清空知识结构"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                  <div className="mx-1 hidden h-4 w-px bg-slate-200 sm:block" />
                  <button
                    type="button"
                    onClick={() => setIsMaximized((value) => !value)}
                    className="hidden rounded-md p-1.5 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700 sm:flex"
                    title={isMaximized ? "还原尺寸" : "最大化"}
                  >
                    {isMaximized ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
                  </button>
                  <button
                    type="button"
                    onClick={() => setIsOpen(false)}
                    className="rounded-md bg-slate-100 px-3 py-1.5 text-sm font-medium text-slate-600 transition-colors hover:bg-slate-200 hover:text-slate-900"
                  >
                    收起
                  </button>
                </div>
              </div>

              <div className="border-b border-slate-200 bg-slate-50/70 p-4">
                <div className="grid gap-3 xl:grid-cols-[1.1fr_0.9fr]">
                  <DigestBuildProgress compact />
                  <StudyPlanPanel subject={subjectId} compact />
                </div>
              </div>

              <div className="border-b border-slate-100 bg-white px-4 py-3 sm:px-6">
                <div className="flex gap-1 rounded-xl bg-slate-100 p-1">
                  {VIEW_TABS.map((tab) => (
                    <button
                      key={tab.id}
                      type="button"
                      onClick={() => setActiveTab(tab.id)}
                      className={`flex flex-1 items-center justify-center gap-2 rounded-lg px-3 py-2.5 text-[13px] font-medium transition-all ${
                        activeTab === tab.id
                          ? "bg-slate-900 text-white shadow-md shadow-slate-900/10"
                          : "text-slate-600 hover:bg-slate-200/70 hover:text-slate-900"
                      }`}
                    >
                      {tab.icon}
                      <span>{tab.label}</span>
                    </button>
                  ))}
                </div>
              </div>

              <div className="relative flex-1 overflow-auto bg-slate-50/50 p-4 sm:p-6">
                {overviewLoading ? (
                  <div className="absolute inset-0 flex items-center justify-center bg-white/80 text-sm text-slate-500">
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
                      <Suspense fallback={<PanelFallback message="正在加载知识宇宙..." />}>
                        <SemanticUniverse
                          subjectLabel={subjectLabel}
                          overviewGraph={overview?.graph ?? null}
                          height="calc(100vh - 22rem)"
                        />
                      </Suspense>
                    ) : null}

                    {activeTab === "theme-tree" ? (
                      <Suspense fallback={<PanelFallback message="正在加载主题树..." />}>
                        <ThemeTreeView overviewData={overview?.theme_tree ?? null} />
                      </Suspense>
                    ) : null}

                    {activeTab === "prereq-dag" ? (
                      <Suspense fallback={<PanelFallback message="正在加载先修图..." />}>
                        <PrereqDagView overviewDag={overview?.prereq_dag ?? null} overviewUnits={overview?.units ?? []} />
                      </Suspense>
                    ) : null}

                    {activeTab === "knowledge-graph" ? (
                      <Suspense fallback={<PanelFallback message="正在加载知识图谱..." />}>
                        <KnowledgeGraphView subject={subjectId} overviewGraph={overview?.graph ?? null} />
                      </Suspense>
                    ) : null}
                  </>
                ) : null}
              </div>
            </motion.div>
          </motion.div>
        ) : null}
      </AnimatePresence>

      <Modal open={showClearConfirm} onClose={() => setShowClearConfirm(false)} title="确认清空知识数据">
        <div className="space-y-4">
          <div className="flex items-start gap-3 rounded-lg bg-rose-50 p-3">
            <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-rose-500" />
            <div className="text-sm text-rose-700">
              <p>这会删除当前学科已经发布的知识图谱、教学单元、主题树、先修图以及相关快照。</p>
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
    </DigestBuildProvider>
  );
}
