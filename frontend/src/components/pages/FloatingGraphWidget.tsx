import { useState, useRef } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  AlertTriangle,
  FolderTree,
  GitBranch,
  Loader2,
  Network,
  Trash2,
  Minimize2,
  Maximize2,
  Map
} from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";

import {
  knowledgeClearApiV1SubjectsSubjectKnowledgeClearPost,
} from "../../api/generated/knowledge";
import { getApiErrorMessage } from "../../api/client";
import { buildKnowledgeOverviewQueryKey, fetchKnowledgeOverview, OVERVIEW_INCLUDE_PRESETS } from "../../lib/knowledgeOverview";

import { DigestBuildButton, DigestBuildProvider } from "./DigestBuildPanel";
import { KnowledgeGraphView } from "./KnowledgeGraphView";
import { PrereqDagView } from "./PrereqDagView";
import { ThemeTreeView } from "./ThemeTreeView";
import { Modal } from "../ui/Modal";
import { Button } from "../ui/Button";

type KnowledgeViewTab = "theme-tree" | "prereq-dag" | "knowledge-graph";

const VIEW_TABS: { id: KnowledgeViewTab; label: string; icon: React.ReactNode; desc: string }[] = [
  { id: "theme-tree", label: "主题树", icon: <FolderTree className="h-4 w-4" />, desc: "按章节与主题组织的课程结构" },
  { id: "prereq-dag", label: "先修图", icon: <GitBranch className="h-4 w-4" />, desc: "展示学习顺序和依赖关系" },
  { id: "knowledge-graph", label: "知识图谱", icon: <Network className="h-4 w-4" />, desc: "展示底层知识节点与连接关系" },
];

export function FloatingGraphWidget({ subjectId }: { subjectId: string }) {
  const queryClient = useQueryClient();
  const [isOpen, setIsOpen] = useState(false);
  const [isMaximized, setIsMaximized] = useState(false);
  const [activeTab, setActiveTab] = useState<KnowledgeViewTab>("theme-tree");
  const [showClearConfirm, setShowClearConfirm] = useState(false);
  const overviewInclude = activeTab === "theme-tree"
    ? OVERVIEW_INCLUDE_PRESETS.themeTree
    : activeTab === "prereq-dag"
      ? OVERVIEW_INCLUDE_PRESETS.prereqDag
      : OVERVIEW_INCLUDE_PRESETS.knowledgeGraph;
  
  // Ref for click outside to close (optional, if we want it to behave like a popover)
  const widgetRef = useRef<HTMLDivElement>(null);

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
      setShowClearConfirm(false);
    },
  });

  return (
    <DigestBuildProvider subject={subjectId}>
      {/* Floating Action Button */}
      <AnimatePresence>
        {!isOpen && (
          <motion.div
            initial={{ opacity: 0, scale: 0.8, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.8, y: 20 }}
            transition={{ type: "spring", stiffness: 260, damping: 20 }}
            className="fixed bottom-6 right-8 z-[60]"
          >
            <button
              onClick={() => setIsOpen(true)}
              className="group flex h-14 items-center gap-3 overflow-hidden rounded-full border border-blue-200 bg-white/80 pl-4 pr-2.5 shadow-[0_8px_30px_rgb(0,0,0,0.12)] backdrop-blur-xl transition-all hover:border-blue-300 hover:bg-white hover:shadow-[0_8px_30px_rgb(59,130,246,0.2)]"
            >
              <div className="flex flex-col items-start pr-2">
                <span className="text-sm font-semibold text-slate-800">学习向导</span>
                <span className="text-[10px] text-slate-500 font-medium">查看知识图谱与结构</span>
              </div>
              <div className="flex h-10 w-10 items-center justify-center rounded-full bg-blue-50 text-blue-600 transition-colors group-hover:bg-blue-100 group-hover:text-blue-700">
                <Map className="h-5 w-5" />
              </div>
            </button>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Expanded Widget */}
      <AnimatePresence>
        {isOpen && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="fixed inset-0 z-[70] bg-slate-900/10 backdrop-blur-sm pointer-events-auto flex items-end sm:items-center justify-center sm:p-6"
            onClick={(e) => {
              if (e.target === e.currentTarget) setIsOpen(false);
            }}
          >
            <motion.div
              ref={widgetRef}
              initial={{ y: "100%", opacity: 0.5, scale: 0.95 }}
              animate={{ y: 0, opacity: 1, scale: 1 }}
              exit={{ y: "100%", opacity: 0, scale: 0.95 }}
              transition={{ type: "spring", damping: 25, stiffness: 300 }}
              className={`
                relative flex flex-col bg-white shadow-2xl overflow-hidden
                w-full border border-slate-200 
                rounded-t-3xl sm:rounded-2xl
                ${isMaximized ? "sm:h-[90vh] sm:w-[95vw]" : "sm:h-[650px] sm:w-[800px] sm:max-w-full"}
                ${isMaximized ? "h-[90vh]" : "h-[85vh]"}
              `}
              style={{
                boxShadow: "0 25px 50px -12px rgba(15, 23, 42, 0.25)",
              }}
            >
              {/* Header */}
              <div className="flex items-center justify-between border-b border-slate-100 bg-slate-50/80 px-4 py-3 sm:px-6 sm:py-4 backdrop-blur-md">
                <div>
                  <h2 className="text-base sm:text-lg font-bold text-slate-900 flex items-center gap-2">
                    <Map className="h-5 w-5 text-blue-500" />
                    知识图谱导航
                  </h2>
                </div>
                
                <div className="flex items-center gap-2">
                  <div className="hidden sm:block">
                    <DigestBuildButton />
                  </div>
                  
                  <button
                    onClick={() => setShowClearConfirm(true)}
                    className="p-1.5 text-slate-400 hover:text-red-500 hover:bg-red-50 rounded-md transition-colors"
                    title="清空知识"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>

                  <div className="hidden sm:block h-4 w-px bg-slate-200 mx-1" />

                  <button
                    onClick={() => setIsMaximized(!isMaximized)}
                    className="hidden sm:flex p-1.5 text-slate-400 hover:text-slate-700 hover:bg-slate-200/50 rounded-md transition-colors"
                  >
                    {isMaximized ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
                  </button>
                  <button
                    onClick={() => setIsOpen(false)}
                    className="p-1.5 text-sm font-medium hover:bg-slate-200/50 text-slate-500 hover:text-slate-800 rounded-md transition-colors px-3 py-1 bg-slate-100"
                  >
                    收起
                  </button>
                </div>
              </div>

              {/* Tabs */}
              <div className="px-4 py-2 sm:px-6 sm:py-3 bg-white border-b border-slate-100 flex gap-1">
                {VIEW_TABS.map((tab) => (
                  <button
                    key={tab.id}
                    onClick={() => setActiveTab(tab.id)}
                    className={`flex flex-1 items-center justify-center gap-2 rounded-lg py-2.5 text-[13px] font-medium transition-all ${
                      activeTab === tab.id
                        ? "bg-slate-900 text-white shadow-md shadow-slate-900/10"
                        : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
                    }`}
                    title={tab.desc}
                  >
                    {tab.icon}
                    <span>{tab.label}</span>
                  </button>
                ))}
              </div>

              {/* Content Area */}
              <div className="flex-1 relative overflow-auto bg-slate-50/50">
                {overviewLoading && (
                  <div className="absolute inset-0 flex items-center justify-center text-sm text-slate-500 bg-white/80 z-10">
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
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

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
    </DigestBuildProvider>
  );
}
