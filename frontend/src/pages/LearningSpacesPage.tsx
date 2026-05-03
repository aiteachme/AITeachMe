import { useState } from "react";
import type { ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import {
  ArrowRight,
  BookOpen,
  Download,
  LayoutGrid,
  Loader2,
  PackagePlus,
  Plus,
  Upload,
} from "lucide-react";

import { listCoursesApiApiV1CoursesListPost } from "../api/generated/courses";
import { CourseExportModal } from "../components/course/CourseExportModal";
import { CourseImportModal } from "../components/course/CourseImportModal";
import { unwrapOrvalResponse } from "../lib/unwrapOrvalResponse";
import { resolveCourseIcon, resolveCourseTone } from "../lib/courseIcons";
import { cn } from "../lib/utils";
import { buildCoursePath } from "../lib/courseNavigation";

type CourseWithIcon = {
  course_id: string;
  name?: string | null;
  icon_key?: string | null;
};

function displayCourseName(course: { name?: string | null }) {
  return course.name?.trim() || "未命名课程";
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
  const [exportCourseId, setExportCourseId] = useState<string | null>(null);

  const { data: courses = [], isLoading } = useQuery({
    queryKey: ["courses"],
    queryFn: async () =>
      unwrapOrvalResponse(
        await listCoursesApiApiV1CoursesListPost({
          page: 1,
          size: 100,
        }),
      )?.items ?? [],
  });

  const courseCount = courses.length;
  return (
    <>
      <div className="min-h-full px-4 pb-24 pt-20 sm:px-6 sm:pb-12 md:px-10 lg:px-12 lg:pt-10 xl:px-16">
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
                  管理课程、资料和课程包迁移。每个课程都可以继续构建、查看知识库、导出备份。
                </p>
              </div>
            </div>

            <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap xl:justify-end">
              <WorkspaceActionButton
                variant="primary"
                icon={<Plus className="h-4 w-4" />}
                onClick={() => navigate("/", { state: { newEntryAt: Date.now() } })}
              >
                新建课程
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
              <h2 className="text-lg font-semibold text-slate-950 dark:text-slate-100">课程列表</h2>
              <p className="mt-1 text-sm leading-6 text-slate-500 dark:text-slate-400">
                {isLoading ? "正在加载课程..." : courseCount > 0 ? `${courseCount} 门课程可继续学习` : "还没有创建课程"}
              </p>
            </div>
          </div>

          {isLoading ? (
            <div className="mt-10 flex min-h-[180px] items-center justify-center pb-12 sm:mt-12 sm:pb-0">
              <div className="flex items-center gap-2 text-sm text-slate-500 dark:text-slate-400">
                <Loader2 className="h-4 w-4 animate-spin" />
                正在加载学习空间...
              </div>
            </div>
          ) : null}

          {!isLoading && courses.length === 0 ? (
            <div className="mt-10 flex min-h-[180px] flex-col items-center justify-center px-6 pb-12 text-center sm:mt-14 sm:pb-0">
              <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-slate-100/80 text-slate-500 dark:bg-slate-800/80 dark:text-slate-400">
                <LayoutGrid className="h-5 w-5" />
              </div>
              <h2 className="mt-4 text-lg font-semibold text-slate-900 dark:text-slate-100">还没有学习空间</h2>
              <p className="mt-2 max-w-md text-sm leading-6 text-slate-500 dark:text-slate-400">
                可以新建一个空课程，也可以直接导入别人分享的 .atmx 课程包。
              </p>
              <div className="mt-6 flex flex-col gap-2 sm:flex-row">
                <WorkspaceActionButton
                  variant="primary"
                  icon={<Plus className="h-4 w-4" />}
                  onClick={() => navigate("/", { state: { newEntryAt: Date.now() } })}
                >
                  新建课程
                </WorkspaceActionButton>
              </div>
            </div>
          ) : null}

          {!isLoading && courses.length > 0 ? (
            <div className="mt-5 grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
              {courses.map((course: CourseWithIcon, index: number) => {
                const displayName = displayCourseName(course);
                const CourseIcon = resolveCourseIcon(course.icon_key);

                return (
                  <motion.div
                    key={course.course_id}
                    className="atm-deferred-card group flex min-h-[190px] flex-col overflow-hidden rounded-xl border border-slate-200/80 bg-white/95 shadow-sm transition duration-200 hover:border-slate-300 hover:shadow-[0_18px_42px_rgba(15,23,42,0.08)] dark:border-slate-800/80 dark:bg-slate-900/90 dark:hover:border-slate-700 dark:hover:shadow-[0_18px_42px_rgba(0,0,0,0.24)]"
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
                    <div className="flex flex-1 flex-col p-4">
                      <div className="flex items-start gap-3">
                        <div className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br ${resolveCourseTone(displayName)} text-white shadow-sm`}>
                          <CourseIcon className="h-5 w-5" strokeWidth={2.1} />
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="flex items-start justify-between gap-2">
                            <h3 className="line-clamp-2 text-base font-semibold leading-6 text-slate-950 dark:text-slate-100">
                              {displayName}
                            </h3>
                            <button
                              type="button"
                              onClick={() => setExportCourseId(course.course_id)}
                              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-slate-400 transition hover:bg-slate-100 hover:text-slate-700 dark:text-slate-500 dark:hover:bg-slate-800 dark:hover:text-slate-200"
                              title="导出课程包"
                              aria-label={`导出 ${displayName}`}
                            >
                              <Download className="h-4 w-4" />
                            </button>
                          </div>
                          <p className="mt-1.5 text-sm leading-6 text-slate-500 dark:text-slate-400">继续构建、阅读、练习和查看画像。</p>
                        </div>
                      </div>

                      <div className="mt-auto pt-4">
                        <Link
                          to={buildCoursePath(course.course_id, "build")}
                          className="inline-flex min-h-10 w-full items-center justify-center gap-2 whitespace-nowrap rounded-xl bg-slate-900 px-3 text-sm font-medium text-white transition hover:bg-slate-800 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-white"
                        >
                          <BookOpen className="h-4 w-4" />
                          进入学习
                          <ArrowRight className="h-4 w-4" />
                        </Link>
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
        <CourseImportModal onClose={() => setIsImportModalOpen(false)} />
      ) : null}

      {exportCourseId ? (
        <CourseExportModal courseId={exportCourseId} onClose={() => setExportCourseId(null)} />
      ) : null}
    </>
  );
}
