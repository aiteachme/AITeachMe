import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { BookOpen, CheckCircle2, ChevronDown, ChevronUp, FileText, LayoutTemplate, Loader2, Sparkles, Activity } from "lucide-react";

import { cn } from "../../lib/utils";
import type { FileRecord } from "../../api/generated/model";
import type {
  BuildPreviewChapterProgress,
  BuildPreviewRecentEvent,
  KnowledgeBuildMetrics,
  KnowledgeBuildPreview,
} from "./types";
import { BuildChapterProgress } from "./BuildChapterProgress";
import { BuildMaterialPipeline } from "./BuildMaterialPipeline";
import { BuildMetricsBadges } from "./BuildMetricsBadges";
import { BuildProcessTimeline, useBuildTimelineSteps } from "./BuildProcessTimeline";
import { BuildResearchSources } from "./BuildResearchSources";
import { buildChapterStatusLabel, formatBuildEventTime, normalizeDomainLabel } from "./utils";

interface Props {
  isFetching: boolean;
  progress: number;
  statusText: string;
  buildPreview: KnowledgeBuildPreview | null;
  buildMetrics: KnowledgeBuildMetrics | null;
  sourceFiles: FileRecord[];
  sourceFilesFetching: boolean;
  buildStage: string | null | undefined;
  className?: string;
}

interface WorkspaceStatProps {
  label: string;
  value: string;
  hint: string;
}

const ACTIVE_CHAPTER_STATUSES = new Set(["generating", "enhancing", "reviewing", "drafting", "researching"]);
const STABLE_CHAPTER_STATUSES = new Set(["generated", "enhanced", "reviewed", "completed", "drafted", "researched"]);

const EVENT_STAGE_LABELS: Record<string, string> = {
  build_accepted: "已受理",
  search_only_mode: "联网模式",
  planner_confirmed: "方案确认",
  preparing_docgen_context: "理解资料",
  dispatch_ready: "执行合同",
  building_document_backbone: "文档骨架",
  generating_chapters: "章节写作",
  enhancing_chapters: "章节增强",
  chapters_enhanced: "增强完成",
  reviewing_content: "复核中",
  content_reviewed: "复核完成",
  repairing_or_routing: "回流处理",
  repair_routed: "回流记录",
  merge_reviewed: "整本检查",
  titles_finalized: "标题收口",
  publishing: "发布中",
  completed: "已发布",
};

function isActiveChapter(status: string | undefined): boolean {
  return ACTIVE_CHAPTER_STATUSES.has((status ?? "").trim());
}

function isStableChapter(status: string | undefined): boolean {
  return STABLE_CHAPTER_STATUSES.has((status ?? "").trim());
}

function uniqueCompact(items: string[]): string[] {
  const seen = new Set<string>();
  const values: string[] = [];
  for (const item of items) {
    const value = String(item ?? "").trim();
    if (!value) continue;
    const key = value.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    values.push(value);
  }
  return values;
}

function pickSpotlightChapter(chapters: BuildPreviewChapterProgress[]): BuildPreviewChapterProgress | null {
  const active = chapters.find((chapter) => isActiveChapter(chapter.status));
  if (active) return active;
  const stable = [...chapters]
    .filter((chapter) => isStableChapter(chapter.status))
    .sort((left, right) => (right.word_count ?? 0) - (left.word_count ?? 0))[0];
  if (stable) return stable;
  return chapters[0] ?? null;
}

function collectSignalDomains(events: BuildPreviewRecentEvent[]): string[] {
  return uniqueCompact(
    events.flatMap((event) => {
      const fromUrls = (event.source_urls ?? []).map((url) => normalizeDomainLabel(url));
      const fromDomains = (event.domains ?? []).map((domain) => normalizeDomainLabel(domain));
      return [...fromUrls, ...fromDomains];
    }),
  );
}

