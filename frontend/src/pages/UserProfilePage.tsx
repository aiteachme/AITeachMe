import type { ReactNode } from "react";
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  BookOpen,
  CalendarDays,
  FileText,
  Gauge,
  Loader2,
  MessageCircle,
  Sparkles,
} from "lucide-react";

import { listCoursesApiApiV1CoursesListPost } from "../api/generated/courses";
import { examHistoryApiV1CoursesCourseIdExamsHistoryGet } from "../api/generated/exams";
import { listChatApiApiV1CoursesCourseIdChatsListPost } from "../api/generated/chats";
import { masteryOverviewApiV1CoursesCourseIdProfileMasteryGet } from "../api/generated/profile";
import type {
  ChatMessageItem,
  CourseItem,
  ExamHistoryItem,
  MasteryOverviewResponse,
  MasteryStateResponse,
  UserProfileSummary,
} from "../api/generated/model";
import { getApiErrorMessage } from "../api/client";
import {
  buildLearningActivityEvents,
  buildLearningCalendarWeeks,
  countLearningActivitySince,
  formatLearningActivityKind,
  formatLearningActivityTime,
  getLatestLearningActivity,
  getLearningActivityTileClass,
} from "../lib/learningActivity";
import { buildCoursePath } from "../lib/courseNavigation";
import { cn } from "../lib/utils";
import { unwrapOrvalResponse } from "../lib/unwrapOrvalResponse";

const ACTIVITY_COURSE_LIMIT = 12;
const PROFILE_SNAPSHOT_COURSE_LIMIT = 4;

interface UserProfilePageData {
  courses: CourseItem[];
  exams: ExamHistoryItem[];
  chatMessages: ChatMessageItem[];
  masteryStates: MasteryStateResponse[];
  userProfile: UserProfileSummary | null;
}

function formatToken(value?: string | null, fallback = "暂无"): string {
  const text = value?.trim();
  if (!text) return fallback;
  const labels: Record<string, string> = {
    paper_exam: "完整试卷",
    web_practice: "网页练习",
    balanced: "均衡",
    steady: "稳定",
    intensive: "强化",
    concise: "简洁讲解",
    detailed: "详细讲解",
  };
  return labels[text] ?? text.replace(/[_-]+/g, " ");
}

function formatList(values?: string[] | null, fallback = "暂无稳定信号"): string {
  const items = (values ?? []).map((item) => formatToken(item, "")).filter(Boolean);
  return items.length ? items.join("、") : fallback;
}

function formatDate(value?: string | null): string {
  if (!value) return "暂无";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "暂无";
  return date.toLocaleDateString("zh-CN", { month: "2-digit", day: "2-digit" });
}

async function fetchUserProfilePageData(signal?: AbortSignal): Promise<UserProfilePageData> {
  const coursesResponse = await listCoursesApiApiV1CoursesListPost({ page: 1, size: 50 }, { signal });
  const courses = unwrapOrvalResponse<{ items?: CourseItem[] }>(coursesResponse)?.items ?? [];
  const sortedCourses = [...courses].sort(
    (left, right) => new Date(right.updated_at).getTime() - new Date(left.updated_at).getTime(),
  );
  const activityCourseIds = sortedCourses.map((item) => item.course_id).slice(0, ACTIVITY_COURSE_LIMIT);
  const profileCourseIds = activityCourseIds.slice(0, PROFILE_SNAPSHOT_COURSE_LIMIT);

  const activityResults = await Promise.allSettled(
    activityCourseIds.map(async (courseId) => {
      const [examResponse, chatResponse] = await Promise.all([
        examHistoryApiV1CoursesCourseIdExamsHistoryGet(courseId, { page: 1, size: 50 }, { signal }),
        listChatApiApiV1CoursesCourseIdChatsListPost(courseId, { page: 1, size: 80 }, { signal }),
      ]);
      return {
        exams: unwrapOrvalResponse<{ items?: ExamHistoryItem[] }>(examResponse)?.items ?? [],
        chatMessages: unwrapOrvalResponse<{ items?: ChatMessageItem[] }>(chatResponse)?.items ?? [],
      };
    }),
  );

  const masteryResults = await Promise.allSettled(
    profileCourseIds.map(async (courseId) => {
      const response = await masteryOverviewApiV1CoursesCourseIdProfileMasteryGet(courseId, { signal });
      return unwrapOrvalResponse<MasteryOverviewResponse>(response);
    }),
  );
  const masterySnapshots = masteryResults
    .flatMap((result) => (result.status === "fulfilled" && result.value ? [result.value] : []));

  return {
    courses: sortedCourses,
    exams: activityResults.flatMap((result) => (result.status === "fulfilled" ? result.value.exams : [])),
    chatMessages: activityResults.flatMap((result) => (
      result.status === "fulfilled" ? result.value.chatMessages : []
    )),
    masteryStates: masterySnapshots.flatMap((item) => item.knowledge_unit_states ?? []),
    userProfile: masterySnapshots.find((item) => item.user_profile)?.user_profile ?? null,
  };
}

