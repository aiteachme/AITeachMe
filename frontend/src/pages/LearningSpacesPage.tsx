import { useState } from "react";
import type { ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { ArrowRight, BookOpen, Download, LayoutGrid, Loader2, PackagePlus, Plus, Upload } from "lucide-react";

import { listSubjectsApiApiV1SubjectsListPost } from "../api/generated/subjects";
import { SubjectExportModal } from "../components/subject/SubjectExportModal";
import { SubjectImportModal } from "../components/subject/SubjectImportModal";
import { unwrapOrvalResponse } from "../lib/unwrapOrvalResponse";
import { resolveSubjectIcon } from "../lib/subjectIcons";
import { cn } from "../lib/utils";

type SubjectWithIcon = {
  subject_id: string;
  name?: string | null;
  icon_key?: string | null;
};

function displaySubjectName(subject: { name?: string | null }) {
  return subject.name?.trim() || "未命名学科";
}

function subjectTone(name: string) {
  const tones = [
    "from-slate-900 to-slate-700",
    "from-emerald-600 to-teal-500",
    "from-rose-600 to-orange-500",
    "from-indigo-600 to-blue-500",
    "from-amber-500 to-orange-500",
    "from-cyan-600 to-sky-500",
  ];

  let hash = 0;
  for (let index = 0; index < name.length; index += 1) {
    hash = name.charCodeAt(index) + ((hash << 5) - hash);
  }

  return tones[Math.abs(hash) % tones.length];
}

function WorkspaceActionButton({
  children,
  icon,
  onClick,
  variant = "outline",
}: {
  children: ReactNode;
  icon: ReactNode;
  onClick: () => void;
  variant?: "primary" | "outline";
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "inline-flex min-h-11 items-center justify-center gap-2 rounded-xl px-4 text-sm font-medium transition active:scale-[0.98] focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-300 dark:focus-visible:ring-slate-700",
        variant === "primary"
          ? "bg-slate-900 text-white shadow-sm hover:bg-slate-800 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-white"
          : "border border-slate-200 bg-white text-slate-700 shadow-sm hover:border-slate-300 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:border-slate-600 dark:hover:bg-slate-800",
      )}
    >
      {icon}
      {children}
    </button>
  );
}