function resolveStepSummary(stepTitle: string, sourceFiles: FileRecord[], chapters: BuildPreviewChapterProgress[]): string {
  if (sourceFiles.length === 0) {
    return `${stepTitle}已启动，当前没有本地资料可复用，本轮会优先依赖联网研究来补齐知识框架。`;
  }
  if (chapters.length === 0) {
    return `${stepTitle}已启动，系统会先理解资料范围与章节边界，再逐步露出大纲与正文片段。`;
  }
  return `${stepTitle}已启动，工作台会优先展示已经稳定的中间产物，避免界面在阶段切换时突然清空。`;
}

function WorkspaceStat({ label, value, hint }: WorkspaceStatProps) {
  return (
    <div className="rounded-[22px] border border-white/60 bg-white/70 px-4 py-3 shadow-sm backdrop-blur-md">
      <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-zinc-500">{label}</p>
      <p className="mt-2 text-lg font-semibold text-zinc-900">{value}</p>
      <p className="mt-1 text-[12px] leading-5 text-zinc-600">{hint}</p>
    </div>
  );
}

// Artifact Canvas Inner Component
function ArtifactCanvas({
  buildPreview,
  chapters,
  events,
  sourceFiles,
  currentStepTitle,
  currentStepDescription,
}: {
  buildPreview: KnowledgeBuildPreview | null;
  chapters: BuildPreviewChapterProgress[];
  events: BuildPreviewRecentEvent[];
  sourceFiles: FileRecord[];
  currentStepTitle: string;
  currentStepDescription: string;
}) {
  const chapterTitles = uniqueCompact([
    ...(buildPreview?.latest_chapter_titles ?? []),
    ...chapters.map((chapter) => chapter.title),
  ]).slice(0, 6);
  const draftExcerpt = buildPreview?.draft_excerpt?.trim() ?? "";
  const planSummary = buildPreview?.plan_summary?.trim() ?? "";
  const sampleCards = (buildPreview?.sample_cards ?? []).slice(0, 3);
  const spotlightChapter = pickSpotlightChapter(chapters);
  const activeCount = chapters.filter((chapter) => isActiveChapter(chapter.status)).length;
  const stableCount = chapters.filter((chapter) => isStableChapter(chapter.status)).length;
  const sourceNames = sourceFiles.map((file) => file.filename.trim()).filter(Boolean).slice(0, 4);
  const lastEvent = events[0] ?? null;
  const fallbackSummary = resolveStepSummary(currentStepTitle, sourceFiles, chapters);

  return (
    <section className="relative overflow-hidden rounded-[32px] border border-white/60 bg-white/50 backdrop-blur-xl shadow-[0_30px_90px_-72px_rgba(28,25,23,0.1)]">
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_right,rgba(56,189,248,0.1),transparent_40%),radial-gradient(circle_at_bottom_left,rgba(99,102,241,0.06),transparent_40%)]" />

      <div className="relative px-5 py-5 md:px-7 md:py-6">
        <div className="flex flex-col gap-4 border-b border-zinc-200/50 pb-5 xl:flex-row xl:items-start xl:justify-between">
          <div className="max-w-2xl">
            <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-zinc-400">Artifact Canvas</p>
            <h2 className="mt-2 text-[22px] font-semibold tracking-tight text-zinc-950">知识文档正在成形</h2>
            <p className="mt-2 text-sm leading-6 text-zinc-600">
              {currentStepDescription || fallbackSummary}
            </p>
          </div>

          <div className="rounded-[24px] border border-white/60 bg-white/70 p-4 shadow-sm backdrop-blur-md xl:max-w-[320px]">
            <div className="flex items-center gap-2 text-zinc-900">
              <Sparkles className="h-4 w-4 text-sky-500" />
              <span className="text-sm font-semibold">当前焦点</span>
            </div>
            <p className="mt-3 text-sm font-medium leading-6 text-zinc-800">
              {spotlightChapter
                ? `${String(spotlightChapter.chapter_index).padStart(2, "0")} · ${spotlightChapter.title}`
                : "系统正在先搭稳定骨架，再暴露正文片段。"}
            </p>
            <p className="mt-1 text-[12px] leading-5 text-zinc-500">
              {spotlightChapter
                ? `当前状态：${buildChapterStatusLabel(spotlightChapter.status)}`
                : "先出现章节结构，随后才会出现逐段增长的正文预览。"}
            </p>
          </div>
        </div>

        <div className="mt-5 grid gap-5 xl:grid-cols-[minmax(0,1.08fr)_minmax(320px,0.92fr)]">
          <div className="space-y-4">
            <section className="rounded-[28px] border border-white/60 bg-white/70 p-5 shadow-sm backdrop-blur-md">
              <div className="flex items-center gap-2 text-zinc-900">
                <BookOpen className="h-4 w-4 text-zinc-500" />
                <h3 className="text-sm font-semibold">学习骨架</h3>
              </div>

              <p
                className="mt-4 text-[14px] leading-7 text-zinc-600"
                style={{ fontFamily: "var(--font-serif)" }}
              >
                {planSummary || fallbackSummary}
              </p>

              {chapterTitles.length > 0 ? (
                <div className="mt-5 grid gap-2 sm:grid-cols-2">
                  {chapterTitles.map((title, index) => (
                    <motion.div
                      key={title}
                      initial={{ opacity: 0, x: -6 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ delay: index * 0.05, duration: 0.22 }}
                      className="rounded-2xl border border-white/50 bg-white/40 px-3 py-2"
                    >
                      <div className="flex items-start gap-2">
                        <span className="mt-0.5 text-[11px] font-medium text-zinc-400">
                          {String(index + 1).padStart(2, "0")}
                        </span>
                        <span className="text-[13px] leading-6 text-zinc-700">{title}</span>
                      </div>
                    </motion.div>
                  ))}
                </div>
              ) : null}

              {sampleCards.length > 0 ? (
                <div className="mt-5 grid gap-3 md:grid-cols-3">
                  {sampleCards.map((card, index) => (
                    <motion.div
                      key={`${card.title}-${index}`}
                      initial={{ opacity: 0, y: 6 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ delay: index * 0.05, duration: 0.22 }}
                      className="rounded-[22px] border border-white/50 bg-white/60 px-3.5 py-3 shadow-sm"
                    >
                      <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-zinc-400">
                        {card.card_type || "info"}
                      </p>
                      <p className="mt-2 text-sm font-medium text-zinc-800">{card.title}</p>
                      <p className="mt-1 text-[12px] leading-5 text-zinc-500">{card.summary}</p>
                    </motion.div>
                  ))}
                </div>
              ) : null}
            </section>

            <div className="grid gap-4 md:grid-cols-2">
              <section className="rounded-[26px] border border-white/60 bg-white/70 p-4 shadow-sm backdrop-blur-md">
                <div className="flex items-center gap-2 text-zinc-900">
                  <FileText className="h-4 w-4 text-zinc-500" />
                  <h3 className="text-sm font-semibold">资料范围</h3>
                </div>
                <div className="mt-4 flex flex-wrap gap-2">
                  <span className="rounded-full border border-zinc-200/50 bg-white/50 px-2.5 py-1 text-[11px] text-zinc-500">
                    {buildPreview?.digest_mode === "sprint" ? "冲刺模式" : buildPreview?.digest_mode === "systematic" ? "系统模式" : "模式待定"}
                  </span>
                  {buildPreview?.mode_reason?.trim() ? (
                    <span className="rounded-full border border-sky-100 bg-sky-50 px-2.5 py-1 text-[11px] text-sky-600">
                      {buildPreview.mode_reason.trim()}
                    </span>
                  ) : null}
                </div>
                <div className="mt-4 space-y-2">
                  {sourceNames.length > 0 ? (
                    sourceNames.map((name) => (
                      <div
                        key={name}
                        className="rounded-2xl border border-zinc-200/50 bg-white/40 px-3 py-2 text-[12px] text-zinc-600 truncate"
                      >
                        {name}
                      </div>
                    ))
                  ) : (
                    <p className="text-[12px] leading-5 text-zinc-500">
                      当前没有本地资料，本轮会先以搜索结果作为主输入。
                    </p>
                  )}
                </div>
              </section>

              <section className="rounded-[26px] border border-white/60 bg-white/70 p-4 shadow-sm backdrop-blur-md">
                <div className="flex items-center gap-2 text-zinc-900">
                  <CheckCircle2 className="h-4 w-4 text-zinc-500" />
                  <h3 className="text-sm font-semibold">执行脉络</h3>
                </div>
                <div className="mt-4 grid grid-cols-2 gap-3">
                  <div className="rounded-2xl border border-zinc-200/50 bg-emerald-50/50 px-3 py-3">
                    <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-emerald-600">已稳定</p>
                    <p className="mt-2 text-xl font-semibold text-emerald-900">{stableCount}</p>
                  </div>
                  <div className="rounded-2xl border border-zinc-200/50 bg-sky-50/50 px-3 py-3">
                    <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-sky-600">进行中</p>
                    <p className="mt-2 text-xl font-semibold text-sky-900">{activeCount}</p>
                  </div>
                </div>
                <p className="mt-4 text-[12px] leading-5 text-zinc-500">
                  阶段切换时会尽量保留上一份稳定产物。
                </p>
              </section>
            </div>
          </div>

          <section className="relative overflow-hidden rounded-[30px] border border-white/60 bg-white/60 p-5 shadow-sm backdrop-blur-md">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-2 text-zinc-900">
                <Activity className="h-4 w-4 text-zinc-500" />
                <h3 className="text-sm font-semibold">实时正文预览</h3>
              </div>
              <span className="rounded-full border border-zinc-200/50 bg-white px-2.5 py-1 text-[11px] text-zinc-500">
                {draftExcerpt ? "持续覆盖更新" : "等待第一段正文"}
              </span>
            </div>

            {chapterTitles.length > 0 ? (
              <div className="mt-4 flex flex-wrap gap-2">
                {chapterTitles.slice(0, 4).map((title) => (
                  <span
                    key={title}
                    className="rounded-full border border-sky-100 bg-sky-50 px-2.5 py-1 text-[11px] text-sky-600"
                  >
                    {title}
                  </span>
                ))}
              </div>
            ) : null}

            {draftExcerpt ? (
              <div className="mt-5 flex-1 bg-white/40 rounded-xl p-5 border border-white/60 shadow-[inset_0_2px_10px_rgba(0,0,0,0.02)]">
                <pre
                  className="max-h-[420px] overflow-y-auto whitespace-pre-wrap text-[13.5px] leading-[2] text-zinc-600 scrollbar-thin scrollbar-webkit pr-2"
                  style={{ fontFamily: "var(--font-serif)" }}
                >
                  {draftExcerpt}
                  <motion.span className="ml-0.5 inline-block h-[15px] w-[2px] animate-blink rounded-sm bg-sky-500 align-middle" />
                </pre>
              </div>
            ) : (
              <div className="mt-5 space-y-3 p-5">
                <div className="h-3 w-3/4 animate-pulse rounded-full bg-zinc-200/50" />
                <div className="h-3 w-full animate-pulse rounded-full bg-zinc-200/50" />
                <div className="h-3 w-[92%] animate-pulse rounded-full bg-zinc-200/50" />
                <div className="h-3 w-[82%] animate-pulse rounded-full bg-zinc-200/50" />
                <div className="h-3 w-[66%] animate-pulse rounded-full bg-zinc-200/50" />
                <p className="pt-2 text-[12px] leading-6 text-zinc-400">
                  当前还没有可展示的草稿片段，系统会先固定章节结构和资料范围。
                </p>
              </div>
            )}

            <div className="mt-5 rounded-[22px] border border-white/50 bg-white/40 px-3.5 py-3">
              <div className="flex items-center justify-between gap-2">
                <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-zinc-400">Last Movement</p>
                {lastEvent?.created_at ? (
                  <span className="text-[11px] text-zinc-400">{formatBuildEventTime(lastEvent.created_at)}</span>
                ) : null}
              </div>
              <p className="mt-2 text-[13px] leading-6 text-zinc-600">
                {lastEvent?.summary?.trim() || "事件流等待中..."}
              </p>
            </div>
          </section>
        </div>
      </div>
    </section>
  );
}