function UserProfileStat({
  label,
  value,
  detail,
  icon,
}: {
  label: string;
  value: string;
  detail: string;
  icon: ReactNode;
}) {
  return (
    <div className="rounded-2xl border border-slate-200/60 bg-white p-5 shadow-sm dark:border-slate-800/60 dark:bg-[#0a0d16]/70">
      <div className="flex items-center gap-3">
        <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-violet-50 text-violet-600 ring-1 ring-violet-100 dark:bg-violet-500/10 dark:text-violet-300 dark:ring-violet-500/20">
          {icon}
        </span>
        <div className="min-w-0">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-400 dark:text-slate-500">{label}</p>
          <p className="mt-0.5 truncate text-xl font-bold text-slate-900 dark:text-slate-100">{value}</p>
          <p className="mt-0.5 truncate text-[11px] text-slate-400 dark:text-slate-500">{detail}</p>
        </div>
      </div>
    </div>
  );
}

export function UserProfilePage() {
  const profileQuery = useQuery({
    queryKey: ["user-profile-page"],
    queryFn: ({ signal }) => fetchUserProfilePageData(signal),
    staleTime: 60_000,
    retry: 1,
  });

  const data = profileQuery.data;
  const events = useMemo(
    () => buildLearningActivityEvents({
      chatMessages: data?.chatMessages,
      exams: data?.exams,
      masteryStates: data?.masteryStates,
    }),
    [data?.chatMessages, data?.exams, data?.masteryStates],
  );
  const calendarWeeks = useMemo(() => buildLearningCalendarWeeks(events, { weeks: 20 }), [events]);
  const weeklyCount = useMemo(() => countLearningActivitySince(events, 7), [events]);
  const monthlyCount = useMemo(() => countLearningActivitySince(events, 30), [events]);
  const latestActivity = useMemo(() => getLatestLearningActivity(events), [events]);
  const userProfile = data?.userProfile ?? null;
  const courses = data?.courses ?? [];
  const notes = (userProfile?.notes ?? []).filter((item) => item.trim()).slice(0, 5);
  const latestActivityText = latestActivity
    ? `${formatLearningActivityKind(latestActivity.kind)} · ${formatLearningActivityTime(latestActivity.occurredAt)}`
    : "完成问答或测验后会自动更新";

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 px-5 py-8 md:px-8">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-violet-500">User Profile</p>
          <h1 className="mt-2 text-2xl font-bold tracking-tight text-slate-950 dark:text-slate-50">我的学习画像</h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-500 dark:text-slate-400">
            汇总所有课程里的真实问答、测验和画像信号，用来观察整体学习节奏、偏好和待复习压力。
          </p>
        </div>
        <Link
          to="/"
          className="inline-flex h-9 items-center justify-center rounded-full border border-slate-200 bg-white px-4 text-sm font-medium text-slate-700 shadow-sm transition hover:border-violet-200 hover:text-violet-600 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-200 dark:hover:border-violet-500/40"
        >
          回到首页
        </Link>
      </header>

      {profileQuery.isError ? (
        <div className="rounded-xl border border-red-200 bg-red-50 px-5 py-4 text-sm text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
          {getApiErrorMessage(profileQuery.error, "用户学习画像加载失败，请重试。")}
        </div>
      ) : null}

      {profileQuery.isLoading ? (
        <div className="flex h-72 items-center justify-center rounded-2xl border border-slate-200/60 bg-white dark:border-slate-800/60 dark:bg-[#0a0d16]/70">
          <Loader2 className="h-8 w-8 animate-spin text-violet-400" />
        </div>
      ) : (
        <>
          <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <UserProfileStat
              label="活跃课程"
              value={String(userProfile?.active_course_count ?? courses.length)}
              detail={`最近读取 ${Math.min(courses.length, ACTIVITY_COURSE_LIMIT)} 门`}
              icon={<BookOpen className="h-5 w-5" strokeWidth={1.5} />}
            />
            <UserProfileStat
              label="本周记录"
              value={String(weeklyCount)}
              detail={`近 30 天 ${monthlyCount} 条`}
              icon={<CalendarDays className="h-5 w-5" strokeWidth={1.5} />}
            />
            <UserProfileStat
              label="待复习"
              value={String(userProfile?.due_review_count ?? userProfile?.pending_review_count ?? 0)}
              detail="跨课程复习压力"
              icon={<Gauge className="h-5 w-5" strokeWidth={1.5} />}
            />
            <UserProfileStat
              label="最近学习"
              value={latestActivity?.label ?? "暂无记录"}
              detail={latestActivityText}
              icon={<FileText className="h-5 w-5" strokeWidth={1.5} />}
            />
          </section>

          <section className="rounded-2xl border border-slate-200/60 bg-white p-5 shadow-sm dark:border-slate-800/60 dark:bg-[#0a0d16]/70">
            <div className="mb-4 flex items-center justify-between gap-3">
              <div>
                <h2 className="text-sm font-semibold text-slate-900 dark:text-slate-100">学习活跃砖图</h2>
                <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">近 20 周，颜色越深表示当天真实学习记录越多。</p>
              </div>
              <span className="rounded-full bg-violet-50 px-2.5 py-1 text-[11px] font-medium text-violet-600 dark:bg-violet-500/10 dark:text-violet-200">
                用户级
              </span>
            </div>

            <div className="flex gap-2 overflow-x-auto pb-1" aria-label="用户级学习活跃砖图">
              <div className="flex shrink-0 flex-col gap-1.5 text-[10px] text-slate-400 dark:text-slate-500">
                <span className="flex h-3.5 items-center">一</span>
                <span className="flex h-3.5 items-center">&nbsp;</span>
                <span className="flex h-3.5 items-center">三</span>
                <span className="flex h-3.5 items-center">&nbsp;</span>
                <span className="flex h-3.5 items-center">五</span>
                <span className="flex h-3.5 items-center">&nbsp;</span>
                <span className="flex h-3.5 items-center">日</span>
              </div>
              <div className="flex min-w-max gap-1.5">
                {calendarWeeks.map((week) => (
                  <div key={week.key} className="flex flex-col gap-1.5">
                    {week.days.map((day) => (
                      <span
                        key={day.key}
                        className={cn(
                          "h-3.5 w-3.5 rounded-[4px] transition",
                          day.isPlaceholder ? "pointer-events-none opacity-0" : getLearningActivityTileClass(day.intensity),
                          day.isToday && "ring-2 ring-violet-300 dark:ring-violet-500/40",
                        )}
                        title={`${day.key}（${day.label}）· ${day.count} 条真实学习记录`}
                        aria-label={`${day.key} ${day.count} 条真实学习记录`}
                      />
                    ))}
                  </div>
                ))}
              </div>
            </div>
          </section>

          <section className="grid gap-5 lg:grid-cols-3">
            <div className="rounded-2xl border border-slate-200/60 bg-white p-5 shadow-sm dark:border-slate-800/60 dark:bg-[#0a0d16]/70">
              <div className="mb-4 flex items-center gap-2">
                <Sparkles className="h-4 w-4 text-violet-500" />
                <h2 className="text-sm font-semibold text-slate-900 dark:text-slate-100">全局偏好</h2>
              </div>
              <dl className="space-y-3 text-sm">
                <div>
                  <dt className="text-xs text-slate-400 dark:text-slate-500">讲解风格</dt>
                  <dd className="mt-1 text-slate-800 dark:text-slate-200">{formatToken(userProfile?.explanation_style, "暂无稳定信号")}</dd>
                </div>
                <div>
                  <dt className="text-xs text-slate-400 dark:text-slate-500">学习节奏</dt>
                  <dd className="mt-1 text-slate-800 dark:text-slate-200">{formatToken(userProfile?.pace_preference, "暂无稳定信号")}</dd>
                </div>
                <div>
                  <dt className="text-xs text-slate-400 dark:text-slate-500">常用题型</dt>
                  <dd className="mt-1 text-slate-800 dark:text-slate-200">{formatList(userProfile?.preferred_question_types)}</dd>
                </div>
                <div>
                  <dt className="text-xs text-slate-400 dark:text-slate-500">考试模式</dt>
                  <dd className="mt-1 text-slate-800 dark:text-slate-200">{formatList(userProfile?.preferred_exam_modes)}</dd>
                </div>
              </dl>
            </div>

            <div className="rounded-2xl border border-slate-200/60 bg-white p-5 shadow-sm dark:border-slate-800/60 dark:bg-[#0a0d16]/70">
              <div className="mb-4 flex items-center gap-2">
                <BookOpen className="h-4 w-4 text-violet-500" />
                <h2 className="text-sm font-semibold text-slate-900 dark:text-slate-100">最近课程</h2>
              </div>
              {courses.length ? (
                <div className="space-y-3">
                  {courses.slice(0, 5).map((course) => (
                    <Link
                      key={course.course_id}
                      to={buildCoursePath(course.course_id, "nav")}
                      className="block rounded-xl border border-slate-100 px-3 py-2.5 transition hover:border-violet-100 hover:bg-violet-50/40 dark:border-slate-800 dark:hover:border-violet-500/30 dark:hover:bg-violet-500/10"
                    >
                      <p className="truncate text-sm font-medium text-slate-800 dark:text-slate-200">{course.name}</p>
                      <p className="mt-0.5 text-xs text-slate-400 dark:text-slate-500">更新于 {formatDate(course.updated_at)}</p>
                    </Link>
                  ))}
                </div>
              ) : (
                <p className="text-sm leading-6 text-slate-500 dark:text-slate-400">创建课程并完成一次问答或测验后，这里会开始沉淀画像。</p>
              )}
            </div>

            <div className="rounded-2xl border border-slate-200/60 bg-white p-5 shadow-sm dark:border-slate-800/60 dark:bg-[#0a0d16]/70">
              <div className="mb-4 flex items-center gap-2">
                <MessageCircle className="h-4 w-4 text-violet-500" />
                <h2 className="text-sm font-semibold text-slate-900 dark:text-slate-100">画像记忆</h2>
              </div>
              {userProfile?.profile_text ? (
                <p className="line-clamp-5 text-sm leading-6 text-slate-600 dark:text-slate-300">{userProfile.profile_text}</p>
              ) : (
                <p className="text-sm leading-6 text-slate-500 dark:text-slate-400">暂无足够信号生成稳定用户画像。</p>
              )}
              {notes.length ? (
                <div className="mt-4 space-y-2">
                  {notes.map((note) => (
                    <p key={note} className="rounded-lg bg-slate-50 px-3 py-2 text-xs leading-5 text-slate-500 dark:bg-slate-900/60 dark:text-slate-400">
                      {note}
                    </p>
                  ))}
                </div>
              ) : null}
            </div>
          </section>
        </>
      )}
    </div>
  );
}