export function LearningSpacesPage() {
  const navigate = useNavigate();
  const [isImportModalOpen, setIsImportModalOpen] = useState(false);
  const [exportSubjectId, setExportSubjectId] = useState<string | null>(null);

  const { data: subjects = [], isLoading } = useQuery({
    queryKey: ["subjects"],
    queryFn: async () =>
      unwrapOrvalResponse(
        await listSubjectsApiApiV1SubjectsListPost({
          page: 1,
          size: 100,
        }),
      )?.items ?? [],
  });

  const subjectCount = subjects.length;
  return (
    <>
      <div className="min-h-full px-4 pb-12 pt-20 sm:px-6 md:px-10 lg:px-12 lg:pt-10 xl:px-16">
        <div className="mx-auto w-full max-w-[1560px]">
          <div className="flex flex-col gap-5 xl:flex-row xl:items-end xl:justify-between">
            <div className="max-w-3xl space-y-3">
              <div className="inline-flex items-center gap-2 rounded-full border border-slate-200/80 bg-white/70 px-3 py-1 text-xs font-medium text-slate-500 backdrop-blur dark:border-slate-700/80 dark:bg-slate-800/70 dark:text-slate-400">
                <LayoutGrid className="h-3.5 w-3.5" />
                学习空间
              </div>
              <div>
                <h1 className="text-3xl font-semibold text-slate-950 dark:text-slate-100 sm:text-[34px]">学习空间</h1>
                <p className="mt-2 text-sm leading-6 text-slate-500 dark:text-slate-400 sm:text-[15px]">
                  管理学科、资料和课程包迁移。每个学科都可以继续构建、查看知识库、导出备份。
                </p>
              </div>
            </div>

            <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap xl:justify-end">
              <WorkspaceActionButton
                variant="primary"
                icon={<Plus className="h-4 w-4" />}
                onClick={() => navigate("/", { state: { newEntryAt: Date.now() } })}
              >
                新建学科
              </WorkspaceActionButton>
              <WorkspaceActionButton
                icon={<Upload className="h-4 w-4" />}
                onClick={() => navigate("/library")}
              >
                上传资料
              </WorkspaceActionButton>
              <WorkspaceActionButton
                icon={<PackagePlus className="h-4 w-4" />}
                onClick={() => setIsImportModalOpen(true)}
              >
                导入课程包
              </WorkspaceActionButton>
            </div>
          </div>

          <div className="mt-8 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <h2 className="text-lg font-semibold text-slate-950 dark:text-slate-100">学科列表</h2>
              <p className="mt-1 text-sm leading-6 text-slate-500 dark:text-slate-400">
                {isLoading ? "正在加载学科..." : subjectCount > 0 ? `${subjectCount} 个学科可继续学习` : "还没有创建学科"}
              </p>
            </div>
          </div>

          {isLoading ? (
            <div className="mt-12 flex min-h-[180px] items-center justify-center">
              <div className="flex items-center gap-2 text-sm text-slate-500 dark:text-slate-400">
                <Loader2 className="h-4 w-4 animate-spin" />
                正在加载学习空间...
              </div>
            </div>
          ) : null}

          {!isLoading && subjects.length === 0 ? (
            <div className="mt-14 flex min-h-[180px] flex-col items-center justify-center px-6 text-center">
              <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-slate-100/80 text-slate-500 dark:bg-slate-800/80 dark:text-slate-400">
                <LayoutGrid className="h-5 w-5" />
              </div>
              <h2 className="mt-4 text-lg font-semibold text-slate-900 dark:text-slate-100">还没有学习空间</h2>
              <p className="mt-2 max-w-md text-sm leading-6 text-slate-500 dark:text-slate-400">
                可以新建一个空学科，也可以直接导入别人分享的 .atmx 课程包。
              </p>
              <div className="mt-6 flex flex-col gap-2 sm:flex-row">
                <WorkspaceActionButton
                  variant="primary"
                  icon={<Plus className="h-4 w-4" />}
                  onClick={() => navigate("/", { state: { newEntryAt: Date.now() } })}
                >
                  新建学科
                </WorkspaceActionButton>
              </div>
            </div>
          ) : null}

          {!isLoading && subjects.length > 0 ? (
            <div className="mt-5 grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
              {subjects.map((subject: SubjectWithIcon, index: number) => {
                const displayName = displaySubjectName(subject);
                const SubjectIcon = resolveSubjectIcon(subject.icon_key);

                return (
                  <motion.div
                    key={subject.subject_id}
                    className="group flex min-h-[232px] flex-col overflow-hidden rounded-2xl border border-slate-200/80 bg-white/90 shadow-sm transition duration-200 hover:border-slate-300 hover:shadow-[0_18px_42px_rgba(15,23,42,0.08)] dark:border-slate-800/80 dark:bg-slate-900/90 dark:hover:border-slate-700 dark:hover:shadow-[0_18px_42px_rgba(0,0,0,0.24)]"
                    initial={{ opacity: 0, scale: 0.97, y: 10 }}
                    animate={{ opacity: 1, scale: 1, y: 0 }}
                    transition={{
                      delay: Math.min(index * 0.035, 0.22),
                      duration: 0.24,
                      ease: "easeOut",
                    }}
                    whileHover={{ y: -3 }}
                    whileTap={{ scale: 0.99 }}
                  >
                    <div className="flex items-start gap-3 px-4 pb-4 pt-4">
                      <div className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br ${subjectTone(displayName)} text-white shadow-sm`}>
                        <SubjectIcon className="h-5 w-5" strokeWidth={2.1} />
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-start justify-between gap-2">
                          <h3 className="line-clamp-2 text-base font-semibold leading-6 text-slate-950 dark:text-slate-100">
                            {displayName}
                          </h3>
                          <span className="shrink-0 rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-500 dark:bg-slate-800 dark:text-slate-400">
                            学科
                          </span>
                        </div>
                        <p className="mt-1.5 line-clamp-2 text-sm leading-6 text-slate-500 dark:text-slate-400">
                          整理资料、生成知识文档、练习考试并查看画像。
                        </p>
                      </div>
                    </div>

                    <div className="flex flex-1 flex-col px-4 pb-4">
                      <div className="grid grid-cols-3 gap-2">
                        {[
                          { label: "构建", path: "build" },
                          { label: "知识库", path: "knowledge-docs" },
                          { label: "画像", path: "profile" },
                        ].map((item) => (
                          <Link
                            key={item.path}
                            to={`/subject/${subject.subject_id}/${item.path}`}
                            className="rounded-lg bg-slate-50 px-2 py-2 text-center text-xs font-medium text-slate-600 transition hover:bg-slate-100 hover:text-slate-900 dark:bg-slate-800/70 dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-slate-100"
                          >
                            {item.label}
                          </Link>
                        ))}
                      </div>

                      <div className="mt-auto grid grid-cols-2 gap-2 border-t border-slate-100 pt-3 dark:border-slate-800">
                        <Link
                          to={`/subject/${subject.subject_id}/build`}
                          className="col-span-2 inline-flex min-h-10 items-center justify-center gap-2 whitespace-nowrap rounded-xl bg-slate-900 px-3 text-sm font-medium text-white transition hover:bg-slate-800 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-white"
                        >
                          <BookOpen className="h-4 w-4" />
                          进入学习
                          <ArrowRight className="h-4 w-4" />
                        </Link>
                        <Link
                          to={`/subject/${subject.subject_id}/build`}
                          className="inline-flex min-h-10 items-center justify-center gap-2 whitespace-nowrap rounded-xl border border-slate-200 bg-white px-3 text-sm font-medium text-slate-700 transition hover:border-slate-300 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:border-slate-600 dark:hover:bg-slate-800"
                          title="进入构建页添加资料"
                        >
                          <Upload className="h-4 w-4" />
                          资料
                        </Link>
                        <button
                          type="button"
                          onClick={() => setExportSubjectId(subject.subject_id)}
                          className="inline-flex min-h-10 items-center justify-center gap-2 whitespace-nowrap rounded-xl border border-slate-200 bg-white px-3 text-sm font-medium text-slate-700 transition hover:border-slate-300 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:border-slate-600 dark:hover:bg-slate-800"
                          title="导出课程包"
                        >
                          <Download className="h-4 w-4" />
                          导出
                        </button>
                      </div>
                    </div>
                  </motion.div>
                );
              })}
            </div>
          ) : null}
        </div>
      </div>

      {isImportModalOpen ? (
        <SubjectImportModal onClose={() => setIsImportModalOpen(false)} />
      ) : null}

      {exportSubjectId ? (
        <SubjectExportModal subjectId={exportSubjectId} onClose={() => setExportSubjectId(null)} />
      ) : null}
    </>
  );
}