function BuildLiveFeed({ events, className }: { events: BuildPreviewRecentEvent[]; className?: string }) {
  return (
    <section
      className={cn(
        "overflow-hidden flex flex-col rounded-[28px] border border-white/60 bg-white/70 backdrop-blur-md p-4 shadow-sm md:p-5",
        className,
      )}
    >
      <div className="flex items-center justify-between gap-3 border-b border-zinc-200/50 pb-3">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-zinc-400">Live Feed</p>
          <h3 className="mt-1 flex items-center justify-between text-sm font-semibold text-zinc-900 gap-2">
            最近进展 <span className="flex h-2 w-2 rounded-full bg-emerald-400 animate-pulse" />
          </h3>
        </div>
        <span className="rounded-full border border-sky-100 bg-sky-50 px-2.5 py-1 text-[11px] text-sky-600">
          {events.length} 条
        </span>
      </div>

      {events.length === 0 ? (
        <div className="mt-4 flex flex-col items-center justify-center py-6 text-zinc-400">
          <Loader2 className="w-5 h-5 animate-spin mb-2 opacity-50" />
          <span className="text-[12px]">等待系统产生事件...</span>
        </div>
      ) : (
        <div className="mt-4 space-y-2.5 flex-1 overflow-y-auto pr-2 -mr-2 scrollbar-thin scrollbar-webkit">
          <AnimatePresence initial={false}>
            {events.slice(0, 10).map((event, index) => {
              const stageLabel = EVENT_STAGE_LABELS[(event.stage ?? "").trim()] ?? (event.stage?.trim() || "构建事件");
              const chapterLabel =
                event.title?.trim() ||
                (event.chapter_index ? `第 ${event.chapter_index} 章` : "");
  
              return (
                <motion.div
                  key={`${event.stage}-${event.chapter_index ?? "global"}-${event.created_at || index}`}
                  initial={{ opacity: 0, height: 0, scale: 0.95 }}
                  animate={{ opacity: 1, height: "auto", scale: 1 }}
                  exit={{ opacity: 0, height: 0 }}
                  transition={{ duration: 0.3 }}
                  className="rounded-xl border border-white/50 bg-white/60 backdrop-blur-sm p-3 shadow-sm"
                >
                  <div className="flex items-center gap-2 mb-1.5 flex-wrap">
                    <span className="w-1.5 h-1.5 rounded-full bg-sky-400 animate-pulse" />
                    <span className="font-semibold text-zinc-700 text-xs">{stageLabel}</span>
                    {chapterLabel ? (
                      <span className="rounded-full border border-zinc-200 bg-white px-2 py-0.5 text-[10px] text-zinc-500">
                        {chapterLabel}
                      </span>
                    ) : null}
                    {event.created_at ? (
                      <span className="ml-auto text-[10px] text-zinc-400">{formatBuildEventTime(event.created_at)}</span>
                    ) : null}
                  </div>
                  <p className="text-zinc-500 text-xs line-clamp-2 pl-3.5 leading-relaxed">
                    {event.summary}
                  </p>
                </motion.div>
              );
            })}
          </AnimatePresence>
        </div>
      )}
    </section>
  );
}

