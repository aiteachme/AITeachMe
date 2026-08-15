import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  AlertCircle,
  ArrowRight,
  BookOpen,
  CalendarClock,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
  CheckCircle2,
  ClipboardCheck,
  ExternalLink,
  FileText,
  Gauge,
  Info,
  ListCollapse,
  ListTree,
  Loader2,
  LogIn,
  Lock,
  Network,
  Plus,
  SlidersHorizontal,
  Sparkles,
  Target,
  Trophy,
} from "lucide-react";

import { anonymousApiClient, apiClient, getApiErrorMessage } from "../api/client";
import type { ApiResponse } from "../api/types";
import type { CourseShareDocumentContent, CourseShareDocumentPreview, CourseSharePreviewData, ImportResultData } from "../api/generated/model";
import { PlannerPlanCardShell, PlannerPlanSummary } from "../components/build-plan/PlannerPlanCard";
import { CourseSharePillTitle } from "../components/course/CoursePagePillTitle";
import {
  COURSE_PAGE_CONTENT_CLASS,
  COURSE_PAGE_HEADER_ACTION_BUTTON_CLASS,
  COURSE_PAGE_SHELL_CLASS,
  CoursePageHeader,
} from "../components/course/CoursePageHeader";
import { useDocToc, type TocTreeNode } from "../components/knowledge-docs";
import { Button } from "../components/ui/Button";
import { MarkdownViewer } from "../components/ui/MarkdownViewer";
import { useToast } from "../components/ui/Toast";
import { useAuthSession } from "../hooks/useAuthSession";
import { buildCoursePath } from "../lib/courseNavigation";
import { publicAssetPath } from "../lib/publicAsset";
import { cn } from "../lib/utils";

const FLOATING_ACTION_CLASS =
  "fixed right-6 inline-flex h-10 w-10 items-center justify-center gap-2 rounded-xl border border-slate-200/70 bg-white/90 text-[13px] font-medium text-slate-700 shadow-[0_12px_32px_-24px_rgba(15,23,42,0.55)] backdrop-blur-md transition duration-200 hover:-translate-y-0.5 hover:border-slate-300 hover:bg-white hover:text-slate-950 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/30 active:translate-y-0 active:scale-[0.98] sm:w-[9.25rem] sm:justify-start sm:px-3 dark:border-slate-800/80 dark:bg-slate-950/88 dark:text-slate-300 dark:shadow-[0_18px_44px_-28px_rgba(0,0,0,0.9)] dark:hover:border-slate-700 dark:hover:bg-slate-950 dark:hover:text-slate-100";
const LOGO_SRC = publicAssetPath("logo.svg");
const SHARE_TRAINING_SECTION_CLASS =
  "border-b border-slate-200 py-7 dark:border-slate-800";

type ShareView = "build" | "knowledge-docs" | "exams" | "profile";

const SHARE_VIEWS = new Set<ShareView>(["build", "knowledge-docs", "exams", "profile"]);

function normalizeShareView(value: string | null): ShareView {
  return value && SHARE_VIEWS.has(value as ShareView) ? value as ShareView : "knowledge-docs";
}

function pickSelectedDocId(documents: CourseShareDocumentPreview[], requestedDocId: string | null): string {
  if (requestedDocId && documents.some((doc) => doc.doc_id === requestedDocId)) {
    return requestedDocId;
  }
  return documents[0]?.doc_id ?? "";
}

function collectCollapsibleTocIds(nodes: TocTreeNode[]): Set<string> {
  const ids = new Set<string>();
  const visit = (items: TocTreeNode[]) => {
    for (const node of items) {
      if (node.children.length > 0) {
        ids.add(node.item.id);
        visit(node.children);
      }
    }
  };
  visit(nodes);
  return ids;
}

function splitTocDisplayText(text: string): { number: string | null; title: string } {
  const trimmed = text.trim();
  const match = trimmed.match(/^((?:\d+\.)*\d+)\s+(.+)$/);
  if (!match) {
    return { number: null, title: trimmed };
  }
  const number = match[1]
    .split(".")
    .map((part) => String(Number(part) || part))
    .join(".");
  return { number, title: match[2].trim() };
}

function shareStat(preview: CourseSharePreviewData, key: string): number {
  const value = preview.stats?.[key as keyof typeof preview.stats];
  const numeric = Number(value ?? 0);
  return Number.isFinite(numeric) ? Math.max(0, numeric) : 0;
}

function formatStat(value: number): string {
  return value.toLocaleString("zh-CN");
}

