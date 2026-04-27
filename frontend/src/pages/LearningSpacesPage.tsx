import { Link, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { BookOpen, LayoutGrid, Loader2, Plus } from "lucide-react";

import { listSubjectsApiApiV1SubjectsListPost } from "../api/generated/subjects";
import { unwrapOrvalResponse } from "../lib/unwrapOrvalResponse";
import { resolveSubjectIcon } from "../lib/subjectIcons";

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

export function LearningSpacesPage() {
  const navigate = useNavigate();

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

  return (
    <div className="min-h-full px-4 pb-12 pt-20 sm:px-6 sm:pt-24 md:px-12">
      <div className="mx-auto w-full max-w-[1400px]">
        <div className="flex flex-col gap-5 md:flex-row md:items-end md:justify-between">
          <div className="space-y-3">
            <div className="inline-flex items-center gap-2 rounded-full bg-white/85 dark:bg-slate-800/85 px-3 py-1 text-xs font-medium text-slate-500 dark:text-slate-400 ring-1 ring-slate-200/80 dark:ring-slate-700/80 backdrop-blur">
              <LayoutGrid className="h-3.5 w-3.5" />
              学习空间
            </div>
            <div>
              <h1 className="text-2xl font-semibold tracking-tight text-slate-900 dark:text-slate-100 sm:text-[32px]">学习空间</h1>
              <p className="mt-2 text-sm leading-6 text-slate-500 dark:text-slate-400">
                这里直接展示你已经创建的学科，每个学科都是一张独立卡片。
              </p>
            </div>
          </div>

          <button
            type="button"
            onClick={() => navigate("/", { state: { newEntryAt: Date.now() } })}
            className="inline-flex w-full items-center justify-center gap-2 rounded-2xl bg-slate-900 px-4 py-3 text-sm font-medium text-white transition hover:bg-slate-800 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-white sm:w-auto"
          >
            <Plus className="h-4 w-4" />
            新建学科
          </button>
        </div>

        <div className="mt-8 flex items-center justify-between">
          <h2 className="text-[15px] font-medium text-slate-500 dark:text-slate-400">学科列表</h2>
          <p className="text-sm text-slate-400 dark:text-slate-500">{isLoading ? "加载中..." : `${subjects.length} 个学科`}</p>
        </div>

        {isLoading ? (
          <div className="mt-8 flex min-h-[240px] items-center justify-center rounded-[30px] border border-dashed border-slate-200 dark:border-slate-800 bg-white/45 dark:bg-slate-900/45">
            <div className="flex items-center gap-2 text-sm text-slate-500 dark:text-slate-400">
              <Loader2 className="h-4 w-4 animate-spin" />
              正在加载学习空间...
            </div>
          </div>
        ) : null}

        {!isLoading && subjects.length === 0 ? (
          <div className="mt-8 flex min-h-[300px] flex-col items-center justify-center rounded-[30px] border border-dashed border-slate-200 dark:border-slate-800 bg-white/45 dark:bg-slate-900/45 px-6 text-center">
            <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-400">
              <LayoutGrid className="h-7 w-7" />
            </div>
            <h2 className="mt-5 text-lg font-semibold text-slate-900 dark:text-slate-100">还没有学习空间</h2>
            <p className="mt-2 max-w-md text-sm leading-6 text-slate-500 dark:text-slate-400">
              先创建一个学科，创建后它就会以独立卡片的形式出现在这里。
            </p>
            <button
              type="button"
              onClick={() => navigate("/", { state: { newEntryAt: Date.now() } })}
              className="mt-6 inline-flex items-center gap-2 rounded-2xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 px-4 py-3 text-sm font-medium text-slate-700 dark:text-slate-300 transition hover:border-slate-300 dark:hover:border-slate-600 hover:bg-slate-50 dark:hover:bg-slate-700"
            >
              <Plus className="h-4 w-4" />
              去新建学科
            </button>
          </div>
        ) : null}

        {!isLoading && subjects.length > 0 ? (
          <div className="mt-6 grid grid-cols-1 gap-6 md:grid-cols-2 xl:grid-cols-3">
          {subjects.map((subject: SubjectWithIcon, index: number) => {
              const displayName = displaySubjectName(subject);
              const SubjectIcon = resolveSubjectIcon(subject.icon_key);

              return (
                <motion.div
                  key={subject.subject_id}
                  className="h-full"
                  initial={{ opacity: 0, scale: 0.95, y: 10 }}
                  animate={{ opacity: 1, scale: 1, y: 0 }}
                  transition={{
                    delay: Math.min(index * 0.04, 0.24),
                    duration: 0.28,
                    ease: "easeOut",
                  }}
                  whileHover={{ y: -4 }}
                  whileTap={{ scale: 0.99 }}
                >
                  <Link
                    to={`/subject/${subject.subject_id}/build`}
                    className="group flex min-h-[288px] flex-col overflow-hidden rounded-3xl border border-slate-200/80 bg-white shadow-[0_6px_24px_rgba(15,23,42,0.06)] transition duration-300 hover:border-slate-300 hover:shadow-[0_20px_48px_rgba(15,23,42,0.12)] dark:border-slate-800/80 dark:bg-slate-900 dark:shadow-[0_6px_24px_rgba(0,0,0,0.2)] dark:hover:border-slate-700 dark:hover:shadow-[0_20px_48px_rgba(0,0,0,0.3)] sm:min-h-[328px] sm:rounded-[30px]"
                  >
                    <div className="relative h-[140px] overflow-hidden border-b border-slate-100 bg-[linear-gradient(135deg,#f8fafc_0%,#eef2ff_50%,#f8fafc_100%)] dark:border-slate-800 dark:bg-[linear-gradient(135deg,#0f172a_0%,#1e1b4b_50%,#0f172a_100%)] sm:h-[176px]">
                      <div className="absolute left-5 top-5 inline-flex items-center gap-2 rounded-full bg-white/92 dark:bg-slate-800/92 px-3 py-1.5 text-xs font-medium text-slate-600 dark:text-slate-300 shadow-sm">
                        <span className="h-2.5 w-2.5 rounded-full bg-sky-400" />
                        Ready
                      </div>
                      <div className="absolute right-5 top-5 rounded-full bg-white/92 dark:bg-slate-800/92 px-3 py-1.5 text-[11px] font-medium text-slate-500 dark:text-slate-400 shadow-sm">
                        学科
                      </div>
                      <div
                        className={`absolute left-5 bottom-5 flex h-16 w-16 items-center justify-center rounded-[22px] bg-gradient-to-br ${subjectTone(displayName)} text-2xl font-semibold text-white shadow-lg`}
                      >
                        <SubjectIcon className="h-8 w-8" strokeWidth={2.1} />
                      </div>
                      <div className="absolute inset-x-0 bottom-0 h-24 bg-gradient-to-t from-white/60 dark:from-slate-900/60 to-transparent" />
                    </div>

                    <div className="flex flex-1 flex-col px-6 pb-6 pt-5">
                      <h3 className="line-clamp-2 text-[19px] font-semibold leading-8 tracking-tight text-slate-900 dark:text-slate-100">
                        {displayName}
                      </h3>

                      <p className="mt-3 text-sm leading-6 text-slate-500 dark:text-slate-400">
                        打开这个学习空间，继续管理资料、知识结构和学习内容。
                      </p>

                      <div className="mt-6 flex flex-wrap gap-2">
                        <span className="rounded-full bg-slate-100 dark:bg-slate-800 px-3 py-1.5 text-xs font-medium text-slate-500 dark:text-slate-400">
                          已创建
                        </span>
                        <span className="rounded-full bg-slate-100 dark:bg-slate-800 px-3 py-1.5 text-xs font-medium text-slate-500 dark:text-slate-400">
                          可继续学习
                        </span>
                      </div>

                      <div className="mt-auto flex items-center justify-between border-t border-slate-100 dark:border-slate-800 pt-6">
                        <div className="inline-flex items-center gap-2 text-sm font-medium text-slate-500 dark:text-slate-400">
                          <BookOpen className="h-4 w-4" />
                          进入学习
                        </div>
                        <span className="rounded-full border border-slate-200 dark:border-slate-700 px-4 py-2 text-sm font-medium text-slate-700 dark:text-slate-300 transition group-hover:border-slate-300 dark:group-hover:border-slate-600 group-hover:bg-slate-50 dark:group-hover:bg-slate-800">
                          打开
                        </span>
                      </div>
                    </div>
                  </Link>
                </motion.div>
              );
            })}
          </div>
        ) : null}
      </div>
    </div>
  );
}