export function BuildView({
  isFetching,
  progress,
  statusText,
  buildPreview,
  buildMetrics,
  sourceFiles,
  sourceFilesFetching,
  buildStage,
  className,
}: Props) {
  const timelineSteps = useBuildTimelineSteps(buildStage);
  const currentStep = timelineSteps.find((step) => step.state === "active") ?? timelineSteps[timelineSteps.length - 1];
  const chapters = buildPreview?.chapter_progress ?? [];
  const events = buildPreview?.recent_events ?? [];
  const stableChapterCount = chapters.filter((chapter) => isStableChapter(chapter.status)).length;
  const signalDomains = collectSignalDomains(events);
  const roundedProgress = Math.max(0, Math.min(100, Math.round(progress)));

  const [isDesktop, setIsDesktop] = useState(
    () => typeof window === "undefined" || window.innerWidth >= 1024
  );
  const [showDetailsMobile, setShowDetailsMobile] = useState(false);

  useEffect(() => {
    if (typeof window === "undefined") return undefined;
    const handleResize = () => {
      setIsDesktop(window.innerWidth >= 1024);
    };
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.35 }}
      className={cn("mx-auto w-full max-w-[1400px] py-4", className)}
    >
      <section className="mb-6 rounded-[30px] border border-white/60 bg-white/50 backdrop-blur-xl shadow-xl shadow-sky-900/5 overflow-hidden">
        <div className="px-5 py-5 md:px-7 md:py-6">
          <div className="flex flex-col gap-5 xl:flex-row xl:items-end xl:justify-between">
            <div className="max-w-3xl">
              <div className="inline-flex items-center gap-2 rounded-full border border-zinc-200/50 bg-white/60 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.24em] text-zinc-600 backdrop-blur-sm">
                <Sparkles className="h-3.5 w-3.5 text-sky-500" />
                DocGen Build Workspace
              </div>

              <h1 className="mt-4 text-[26px] font-semibold tracking-tight text-zinc-950">
                {currentStep?.title ?? "知识文档构建中"}
              </h1>
              <p className="mt-2 text-sm leading-7 text-zinc-600">
                {statusText}
              </p>
              {buildPreview?.mode_reason?.trim() ? (
                <p className="mt-2 text-[12px] leading-6 text-sky-600">{buildPreview.mode_reason.trim()}</p>
              ) : null}
            </div>

            <div className="flex items-center gap-3 rounded-[24px] border border-white/60 bg-white/70 px-4 py-3 shadow-sm backdrop-blur-md">
              <div className="relative shrink-0">
                <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-zinc-900 shadow-sm">
                  <Sparkles className="h-4 w-4 text-white" />
                </div>
                <motion.div
                  className="absolute -inset-1 rounded-2xl border border-sky-300/50"
                  animate={{ scale: [1, 1.18, 1], opacity: [0.45, 0, 0.45] }}
                  transition={{ duration: 2, repeat: Infinity, ease: "easeInOut" }}
                />
              </div>

              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <p className="text-sm font-semibold text-zinc-900">{roundedProgress}%</p>
                  {isFetching ? <Loader2 className="h-3.5 w-3.5 animate-spin text-zinc-400" /> : null}
                </div>
                <p className="mt-1 text-[12px] leading-5 text-zinc-500">页面通过 polling 持续恢复最新 build snapshot。</p>
              </div>
            </div>
          </div>

          <div className="mt-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <WorkspaceStat
              label="当前进度"
              value={`${roundedProgress}%`}
              hint={currentStep?.description ?? "构建阶段正在推进。"}
            />
            <WorkspaceStat
              label="章节规模"
              value={chapters.length > 0 ? `${chapters.length} 章` : "待收口"}
              hint={chapters.length > 0 ? `${stableChapterCount} 章已进入稳定状态` : "确认方案后会先露出章节骨架。"}
            />
            <WorkspaceStat
              label="资料输入"
              value={sourceFiles.length > 0 ? `${sourceFiles.length} 份` : "联网优先"}
              hint={sourceFiles.length > 0 ? "本轮优先使用已选资料，再按需补检索。" : "当前没有本地资料，系统将从外部资料补齐。"}
            />
            <WorkspaceStat
              label="实时信号"
              value={events.length > 0 ? `${events.length} 条` : "等待事件"}
              hint={signalDomains.length > 0 ? `${signalDomains.length} 个来源域名已露出` : "最近事件会优先在右侧 feed 中出现。"}
            />
          </div>

          {buildMetrics && <BuildMetricsBadges metrics={buildMetrics} preview={buildPreview} className="mt-4" />}

          <div className="mt-6 h-1.5 w-full overflow-hidden rounded-full bg-zinc-200/50 shadow-inner">
            <motion.div
              initial={{ width: 0 }}
              animate={{ width: `${roundedProgress}%` }}
              transition={{ duration: 0.7, ease: "easeOut" }}
              className="h-full rounded-full bg-gradient-to-r from-sky-400 to-indigo-500"
            />
          </div>
        </div>
      </section>

      {/* 三栏响应式剧场布局 */}
      <div className="grid grid-cols-1 lg:grid-cols-[260px_1fr_300px] gap-6 items-start">
        {/* 左栏：生命周期与资料 */}
        <motion.div
          initial={{ opacity: 0, x: -12 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ delay: 0.12, duration: 0.35 }}
          className="lg:sticky lg:top-6 flex flex-col gap-5"
        >
          <div className="rounded-[28px] border border-white/60 bg-white/70 backdrop-blur-md p-5 shadow-sm">
            <h3 className="text-xs font-bold text-zinc-900 uppercase tracking-widest mb-4">执行生命线</h3>
            <BuildProcessTimeline steps={timelineSteps} />
          </div>
          
          <div className="rounded-[28px] border border-white/60 bg-white/70 backdrop-blur-md p-5 shadow-sm">
            <h3 className="text-xs font-bold text-zinc-900 uppercase tracking-widest mb-4">文献吸收站</h3>
            <BuildMaterialPipeline files={sourceFiles} isFetching={sourceFilesFetching} />
          </div>
        </motion.div>

        {/* 中栏：产物画布 */}
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.18, duration: 0.4 }}
          className="flex flex-col w-full min-w-0"
        >
          <ArtifactCanvas
            buildPreview={buildPreview}
            chapters={chapters}
            events={events}
            sourceFiles={sourceFiles}
            currentStepTitle={currentStep?.title ?? "知识文档构建中"}
            currentStepDescription={currentStep?.description ?? ""}
          />
        </motion.div>

        {/* 右栏：实时动态与溯源 */}
        <motion.div
           initial={{ opacity: 0, x: 12 }}
           animate={{ opacity: 1, x: 0 }}
           transition={{ delay: 0.24, duration: 0.35 }}
           className={cn(
             "lg:sticky lg:top-6 flex flex-col gap-6",
             !isDesktop && !showDetailsMobile && "hidden"
           )}
        >
           <BuildLiveFeed events={events} className="max-h-[400px]" />
           
           {(chapters.length > 0 || events.length > 0) && (
              <div className="rounded-[28px] border border-white/60 bg-white/70 backdrop-blur-md p-5 shadow-sm flex flex-col max-h-[400px]">
                <h3 className="text-xs font-bold text-zinc-900 uppercase tracking-widest mb-4 flex items-center gap-1.5">
                  <LayoutTemplate className="w-3.5 h-3.5" /> 引用与状态溯源
                </h3>
                <div className="flex-1 overflow-y-auto pr-2 -mr-2 scrollbar-thin scrollbar-webkit space-y-4">
                   <BuildResearchSources events={events} />
                   <BuildChapterProgress chapters={chapters} />
                </div>
              </div>
           )}
        </motion.div>

        {/* 移动端切换详情的入口 */}
        {!isDesktop && (
          <div className="fixed bottom-4 left-4 right-4 z-50">
           <button
             type="button"
             onClick={() => setShowDetailsMobile(!showDetailsMobile)}
             className="w-full flex items-center justify-center gap-2 rounded-xl bg-zinc-900 text-white shadow-xl shadow-zinc-900/20 py-3.5 text-sm font-semibold transition-transform active:scale-[0.98]"
           >
             {showDetailsMobile ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
             {showDetailsMobile ? "返回主视图" : "查看执行详情日志"}
           </button>
          </div>
        )}
      </div>

      <style>{`
        /* 避免因为右侧滚动条影响高度的自定义简单滚动条 */
        .scrollbar-webkit::-webkit-scrollbar {
          width: 4px;
        }
        .scrollbar-webkit::-webkit-scrollbar-track {
          background: transparent;
        }
        .scrollbar-webkit::-webkit-scrollbar-thumb {
          background-color: rgba(161, 161, 170, 0.4);
          border-radius: 4px;
        }
      `}</style>
    </motion.div>
  );
}