function formatSharedPreviewText(value: string | null | undefined, fallback = ""): string {
  const source = String(value || "").trim();
  if (!source) {
    return fallback;
  }
  return source
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/!\[[^\]]*]\([^)]*\)/g, " ")
    .replace(/\[([^\]]+)]\([^)]*\)/g, "$1")
    .replace(/`([^`]*)`/g, "$1")
    .replace(/^#{1,6}\s*/gm, "")
    .replace(/^\s*>\s?/gm, "")
    .replace(/^\s*[-*+]\s+/gm, "")
    .replace(/\*\*|__|\*|_/g, "")
    .replace(/^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$/gm, " ")
    .replace(/\s*\|\s*/g, "；")
    .replace(/(?:^|；)\s*:?-{3,}:?\s*(?=；|$)/g, "；")
    .replace(/[ \t]*\n[ \t]*/g, " ")
    .replace(/\s+/g, " ")
    .replace(/；{2,}/g, "；")
    .replace(/^；|；$/g, "")
    .trim()
    || fallback;
}

function SaveRequiredButton({
  children,
  onClick,
  variant = "outline",
  className,
}: {
  children: ReactNode;
  onClick: () => void;
  variant?: "default" | "outline" | "ghost";
  className?: string;
}) {
  return (
    <Button
      type="button"
      variant={variant}
      className={className}
      onClick={onClick}
    >
      {children}
    </Button>
  );
}

function SharedAssistantAvatar() {
  return (
    <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-slate-200 bg-slate-50 p-1 dark:border-slate-800 dark:bg-slate-900">
      <img src={LOGO_SRC} alt="AI" className="h-full w-full object-contain" />
    </div>
  );
}

function SharedReadonlyBuildView({
  preview,
  documents,
  onSaveRequired,
}: {
  preview: CourseSharePreviewData;
  documents: CourseShareDocumentPreview[];
  onSaveRequired: (feature: string) => void;
}) {
  const description = preview.course_description?.trim();
  const outlineItems = useMemo(() => documents.map((doc) => ({
      title: doc.title,
      description: formatSharedPreviewText(doc.summary || doc.excerpt),
  })), [documents]);
  const readonlyBadge = (
    <span className="inline-flex items-center gap-1.5 rounded-md bg-zinc-100 px-2.5 py-1 text-xs font-medium text-zinc-600 dark:bg-slate-800 dark:text-slate-300">
      <Lock className="h-3.5 w-3.5" />
      只读
    </span>
  );

  return (
    <div className="relative flex min-h-full w-full flex-col bg-transparent">
      <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-4 pt-6 md:px-8 md:pt-8 lg:px-16">
        <div className="mx-auto max-w-3xl space-y-5">
          <div className="flex gap-3">
            <SharedAssistantAvatar />
            <div className="min-w-0 flex-1 space-y-3">
              <PlannerPlanCardShell
                courseName={preview.course_name}
                stageDescription="共享课程方案 · 只读预览"
                stageBadge={readonlyBadge}
              >
                <PlannerPlanSummary
                  introText={description || "这门共享课程已经整理成一条可直接浏览的学习路径。"}
                  outlineItems={outlineItems}
                />
              </PlannerPlanCardShell>
            </div>
          </div>
        </div>
      </div>

      <div className="shrink-0 px-4 pb-6 pt-2 md:px-8 lg:px-16">
        <div className="mx-auto max-w-3xl">
          <div className="w-full rounded-lg border border-zinc-200 bg-white transition-colors dark:border-slate-800 dark:bg-slate-900">
            <button
              type="button"
              onClick={() => onSaveRequired("继续规划")}
              className="block min-h-[56px] w-full resize-none border-0 bg-transparent px-4 pb-3 pt-4 text-left text-[14px] leading-relaxed text-zinc-400 dark:text-slate-500"
            >
              输入新的学习目标或上传资料前，请先保存到自己的课程
            </button>

            <div className="px-3 pb-3">
              <div className="flex flex-col gap-2 px-1 sm:flex-row sm:items-center sm:justify-between">
                <div className="flex min-w-0 w-full flex-wrap items-center gap-1.5 sm:flex-1 sm:gap-2">
                  <SaveRequiredButton onClick={() => onSaveRequired("上传资料")} variant="ghost" className="h-9 shrink-0 rounded-md px-2.5 text-xs font-medium text-zinc-500">
                    <FileText className="h-4 w-4" />
                    上传
                  </SaveRequiredButton>
                  <SaveRequiredButton onClick={() => onSaveRequired("从资料库选择资料")} variant="ghost" className="h-9 shrink-0 rounded-md px-2.5 text-xs font-medium text-zinc-500">
                    <BookOpen className="h-4 w-4" />
                    资料库
                  </SaveRequiredButton>
                </div>
                <SaveRequiredButton onClick={() => onSaveRequired("继续规划")} className="h-9 rounded-md bg-zinc-900 px-3 text-xs font-semibold text-white dark:bg-slate-100 dark:text-slate-950">
                  <ArrowRight className="h-4 w-4" />
                  发送
                </SaveRequiredButton>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
function SharedTrainingModeCard({
  icon,
  title,
  statusBadge,
  description,
  meta,
  actions,
  variant = "practice",
}: {
  icon: ReactNode;
  title: string;
  statusBadge: string;
  description: string;
  meta: string[];
  actions: ReactNode;
  variant?: "practice" | "paper" | "mastery";
}) {
  const toneClass = {
    practice: {
      icon: "bg-blue-50 text-blue-600 dark:bg-blue-500/10 dark:text-blue-400",
    },
    paper: {
      icon: "bg-indigo-50 text-indigo-600 dark:bg-indigo-500/10 dark:text-indigo-400",
    },
    mastery: {
      icon: "bg-emerald-50 text-emerald-600 dark:bg-emerald-500/10 dark:text-emerald-400",
    },
  }[variant];

  return (
    <article className="grid min-w-0 grid-cols-1 gap-4 px-1 py-5 md:grid-cols-[minmax(0,1fr)_auto] md:items-center lg:grid-cols-[minmax(0,1fr)_minmax(220px,0.55fr)_220px]">
        <div className="flex min-w-0 items-start gap-3.5">
          <div className={cn("grid h-10 w-10 shrink-0 place-items-center rounded-lg", toneClass.icon)}>
            {icon}
          </div>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-base font-semibold leading-tight text-slate-950 dark:text-slate-100">{title}</h3>
              <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-500 dark:bg-slate-900 dark:text-slate-400">
                {statusBadge}
              </span>
            </div>
            <p className="mt-1 text-sm leading-6 text-slate-500 dark:text-slate-400">{description}</p>
          </div>
        </div>
          <div className="grid grid-flow-col auto-cols-fr divide-x divide-slate-200 dark:divide-slate-800">
            {meta.map((item) => (
              <span key={item} className="px-2 text-center text-xs font-medium leading-5 text-slate-600 dark:text-slate-300">
                {item}
              </span>
            ))}
          </div>
          <div className="grid w-full grid-cols-2 items-center gap-2 md:col-span-2 md:max-w-[220px] md:justify-self-end lg:col-span-1">{actions}</div>
    </article>
  );
}

function SharedReadonlyExamsView({
  preview,
  onSaveRequired,
}: {
  preview: CourseSharePreviewData;
  onSaveRequired: (feature: string) => void;
}) {
  const templateCount = shareStat(preview, "question_template_count");
  const paperCount = shareStat(preview, "exam_paper_count");

  return (
    <div className={COURSE_PAGE_SHELL_CLASS}>
      <div className={`${COURSE_PAGE_CONTENT_CLASS} gap-5`}>
        <CoursePageHeader
          title={preview.course_name}
          description="选择训练方式，题目来自课程资料与题库沉淀。"
          actions={
            <>
              <Button type="button" variant="outline" className={COURSE_PAGE_HEADER_ACTION_BUTTON_CLASS} onClick={() => onSaveRequired("查看题库")}>
                <BookOpen className="h-4 w-4 shrink-0" />
                题库
              </Button>
              <Button type="button" variant="outline" className={COURSE_PAGE_HEADER_ACTION_BUTTON_CLASS} onClick={() => onSaveRequired("查看题型")}>
                <Target className="h-4 w-4 shrink-0" />
                查看题型
              </Button>
            </>
          }
        />

        <section className={SHARE_TRAINING_SECTION_CLASS}>
          <div className="mb-4 flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <h2 className="text-lg font-black text-slate-950 dark:text-slate-100">训练模式</h2>
              <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">选择训练方式，题目来自课程资料与题库沉淀。</p>
            </div>
          </div>

          <div className="divide-y divide-slate-200 border-y border-slate-200 dark:divide-slate-800 dark:border-slate-800">
            <SharedTrainingModeCard
              icon={<ClipboardCheck className="h-5 w-5" />}
              title="网页练习"
              statusBadge={templateCount > 0 ? "可准备" : "待保存"}
              description="日常巩固，快速检验掌握情况。"
              meta={["默认 10 题", "预计 10-15 分钟"]}
              actions={
                <>
                  <SaveRequiredButton onClick={() => onSaveRequired("开始网页练习")} className="rounded-lg bg-black px-5 dark:bg-white dark:text-slate-950" variant="default">
                    <Plus className="h-3.5 w-3.5" />
                    开始
                  </SaveRequiredButton>
                  <SaveRequiredButton onClick={() => onSaveRequired("调整出题配置")} className="rounded-lg" variant="outline">
                    <SlidersHorizontal className="h-3.5 w-3.5" />
                    出题配置
                  </SaveRequiredButton>
                </>
              }
            />

            <SharedTrainingModeCard
              icon={<FileText className="h-5 w-5" />}
              title="整卷检测"
              statusBadge={paperCount > 0 ? `${paperCount} 份记录` : "待保存"}
              description="模拟真实试卷结构进行整卷检测。"
              meta={["默认 25 题", "预计 25-35 分钟"]}
              variant="paper"
              actions={
                <>
                  <SaveRequiredButton onClick={() => onSaveRequired("开始整卷检测")} className="rounded-lg bg-black px-5 dark:bg-white dark:text-slate-950" variant="default">
                    <Plus className="h-3.5 w-3.5" />
                    开始
                  </SaveRequiredButton>
                  <SaveRequiredButton onClick={() => onSaveRequired("调整出题配置")} className="rounded-lg" variant="outline">
                    <SlidersHorizontal className="h-3.5 w-3.5" />
                    出题配置
                  </SaveRequiredButton>
                </>
              }
            />

            <SharedTrainingModeCard
              icon={<Sparkles className="h-5 w-5" />}
              title="闯关"
              statusBadge={templateCount > 0 ? "可准备" : "待保存"}
              description="围绕薄弱点连续练习。"
              meta={["默认 20 题", "按画像动态选题"]}
              variant="mastery"
              actions={
                <>
                  <SaveRequiredButton onClick={() => onSaveRequired("开始闯关")} className="rounded-lg bg-black px-5 dark:bg-white dark:text-slate-950" variant="default">
                    <Plus className="h-3.5 w-3.5" />
                    开始
                  </SaveRequiredButton>
                  <SaveRequiredButton onClick={() => onSaveRequired("调整闯关配置")} className="rounded-lg" variant="outline">
                    <SlidersHorizontal className="h-3.5 w-3.5" />
                    出题配置
                  </SaveRequiredButton>
                </>
              }
            />
          </div>
          <div className="mt-4 flex items-center gap-2 px-1 text-xs leading-5 text-slate-400 dark:text-slate-500">
            <Info className="h-3.5 w-3.5 shrink-0" />
            <span>闯关优先复用题库题目；题目不足时会自动准备新题，并在生成后沉淀到题库。</span>
          </div>
        </section>

        <section className={SHARE_TRAINING_SECTION_CLASS}>
          <div className="mb-4 flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <h2 className="text-lg font-black text-slate-950 dark:text-slate-100">训练记录</h2>
              <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">继续未完成内容，或回看已完成测验和考卷。</p>
            </div>
          </div>
          <div className="space-y-3">
            {[
              { key: "active", title: "待完成", count: 0, emptyText: "暂无待完成记录" },
              { key: "completed", title: "已完成", count: paperCount, emptyText: "暂无已完成记录" },
            ].map((group) => (
              <div key={group.key} className="border-t border-slate-200 py-4 first:border-t-0 dark:border-slate-800">
                <button type="button" onClick={() => onSaveRequired("查看训练记录")} className="flex w-full items-center gap-4 text-left">
                  <h3 className="flex shrink-0 items-center gap-2 text-base font-semibold text-slate-950 dark:text-slate-100">
                    <span>{group.title}</span>
                    <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-500 dark:bg-slate-900 dark:text-slate-400">
                      {formatStat(group.count)}
                    </span>
                  </h3>
                  <div className="h-px flex-1 bg-slate-200/80 dark:bg-slate-800" />
                  <div className="grid h-8 w-8 shrink-0 place-items-center rounded-full text-slate-500 dark:text-slate-400">
                    <ChevronRight className="h-4 w-4" />
                  </div>
                </button>

                {group.count === 0 ? (
                  <div className="mt-3 flex items-center gap-2 border-t border-dashed border-slate-200 px-1 py-4 text-sm text-slate-500 dark:border-slate-800 dark:text-slate-400">
                    <FileText className="h-4 w-4 shrink-0 text-slate-400 dark:text-slate-500" />
                    <span>{group.emptyText}</span>
                  </div>
                ) : (
                  <button
                    type="button"
                    onClick={() => onSaveRequired("打开历史测验")}
                    className="group mt-3 flex w-full items-center justify-between gap-4 rounded-lg px-3 py-3 text-left transition hover:bg-slate-50 dark:hover:bg-slate-900"
                  >
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="h-2 w-2 shrink-0 rounded-full bg-emerald-500" />
                        <p className="truncate text-sm font-semibold text-slate-900 dark:text-slate-100">历史测验记录</p>
                      </div>
                      <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">整卷检测 · {formatStat(group.count)} 份记录</p>
                    </div>
                    <ArrowRight className="h-4 w-4 shrink-0 text-slate-300 transition group-hover:translate-x-0.5 group-hover:text-indigo-500" />
                  </button>
                )}
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}

function SharedSectionHeading({
  icon,
  title,
  detail,
  action,
}: {
  icon: ReactNode;
  title: string;
  detail?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex items-center justify-between gap-4 border-b border-slate-200 pb-3 dark:border-slate-800">
      <div className="min-w-0">
        <h2 className="flex items-center gap-2 text-sm font-bold text-slate-950 dark:text-slate-100">
          <span className="text-slate-400 dark:text-slate-500">{icon}</span>
          {title}
        </h2>
        {detail ? <p className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">{detail}</p> : null}
      </div>
      {action}
    </div>
  );
}

function SharedSummaryMetric({
  label,
  value,
  hint,
  icon,
  tone = "slate",
}: {
  label: string;
  value: string;
  hint: string;
  icon: ReactNode;
  tone?: "indigo" | "emerald" | "rose" | "slate";
}) {
  const toneClass = {
    indigo: "bg-indigo-50 text-indigo-600 dark:bg-indigo-500/10 dark:text-indigo-300",
    emerald: "bg-emerald-50 text-emerald-600 dark:bg-emerald-500/10 dark:text-emerald-300",
    rose: "bg-rose-50 text-rose-600 dark:bg-rose-500/10 dark:text-rose-300",
    slate: "bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-300",
  }[tone];

  return (
    <div className="p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs font-semibold text-slate-500 dark:text-slate-400">{label}</p>
          <p className="mt-1 text-2xl font-black tabular-nums text-slate-950 dark:text-slate-50">{value}</p>
        </div>
        <span className={cn("flex h-10 w-10 shrink-0 items-center justify-center rounded-lg", toneClass)}>
          {icon}
        </span>
      </div>
      <p className="mt-3 truncate text-xs text-slate-500 dark:text-slate-400">{hint}</p>
    </div>
  );
}

function SharedEmptyBlock({ icon, title, detail }: { icon: ReactNode; title: string; detail: string }) {
  return (
    <div className="flex min-h-[160px] flex-col items-center justify-center rounded-lg border border-dashed border-slate-200 bg-slate-50/50 px-5 py-8 text-center dark:border-slate-800 dark:bg-slate-900/30">
      <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-slate-100 text-slate-400 dark:bg-slate-900 dark:text-slate-500">
        {icon}
      </div>
      <p className="mt-3 text-sm font-semibold text-slate-800 dark:text-slate-200">{title}</p>
      <p className="mt-1 max-w-sm text-xs leading-5 text-slate-500 dark:text-slate-400">{detail}</p>
    </div>
  );
}

function SharedReadonlyProfileView({
  preview,
  onSaveRequired,
  onViewChange,
}: {
  preview: CourseSharePreviewData;
  onSaveRequired: (feature: string) => void;
  onViewChange: (view: ShareView) => void;
}) {
  const masteryCount = shareStat(preview, "user_knowledge_state_count");
  const paperCount = shareStat(preview, "exam_paper_count");
  const documents = preview.documents ?? [];
  const planDocuments = documents.slice(0, 4);
  const [isProfileExpanded, setIsProfileExpanded] = useState(false);

  return (
    <div className={COURSE_PAGE_SHELL_CLASS}>
      <div className={`${COURSE_PAGE_CONTENT_CLASS} gap-5`}>
        <CoursePageHeader
          title={preview.course_name}
          description="用测验、复习和知识点掌握记录，判断现在最该补哪里。"
          actions={
            <>
              <Button type="button" variant="outline" onClick={() => onViewChange("knowledge-docs")} className={COURSE_PAGE_HEADER_ACTION_BUTTON_CLASS}>
                <BookOpen className="h-4 w-4 shrink-0" />
                看知识库
              </Button>
              <Button type="button" variant="outline" onClick={() => onViewChange("exams")} className={COURSE_PAGE_HEADER_ACTION_BUTTON_CLASS}>
                <FileText className="h-4 w-4 shrink-0" />
                练习中心
              </Button>
            </>
          }
        />

        <div className="grid items-stretch gap-4 xl:grid-cols-[minmax(0,1.45fr)_minmax(360px,0.55fr)]">
          <section className="flex h-full flex-col rounded-lg border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-slate-950/75 sm:p-6">
            <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
              <div className="min-w-0">
                <p className="flex items-center gap-2 text-xs font-bold text-indigo-600 dark:text-indigo-300">
                  <Sparkles className="h-4 w-4" />
                  下一步建议
                </p>
                <h2 className="mt-3 text-2xl font-black leading-tight tracking-normal text-slate-950 dark:text-slate-50">
                  继续练习以生成稳定画像
                </h2>
                <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-600 dark:text-slate-400">
                  完成一次练习后，系统会根据作答更新掌握度、复习提醒和下一步建议。
                </p>
              </div>
              <div className="flex shrink-0 flex-wrap gap-2">
                <SaveRequiredButton onClick={() => onSaveRequired("打开练习中心")} className="h-10 rounded-lg bg-slate-950 px-4 text-sm font-semibold text-white hover:bg-slate-800 dark:bg-white dark:text-slate-950 dark:hover:bg-slate-200">
                  <FileText className="h-4 w-4" />
                  去练习中心
                </SaveRequiredButton>
              </div>
            </div>

            <div className="mt-5 flex flex-wrap gap-2">
              <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-700 dark:bg-slate-800 dark:text-slate-300">
                网页练习
              </span>
              <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-700 dark:bg-slate-800 dark:text-slate-300">
                约 10 题
              </span>
              <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-700 dark:bg-slate-800 dark:text-slate-300">
                中等难度
              </span>
            </div>

            <div className="mt-auto grid grid-cols-2 gap-3 border-t border-slate-100 pt-4 dark:border-slate-800">
              <div>
                <p className="text-xs font-semibold text-slate-400 dark:text-slate-500">画像记录</p>
                <p className="mt-1 text-lg font-black tabular-nums text-slate-950 dark:text-slate-50">{formatStat(masteryCount)}</p>
              </div>
              <div>
                <p className="text-xs font-semibold text-slate-400 dark:text-slate-500">测验记录</p>
                <p className="mt-1 text-lg font-black tabular-nums text-slate-950 dark:text-slate-50">{formatStat(paperCount)}</p>
              </div>
            </div>
          </section>

          <section className="grid grid-cols-2 overflow-hidden rounded-lg border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-950/70">
            <div className="border-b border-r border-slate-200 dark:border-slate-800">
              <SharedSummaryMetric label="平均掌握" value={masteryCount > 0 ? "0%" : "暂无"} hint="按已诊断记录统计" icon={<Gauge className="h-5 w-5" />} tone="indigo" />
            </div>
            <div className="border-b border-slate-200 dark:border-slate-800">
              <SharedSummaryMetric label="做题正确" value="暂无" hint={`${formatStat(paperCount)} 次测验`} icon={<Trophy className="h-5 w-5" />} tone="emerald" />
            </div>
            <div className="col-span-2 border-b border-slate-200 dark:border-slate-800">
              <div className="p-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-xs font-semibold text-slate-500 dark:text-slate-400">优先补哪里</p>
                    <p className="mt-1 text-sm font-bold text-slate-950 dark:text-slate-50">还没有明确要补的点</p>
                  </div>
                  <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-rose-50 text-rose-600 dark:bg-rose-500/10 dark:text-rose-300">
                    <Target className="h-5 w-5" />
                  </span>
                </div>
                <p className="mt-3 text-xs leading-5 text-slate-500 dark:text-slate-400">
                  完成一次练习后，系统会把需要优先补的知识点排出来。
                </p>
                <p className="mt-3 text-xs leading-5 text-slate-500 dark:text-slate-400">
                  暂无可诊断的薄弱范围。
                </p>
              </div>
            </div>
            <div className="col-span-2">
              <SharedSummaryMetric label="复习提醒" value="0" hint="需要回顾的知识点" icon={<CalendarClock className="h-5 w-5" />} />
            </div>
          </section>
        </div>

        <div id="profile-mastery-section" className="grid scroll-mt-24 gap-4 xl:grid-cols-2">
          <section className="border-t border-slate-200 py-6 dark:border-slate-800">
            <SharedSectionHeading
              icon={<Target className="h-4 w-4" />}
              title="知识点掌握"
              detail="按掌握度、复习优先级和课程重点排序。"
              action={(
                <Button type="button" variant="outline" size="sm" onClick={() => onViewChange("knowledge-docs")} className="h-8 rounded-lg px-3 text-xs">
                  <BookOpen className="h-3.5 w-3.5" />
                  看知识库
                </Button>
              )}
            />
            <div className="mt-4">
              <SharedEmptyBlock
                icon={<Target className="h-5 w-5" />}
                title="还没有掌握度判断"
                detail="完成一次练习后，系统会根据作答更新每个知识点的掌握度。"
              />
            </div>
          </section>

          <section className="border-t border-slate-200 py-6 dark:border-slate-800">
            <SharedSectionHeading
              icon={<CalendarClock className="h-4 w-4" />}
              title="复习安排"
              detail="需要回顾和刚完成的任务会保留在这里。"
            />
            <div className="mt-4">
              <SharedEmptyBlock
                icon={<CheckCircle2 className="h-5 w-5" />}
                title="暂无待办"
                detail="当前没有到期复习任务，继续保持练习节奏。"
              />
            </div>
          </section>
        </div>

        <div className="grid gap-4 xl:grid-cols-[minmax(0,0.95fr)_minmax(360px,1.05fr)]">
          {planDocuments.length ? (
            <section className="border-t border-slate-200 py-6 dark:border-slate-800">
              <SharedSectionHeading
                icon={<CalendarClock className="h-4 w-4" />}
                title="今日行动"
                detail="按定位、练习、复盘排好顺序。"
              />
              <ol className="mt-4 space-y-3">
                {planDocuments.map((doc, index) => (
                  <li key={doc.doc_id} className="grid gap-3 border-b border-slate-100 px-1 py-3 last:border-b-0 dark:border-slate-800 sm:grid-cols-[5rem_minmax(0,1fr)]">
                    <div className="flex items-center gap-2 sm:flex-col sm:items-start sm:gap-1">
                      <span className="inline-flex h-6 w-6 items-center justify-center rounded-md bg-slate-100 text-[11px] font-black tabular-nums text-slate-500 dark:bg-slate-900 dark:text-slate-400">
                        {String(index + 1).padStart(2, "0")}
                      </span>
                      <span className="text-xs font-bold text-slate-500 dark:text-slate-400">{index === 0 ? "定位" : index === 1 ? "练习" : "复盘"}</span>
                    </div>
                    <div className="min-w-0">
                      <p className="truncate text-sm font-bold text-slate-950 dark:text-slate-100">{doc.title}</p>
                      <p className="mt-1 line-clamp-2 text-sm leading-6 text-slate-500 dark:text-slate-400">
                        {formatSharedPreviewText(doc.summary || doc.excerpt, "回看知识库文档，补齐这部分内容。")}
                      </p>
                    </div>
                  </li>
                ))}
              </ol>
            </section>
          ) : null}

          <section className="border-t border-slate-200 py-6 dark:border-slate-800">
            <SharedSectionHeading
              icon={<FileText className="h-4 w-4" />}
              title="最近测验"
              action={(
                <Button type="button" variant="ghost" size="sm" onClick={() => onViewChange("exams")} className="h-8 px-2 text-xs">
                  全部
                  <ArrowRight className="h-3.5 w-3.5" />
                </Button>
              )}
            />
            <div className="mt-3 space-y-1">
              {paperCount > 0 ? (
                <button
                  type="button"
                  onClick={() => onSaveRequired("打开历史测验")}
                  className="group flex w-full items-center justify-between gap-4 rounded-lg px-3 py-3 text-left transition hover:bg-slate-50 dark:hover:bg-slate-900"
                >
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="h-2 w-2 shrink-0 rounded-full bg-emerald-500" />
                      <p className="truncate text-sm font-semibold text-slate-900 dark:text-slate-100">历史测验记录</p>
                    </div>
                    <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">整卷检测 · {formatStat(paperCount)} 份记录</p>
                  </div>
                  <ArrowRight className="h-4 w-4 shrink-0 text-slate-300 transition group-hover:translate-x-0.5 group-hover:text-indigo-500" />
                </button>
              ) : (
                <SharedEmptyBlock
                  icon={<FileText className="h-5 w-5" />}
                  title="暂无测验记录"
                  detail="完成一次测验后，这里会显示分数和进入入口。"
                />
              )}
            </div>
          </section>
        </div>

        <section className="border-y border-slate-200 dark:border-slate-800">
          <button
            type="button"
            onClick={() => setIsProfileExpanded((value) => !value)}
            className="flex w-full items-center justify-between gap-4 px-5 py-4 text-left text-sm font-bold text-slate-950 transition hover:bg-slate-50 dark:text-slate-100 dark:hover:bg-slate-900/60"
          >
            <span className="flex items-center gap-2">
              <Gauge className="h-4 w-4 text-slate-400" />
              更多画像细节
            </span>
            <span className="flex items-center gap-1 text-xs font-semibold text-slate-500 dark:text-slate-400">
              {isProfileExpanded ? "收起" : "展开"}
              <ChevronRight className={cn("h-4 w-4 transition-transform", isProfileExpanded && "rotate-90")} />
            </span>
          </button>

          {isProfileExpanded ? (
            <div className="grid gap-4 border-t border-slate-200 p-5 dark:border-slate-800 lg:grid-cols-3">
              <div className="rounded-lg border border-slate-100 p-4 dark:border-slate-800">
                <p className="text-sm font-bold text-slate-950 dark:text-slate-100">掌握分布</p>
                <p className="mt-4 text-xs leading-5 text-slate-500 dark:text-slate-400">
                  暂无掌握度分布数据。
                </p>
              </div>

              <div className="space-y-4 rounded-lg border border-slate-100 p-4 dark:border-slate-800">
                <div>
                  <p className="text-sm font-bold text-slate-950 dark:text-slate-100">题型正确率</p>
                  <p className="mt-2 text-xs leading-5 text-slate-500 dark:text-slate-400">暂无题型表现数据。</p>
                </div>
                <div>
                  <p className="text-sm font-bold text-slate-950 dark:text-slate-100">难度正确率</p>
                  <p className="mt-2 text-xs leading-5 text-slate-500 dark:text-slate-400">暂无难度表现数据。</p>
                </div>
              </div>

              <div className="space-y-3 rounded-lg border border-slate-100 p-4 dark:border-slate-800">
                <p className="text-sm font-bold text-slate-950 dark:text-slate-100">偏好与备注</p>
                <label className="block">
                  <span className="text-xs font-semibold text-slate-500 dark:text-slate-400">我的学习偏好</span>
                  <textarea
                    value=""
                    readOnly
                    onFocus={() => onSaveRequired("编辑学习偏好")}
                    rows={3}
                    placeholder="例如：先看例题再总结规律，多提醒易错点。"
                    className="mt-2 w-full resize-none rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs leading-5 text-slate-700 outline-none transition placeholder:text-slate-400 focus:border-indigo-300 focus:bg-white focus:ring-2 focus:ring-indigo-100 dark:border-slate-800 dark:bg-slate-900/70 dark:text-slate-200 dark:placeholder:text-slate-600 dark:focus:border-indigo-500/40 dark:focus:bg-slate-950 dark:focus:ring-indigo-500/10"
                  />
                </label>
                <div className="rounded-lg border border-slate-100 bg-slate-50/70 px-3 py-2 text-xs leading-5 text-slate-500 dark:border-slate-800 dark:bg-slate-900/40 dark:text-slate-400">
                  推荐题型：单选题、简答题
                </div>
                <div className="rounded-lg border border-slate-100 bg-slate-50/70 px-3 py-2 text-xs leading-5 text-slate-500 dark:border-slate-800 dark:bg-slate-900/40 dark:text-slate-400">
                  对话记忆：暂无足够对话信号
                </div>
              </div>
            </div>
          ) : null}
        </section>
      </div>
    </div>
  );
}
export function CourseSharePage() {
  const params = useParams<{ token: string }>();
  const token = params.token ?? "";
  const shareAssetBaseUrl = token ? `/api/v1/course-shares/${encodeURIComponent(token)}/assets` : "";
  const location = useLocation();
  const navigate = useNavigate();
  const authSessionQuery = useAuthSession();
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const [searchParams, setSearchParams] = useSearchParams();
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const [scrollElement, setScrollElement] = useState<HTMLDivElement | null>(null);
  const [isMobileTocOpen, setIsMobileTocOpen] = useState(false);
  const [isTocCollapsed, setIsTocCollapsed] = useState(false);
  const [pageWideMode, setPageWideMode] = useState(false);
  const [savePromptFeature, setSavePromptFeature] = useState<string | null>(null);

  useEffect(() => {
    const existingMeta = document.head.querySelector<HTMLMetaElement>('meta[name="referrer"]');
    const previousContent = existingMeta?.content;
    const meta = existingMeta ?? document.createElement("meta");
    const existingRobotsMeta = document.head.querySelector<HTMLMetaElement>('meta[name="robots"]');
    const previousRobotsContent = existingRobotsMeta?.content;
    const robotsMeta = existingRobotsMeta ?? document.createElement("meta");
    if (!existingMeta) {
      meta.name = "referrer";
      document.head.appendChild(meta);
    }
    if (!existingRobotsMeta) {
      robotsMeta.name = "robots";
      document.head.appendChild(robotsMeta);
    }
    meta.content = "no-referrer";
    robotsMeta.content = "noindex,nofollow,noarchive";
    return () => {
      if (existingMeta) {
        existingMeta.content = previousContent ?? "";
      } else {
        meta.remove();
      }
      if (existingRobotsMeta) {
        existingRobotsMeta.content = previousRobotsContent ?? "";
      } else {
        robotsMeta.remove();
      }
    };
  }, []);

  const previewQuery = useQuery({
    queryKey: ["course-share-preview", token],
    queryFn: async ({ signal }): Promise<CourseSharePreviewData> => {
      const response = await anonymousApiClient<ApiResponse<CourseSharePreviewData>>(
        `/api/v1/course-shares/${encodeURIComponent(token)}`,
        {
          method: "GET",
          cache: "no-store",
          signal,
        },
      );
      if (!response.data) throw new Error("分享链接不存在");
      return response.data;
    },
    retry: false,
    enabled: Boolean(token),
  });

  const preview = previewQuery.data;
  const documents = preview?.documents ?? [];
  const activeShareView = useMemo(() => normalizeShareView(searchParams.get("view")), [searchParams]);
  const isKnowledgeView = activeShareView === "knowledge-docs";
  const selectedDocId = useMemo(
    () => pickSelectedDocId(documents, searchParams.get("doc")),
    [documents, searchParams],
  );
  const selectedDocPreview = documents.find((doc) => doc.doc_id === selectedDocId) ?? documents[0] ?? null;

  useEffect(() => {
    const container = scrollElement ?? scrollRef.current;
    if (container) container.scrollTop = 0;
  }, [activeShareView, scrollElement, selectedDocId]);

  const documentQuery = useQuery({
    queryKey: ["course-share-document", token, selectedDocId],
    queryFn: async ({ signal }): Promise<CourseShareDocumentContent> => {
      const response = await anonymousApiClient<ApiResponse<CourseShareDocumentContent>>(
        `/api/v1/course-shares/${encodeURIComponent(token)}/documents/${encodeURIComponent(selectedDocId)}`,
        {
          method: "GET",
          cache: "no-store",
          signal,
        },
      );
      if (!response.data) throw new Error("文档不存在");
      return response.data;
    },
    retry: false,
    enabled: Boolean(isKnowledgeView && token && selectedDocId && preview?.can_import),
  });

  const documentContent = documentQuery.data?.content_markdown?.trim() || selectedDocPreview?.excerpt || "";
  const bindScrollContainer = useCallback((node: HTMLDivElement | null) => {
    scrollRef.current = node;
    setScrollElement(node);
  }, []);
  const {
    tocTree,
    activeHeading,
    collapsedTocIds,
    setCollapsedTocIds,
    toggleTocCollapse,
    scrollToHeading,
    bindTocNav,
  } = useDocToc(isKnowledgeView ? documentContent : "", scrollRef, scrollElement);
  const collapsibleTocIds = useMemo(() => collectCollapsibleTocIds(tocTree), [tocTree]);
  const pageShellMaxWidthClass = pageWideMode ? "max-w-none" : "max-w-[1120px]";
  const docColumnMaxWidthClass = pageWideMode ? "max-w-none" : "max-w-[980px]";

  const importMutation = useMutation({
    mutationFn: async (): Promise<ImportResultData> => {
      const response = await apiClient<ApiResponse<ImportResultData>>({
        method: "POST",
        url: `/api/v1/course-shares/${encodeURIComponent(token)}/import`,
        data: {},
      });
      if (!response.data) throw new Error("保存失败");
      return response.data;
    },
    onSuccess: async (data) => {
      await queryClient.invalidateQueries({ queryKey: ["courses"] });
      navigate(buildCoursePath(data.course_id, "knowledge-docs"));
    },
  });

  const changeShareView = useCallback((view: ShareView) => {
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      if (view === "knowledge-docs") {
        next.delete("view");
      } else {
        next.set("view", view);
        next.delete("doc");
      }
      return next;
    });
    setIsMobileTocOpen(false);
  }, [setSearchParams]);

  const selectDocument = useCallback((docId: string) => {
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      next.delete("view");
      next.set("doc", docId);
      return next;
    });
    setIsMobileTocOpen(false);
  }, [setSearchParams]);

  const openLogin = useCallback(() => {
    const returnTo = `${location.pathname}${location.search}${location.hash}`;
    const authParams = new URLSearchParams({
      auth: "login",
      returnTo,
    });
    navigate({
      pathname: "/",
      search: `?${authParams.toString()}`,
    });
  }, [location.hash, location.pathname, location.search, navigate]);

  const expandAllTocLevels = useCallback(() => {
    setCollapsedTocIds(new Set());
  }, []);

  const collapseAllTocLevels = useCallback(() => {
    setCollapsedTocIds(new Set(collapsibleTocIds));
  }, [collapsibleTocIds]);

  const promptSaveForFullInteraction = useCallback((feature: string) => {
    setSavePromptFeature(feature);
    toast({
      title: `${feature}需要保存课程`,
      description: "共享链接是只读预览。保存到我的课程后，可以继续使用完整课程交互。",
      variant: "info",
      duration: 8000,
    });
  }, [toast]);

  const renderTocNodes = useCallback((nodes: TocTreeNode[], depth = 0): ReactNode => {
    return nodes.map((node) => {
      const { item } = node;
      const hasChildren = node.children.length > 0;
      const isCollapsed = collapsedTocIds.has(item.id);
      const isActive = activeHeading === item.id;
      const indent = depth * 12;
      const displayText = splitTocDisplayText(item.text);

      return (
        <div key={item.id}>
          <div
            data-toc-id={item.id}
            className={cn(
              "group relative my-px flex min-h-8 items-center overflow-hidden rounded-md transition-colors duration-150",
              isActive
                ? "bg-[#EAF2FF] text-[#245BDB] dark:bg-blue-500/15 dark:text-blue-300"
                : "text-[#4E5969] hover:bg-[#F2F3F5] hover:text-[#1F2329] dark:text-slate-400 dark:hover:bg-slate-800/70 dark:hover:text-slate-100",
            )}
            style={{ paddingLeft: indent + 8 }}
          >
            {isActive ? (
              <span
                className="absolute top-1/2 h-[18px] w-0.5 -translate-y-1/2 rounded-full bg-[#3370FF] dark:bg-blue-400"
                style={{ left: indent + 2 }}
              />
            ) : null}

            {hasChildren ? (
              <button
                type="button"
                onClick={(event) => {
                  event.stopPropagation();
                  toggleTocCollapse(item.id);
                }}
                className={cn(
                  "flex h-5 w-5 shrink-0 items-center justify-center rounded transition-colors",
                  isActive
                    ? "text-[#3370FF] hover:bg-blue-100/70 dark:text-blue-300 dark:hover:bg-blue-500/20"
                    : "text-slate-400 hover:bg-slate-200/60 hover:text-slate-600 dark:text-slate-500 dark:hover:bg-slate-800 dark:hover:text-slate-300",
                )}
                title={isCollapsed ? `展开：${item.text}` : `收起：${item.text}`}
                aria-label={isCollapsed ? `展开：${item.text}` : `收起：${item.text}`}
              >
                <ChevronRight className={cn("h-3.5 w-3.5 transition-transform duration-200", !isCollapsed && "rotate-90")} />
              </button>
            ) : (
              <span className="w-5 shrink-0" />
            )}

            <button
              type="button"
              onClick={() => scrollToHeading(item.id)}
              title={item.text}
              aria-label={`跳转到：${item.text}`}
              className={cn(
                "min-w-0 flex-1 truncate py-1.5 pr-1 text-left text-[13.5px] leading-5 transition-colors",
                isActive
                  ? "font-medium text-[#245BDB] dark:text-blue-300"
                  : item.level === 1
                    ? "font-semibold text-slate-800 dark:text-slate-100"
                    : "font-normal text-slate-700 dark:text-slate-300",
                item.level === 1 && "text-[14.5px]",
                item.level >= 3 && "text-[13.5px]",
              )}
            >
              {displayText.number ? (
                <span className={cn(
                  "mr-1.5 select-none font-medium",
                  isActive ? "text-[#3370FF] dark:text-blue-300" : "text-[#8F959E] dark:text-slate-500",
                )}>
                  {displayText.number}
                </span>
              ) : null}
              <span>{displayText.title}</span>
            </button>
          </div>

          {hasChildren && !isCollapsed ? (
            <div className="overflow-hidden">{renderTocNodes(node.children, depth + 1)}</div>
          ) : null}
        </div>
      );
    });
  }, [activeHeading, collapsedTocIds, scrollToHeading, toggleTocCollapse]);

  const renderTocNav = (showBulkControls: boolean) => {
    const canExpandAllTocLevels = collapsedTocIds.size > 0;
    const canCollapseAllTocLevels = collapsibleTocIds.size > 0 && collapsedTocIds.size < collapsibleTocIds.size;

    return (
      <div className="relative h-full">
        <nav
          ref={showBulkControls === isMobileTocOpen
            ? bindTocNav
            : undefined}
          className={cn("toc-scroll h-full overflow-y-auto pr-2", showBulkControls ? "py-2" : "pb-2 pt-0")}
        >
          {showBulkControls && tocTree.length > 0 ? (
            <div className="sticky top-0 z-10 mb-1 flex h-8 items-center justify-end bg-white/95 px-1 pb-1 pt-0.5 backdrop-blur dark:bg-slate-950/95">
              <div className="flex items-center gap-0.5 text-slate-400">
                <button
                  type="button"
                  onClick={expandAllTocLevels}
                  disabled={!canExpandAllTocLevels}
                  className="inline-flex h-6 w-6 items-center justify-center rounded-[4px] transition hover:bg-slate-100 hover:text-slate-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400 disabled:cursor-default disabled:opacity-30 disabled:hover:bg-transparent disabled:hover:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-200 dark:focus-visible:ring-indigo-500"
                  aria-label="展开所有目录层级"
                  title="展开所有层级"
                >
                  <ListTree className="h-4 w-4" />
                </button>
                <button
                  type="button"
                  onClick={collapseAllTocLevels}
                  disabled={!canCollapseAllTocLevels}
                  className="inline-flex h-6 w-6 items-center justify-center rounded-[4px] transition hover:bg-slate-100 hover:text-slate-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400 disabled:cursor-default disabled:opacity-30 disabled:hover:bg-transparent disabled:hover:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-200 dark:focus-visible:ring-indigo-500"
                  aria-label="收起所有目录层级"
                  title="收起所有层级"
                >
                  <ListCollapse className="h-4 w-4" />
                </button>
              </div>
            </div>
          ) : null}
          {tocTree.length > 0 ? renderTocNodes(tocTree) : (
            <div className="px-3 py-4 text-center text-xs text-slate-400">暂无目录</div>
          )}
        </nav>
      </div>
    );
  };

  const importError = importMutation.isError
    ? getApiErrorMessage(importMutation.error, "保存失败，请稍后重试")
    : "";
  const canSaveWithCurrentSession = Boolean(
    preview?.can_import && authSessionQuery.data?.current_user?.is_authenticated,
  );
  const saveRequiresLogin = Boolean(preview?.can_import && !canSaveWithCurrentSession);
  const saveLoginMessage = "请先登录或注册后再保存课程到自己的账号。";
  const requiresLogin = importError.includes("登录") || importError.includes("注册") || importError.includes("AUTH_REQUIRED");
  const unavailableText = preview?.status === "expired"
    ? "这个分享链接已经过期。"
    : preview?.status === "revoked"
      ? "创建者已经撤销这个分享链接。"
      : "这个分享链接当前不可用。";
  const handleSave = () => {
    if (saveRequiresLogin) {
      openLogin();
      return;
    }
    if (preview?.can_import) {
      importMutation.mutate();
    }
  };

  if (previewQuery.isLoading) {
    return (
      <div className="flex min-h-dvh items-center justify-center bg-white px-6 text-slate-500 dark:bg-slate-950 dark:text-slate-400">
        <section className="w-full max-w-sm text-center">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full border border-slate-200 bg-slate-50 text-indigo-500 shadow-sm dark:border-slate-800 dark:bg-slate-900 dark:text-indigo-300">
            <Loader2 className="h-5 w-5 animate-spin" />
          </div>
          <h1 className="mt-4 text-base font-semibold text-slate-900 dark:text-slate-100">正在读取共享课程</h1>
          <p className="mt-2 text-sm leading-6 text-slate-500 dark:text-slate-400">
            正在加载课程快照和知识文档，首次打开可能需要多等几秒。
          </p>
          <div className="mt-6 space-y-2" aria-hidden="true">
            <div className="mx-auto h-2.5 w-full max-w-[280px] animate-pulse rounded-full bg-slate-100 dark:bg-slate-800" />
            <div className="mx-auto h-2.5 w-4/5 animate-pulse rounded-full bg-slate-100 dark:bg-slate-800" />
            <div className="mx-auto h-2.5 w-2/3 animate-pulse rounded-full bg-slate-100 dark:bg-slate-800" />
          </div>
        </section>
      </div>
    );
  }

  if (!preview) {
    return (
      <div className="flex min-h-dvh items-center justify-center bg-white px-6 text-slate-950 dark:bg-slate-950 dark:text-slate-50">
        <section className="w-full max-w-md rounded-lg border border-red-200 bg-red-50 p-5 text-sm text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
          <div className="flex items-center gap-2 text-base font-semibold">
            <AlertCircle className="h-5 w-5" />
            分享链接无法打开
          </div>
          <p className="mt-3 leading-6">{getApiErrorMessage(previewQuery.error, "请确认链接是否完整，或让创建者重新分享。")}</p>
        </section>
      </div>
    );
  }

  return (
    <div className="relative flex h-full min-h-0 flex-1 w-full flex-col overflow-hidden bg-slate-50 dark:bg-slate-900">
      <CourseSharePillTitle
        courseName={preview.course_name}
        activeView={activeShareView}
        isSaving={importMutation.isPending}
        canSave={Boolean(preview?.can_import)}
        importError={importError}
        saveLabel={saveRequiresLogin ? "登录后保存" : "保存到我的课程"}
        saveDescription={saveRequiresLogin ? "公开预览可直接浏览" : "导入后继续训练和编辑"}
        onSave={handleSave}
        onViewChange={changeShareView}
        className="z-40 shrink-0 bg-white/92 backdrop-blur-md transition-all duration-300 ease-in-out dark:bg-slate-900/92"
        innerClassName="max-md:left-3"
      />

      {saveRequiresLogin && !importError ? (
        <div className="flex flex-wrap items-center justify-center gap-2 border-b border-amber-200 bg-amber-50 px-4 py-2 text-center text-sm text-amber-800 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200">
          <span className="inline-flex items-center gap-2">
            <LogIn className="h-4 w-4" />
            公开内容可直接浏览；登录或注册后可以保存到自己的课程继续训练。
          </span>
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={openLogin}
            className="h-11 rounded-lg border-amber-300 bg-white px-3 text-xs font-semibold text-amber-800 hover:bg-amber-100 dark:border-amber-500/40 dark:bg-slate-950 dark:text-amber-200 dark:hover:bg-amber-500/10"
          >
            登录 / 注册
          </Button>
        </div>
      ) : null}

      {importError ? (
        <div className="flex flex-wrap items-center justify-center gap-2 border-b border-amber-200 bg-amber-50 px-4 py-2 text-center text-sm text-amber-800 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200">
          {requiresLogin ? (
            <>
              <span className="inline-flex items-center gap-2">
                <LogIn className="h-4 w-4" />
                {saveLoginMessage}
              </span>
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={openLogin}
                className="h-11 rounded-lg border-amber-300 bg-white px-3 text-xs font-semibold text-amber-800 hover:bg-amber-100 dark:border-amber-500/40 dark:bg-slate-950 dark:text-amber-200 dark:hover:bg-amber-500/10"
              >
                登录 / 注册
              </Button>
            </>
          ) : importError}
        </div>
      ) : null}

      {!preview.can_import ? (
        <div className="border-b border-red-200 bg-red-50 px-4 py-2 text-center text-sm text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
          {unavailableText}
        </div>
      ) : null}

      {savePromptFeature ? (
        <div className="flex items-center justify-center gap-3 border-b border-indigo-200 bg-indigo-50 px-4 py-2 text-center text-sm text-indigo-800 dark:border-indigo-500/30 dark:bg-indigo-500/10 dark:text-indigo-200">
          <span className="inline-flex items-center gap-2">
            <Lock className="h-4 w-4" />
            {savePromptFeature}需要先保存到我的课程。
          </span>
          {canSaveWithCurrentSession ? (
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={importMutation.isPending}
              onClick={() => importMutation.mutate()}
              className="h-7 rounded-lg border-indigo-200 bg-white px-2.5 text-xs font-semibold text-indigo-700 hover:bg-indigo-50 dark:border-indigo-500/30 dark:bg-slate-950 dark:text-indigo-200 dark:hover:bg-indigo-500/10"
            >
              {importMutation.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
              保存课程
            </Button>
          ) : saveRequiresLogin ? (
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={openLogin}
              className="h-11 rounded-lg border-indigo-200 bg-white px-3 text-xs font-semibold text-indigo-700 hover:bg-indigo-50 dark:border-indigo-500/30 dark:bg-slate-950 dark:text-indigo-200 dark:hover:bg-indigo-500/10"
            >
              登录 / 注册
            </Button>
          ) : null}
        </div>
      ) : null}

      <div className="relative z-10 flex min-h-0 flex-1 w-full bg-white dark:bg-slate-900">
        {isKnowledgeView && tocTree.length > 0 ? (
          <div className="fixed left-3 top-[calc(4.75rem+env(safe-area-inset-top))] z-[79] flex items-center gap-2 lg:hidden">
            <button
              type="button"
              onClick={() => setIsMobileTocOpen(true)}
              className={cn(
                "flex h-10 w-10 items-center justify-center rounded-xl border border-slate-200 bg-white/95 shadow-sm backdrop-blur-sm transition-colors dark:border-slate-800 dark:bg-slate-950/92",
                isMobileTocOpen
                  ? "bg-indigo-50 text-indigo-600 dark:bg-indigo-500/10 dark:text-indigo-300"
                  : "text-slate-600 hover:bg-white hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-900 dark:hover:text-slate-100",
              )}
              aria-label="切换目录抽屉"
              title="目录"
            >
              <FileText className="h-4 w-4" />
            </button>
          </div>
        ) : null}

        {isMobileTocOpen ? (
          <>
            <button
              type="button"
              onClick={() => setIsMobileTocOpen(false)}
              className="fixed inset-0 z-[76] bg-slate-900/24 lg:hidden"
              aria-label="关闭抽屉遮罩"
            />
            <aside className="fixed bottom-4 left-3 top-[calc(7.25rem+env(safe-area-inset-top))] z-[78] flex w-[min(20rem,calc(100vw-1.5rem))] flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl transition-transform duration-200 dark:border-slate-800 dark:bg-slate-950 lg:hidden">
              <div className="flex h-11 items-center justify-between border-b border-slate-200/80 px-3 dark:border-slate-800">
                <div className="flex items-center gap-2 text-slate-900 dark:text-slate-100">
                  <FileText className="h-4 w-4" />
                  <span className="text-sm font-semibold">目录</span>
                </div>
                <button
                  type="button"
                  onClick={() => setIsMobileTocOpen(false)}
                  className="flex h-7 w-7 items-center justify-center rounded-lg text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-700 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-200"
                  aria-label="收起目录"
                >
                  <ChevronRight className="h-4 w-4" />
                </button>
              </div>
              <div className="flex-1 overflow-hidden px-1 pb-2">{renderTocNav(true)}</div>
            </aside>
          </>
        ) : null}

        {isKnowledgeView ? (
          <aside
            className={cn(
              "hidden h-full min-h-0 shrink-0 overflow-hidden bg-white/88 backdrop-blur-md transition-[width] duration-300 ease-out dark:bg-slate-950/88 lg:block",
              isTocCollapsed ? "w-[56px]" : "w-[clamp(14rem,16vw,18rem)]",
            )}
          >
          <div className="flex h-full flex-col">
            {isTocCollapsed ? (
              <div className="flex flex-1 items-start justify-start px-2 py-3">
                <button
                  type="button"
                  onClick={() => setIsTocCollapsed(false)}
                  className="flex h-8 w-8 items-center justify-center rounded-lg text-[#4F46E5] transition-colors hover:bg-[#EEF2FF] hover:text-[#4338CA] dark:text-indigo-300 dark:hover:bg-indigo-500/10 dark:hover:text-indigo-200"
                  aria-label="展开目录"
                  title="展开目录"
                >
                  <ChevronsRight className="h-4 w-4" />
                </button>
              </div>
            ) : (
              <>
                <div className="sticky top-0 z-10 flex items-center justify-between bg-white/92 px-3 pb-1 pt-3 backdrop-blur-md dark:bg-slate-950/92">
                  <div className="flex min-w-0 items-center gap-2">
                    <button
                      type="button"
                      onClick={() => setIsTocCollapsed(true)}
                      className="flex h-8 w-8 items-center justify-center rounded-lg text-[#4F46E5] transition-colors hover:bg-[#EEF2FF] hover:text-[#4338CA] dark:text-indigo-300 dark:hover:bg-indigo-500/10 dark:hover:text-indigo-200"
                      aria-label="收起目录"
                      title="收起目录"
                    >
                      <ChevronsLeft className="h-4 w-4" />
                    </button>
                    <span className="truncate text-sm font-semibold text-slate-800 dark:text-slate-100">目录</span>
                  </div>
                </div>
                <div className="min-h-0 flex-1 overflow-hidden px-2 pb-3 pt-0.5">{renderTocNav(false)}</div>
              </>
            )}
          </div>
          </aside>
        ) : null}

        <div className="relative flex min-h-0 min-w-0 max-w-full flex-1 flex-col overflow-x-hidden">
          <div ref={bindScrollContainer} className="relative h-full max-w-full overflow-x-hidden overflow-y-auto doc-scroll-container content-scroll">
            <div className={cn("min-h-full max-w-full px-4 pb-8 pt-4 md:px-6 lg:px-8", !isKnowledgeView && "px-0 pt-0 md:px-0 lg:px-0")}>
              {isKnowledgeView ? (
              <div className={cn("mx-auto flex min-h-full w-full items-start justify-center", pageShellMaxWidthClass)}>
                <div
                  className={cn(
                    "share-doc-content feishu-doc-content min-w-0 w-full max-w-full overflow-x-hidden",
                    docColumnMaxWidthClass,
                  )}
                >
                  <div className="relative flex min-w-0 items-start">
                    <article className="min-w-0 flex-1 px-2 py-2 md:px-4">
                      {documents.length > 1 ? (
                        <div className="mb-4 flex flex-col gap-2 rounded-lg border border-slate-200 bg-slate-50/80 p-3 dark:border-slate-800 dark:bg-slate-950/70 sm:flex-row sm:items-center">
                          <label
                            htmlFor="course-share-document-select"
                            className="shrink-0 text-xs font-semibold text-slate-600 dark:text-slate-300"
                          >
                            课程文档
                          </label>
                          <select
                            id="course-share-document-select"
                            value={selectedDocId}
                            onChange={(event) => selectDocument(event.target.value)}
                            className="h-11 min-w-0 flex-1 rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 outline-none transition focus:border-indigo-400 focus:ring-2 focus:ring-indigo-500/20 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
                          >
                            {documents.map((doc, index) => (
                              <option key={doc.doc_id} value={doc.doc_id}>
                                {index + 1}. {doc.title}
                              </option>
                            ))}
                          </select>
                        </div>
                      ) : null}
                      {documentQuery.isLoading ? (
                        <div className="flex h-48 items-center justify-center text-sm text-slate-500 dark:text-slate-400">
                          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                          正在读取文档...
                        </div>
                      ) : documentQuery.isError ? (
                        <section className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm leading-6 text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
                          {getApiErrorMessage(documentQuery.error, "这篇文档暂时无法打开。")}
                        </section>
                      ) : documentContent ? (
                        <div className="knowledge-doc-markdown">
                          <MarkdownViewer
                            content={documentContent}
                            assetBaseUrl={shareAssetBaseUrl}
                            publicMode
                            allowRawHtml={false}
                            variant="document"
                            headingAnchors
                            headingNumbering
                            collapsibleHeadings
                          />
                        </div>
                      ) : (
                        <section className="rounded-lg border border-dashed border-slate-200 p-6 text-sm leading-6 text-slate-500 dark:border-slate-800 dark:text-slate-400">
                          这门课程当前没有可直接浏览的文档内容。保存到自己的课程后，可以继续查看完整课程资源。
                        </section>
                      )}
                    </article>
                  </div>
                </div>
              </div>
              ) : (
                activeShareView === "build" ? (
                  <SharedReadonlyBuildView
                    preview={preview}
                    documents={documents}
                    onSaveRequired={promptSaveForFullInteraction}
                  />
                ) : activeShareView === "exams" ? (
                  <SharedReadonlyExamsView
                    preview={preview}
                    onSaveRequired={promptSaveForFullInteraction}
                  />
                ) : (
                  <SharedReadonlyProfileView
                    preview={preview}
                    onSaveRequired={promptSaveForFullInteraction}
                    onViewChange={changeShareView}
                  />
                )
              )}
            </div>
          </div>
        </div>

        {isKnowledgeView ? (
          <>
        <button
          type="button"
          onClick={() => setPageWideMode((value) => !value)}
          className={cn(
            FLOATING_ACTION_CLASS,
            "bottom-[7.5rem] z-[88]",
            pageWideMode && "border-indigo-200 bg-indigo-50/95 text-indigo-700 shadow-[0_14px_34px_-22px_rgba(79,70,229,0.45)] dark:border-indigo-500/40 dark:bg-indigo-500/12 dark:text-indigo-200",
          )}
          aria-label={pageWideMode ? "关闭宽页模式" : "开启宽页模式"}
          aria-pressed={pageWideMode}
        >
          <ExternalLink className="h-4 w-4 shrink-0" />
          <span className="hidden truncate sm:inline">{pageWideMode ? "标准宽度" : "宽页模式"}</span>
        </button>

        <button
          type="button"
          onClick={() => promptSaveForFullInteraction("知识图谱")}
          className={cn(FLOATING_ACTION_CLASS, "bottom-6 z-[86]")}
          aria-label="打开知识图谱"
        >
          <Network className="h-4 w-4 shrink-0 text-slate-500 dark:text-slate-400" />
          <span className="hidden truncate sm:inline">知识图谱</span>
        </button>
          </>
        ) : null}

      </div>
    </div>
  );
}
