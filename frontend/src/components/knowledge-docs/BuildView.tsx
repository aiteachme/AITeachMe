import { motion } from "framer-motion";
import { BookOpen, CheckCircle2, FileText, Loader2, Sparkles } from "lucide-react";

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
    <div className="rounded-[22px] border border-stone-200/80 bg-white/90 px-4 py-3 shadow-[0_14px_44px_-38px_rgba(28,25,23,0.4)]">
      <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-stone-400">{label}</p>
      <p className="mt-2 text-lg font-semibold text-stone-900">{value}</p>
      <p className="mt-1 text-[12px] leading-5 text-stone-500">{hint}</p>
    </div>
  );
}

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
    <section className="relative overflow-hidden rounded-[32px] border border-stone-200/80 bg-[linear-gradient(180deg,#fffefc_0%,#fbfaf7_48%,#f5f3ee_100%)] shadow-[0_30px_90px_-72px_rgba(28,25,23,0.5)]">
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_right,rgba(56,189,248,0.12),transparent_38%),radial-gradient(circle_at_bottom_left,rgba(168,162,158,0.12),transparent_42%)]" />

      <div className="relative px-5 py-5 md:px-7 md:py-6">
        <div className="flex flex-col gap-4 border-b border-stone-200/70 pb-5 xl:flex-row xl:items-start xl:justify-between">
          <div className="max-w-2xl">
            <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-stone-400">Artifact Canvas</p>
            <h2 className="mt-2 text-[22px] font-semibold tracking-tight text-stone-950">知识文档正在成形</h2>
            <p className="mt-2 text-sm leading-6 text-stone-600">
              {currentStepDescription || fallbackSummary}
            </p>
          </div>

          <div className="rounded-[24px] border border-stone-200/80 bg-white/88 p-4 shadow-[0_14px_44px_-36px_rgba(28,25,23,0.35)] xl:max-w-[320px]">
            <div className="flex items-center gap-2 text-stone-900">
              <Sparkles className="h-4 w-4 text-sky-600" />
              <span className="text-sm font-semibold">当前焦点</span>
            </div>
            <p className="mt-3 text-sm font-medium leading-6 text-stone-800">
              {spotlightChapter
                ? `${String(spotlightChapter.chapter_index).padStart(2, "0")} · ${spotlightChapter.title}`
                : "系统正在先搭稳定骨架，再暴露正文片段。"}
            </p>
            <p className="mt-1 text-[12px] leading-5 text-stone-500">
              {spotlightChapter
                ? `当前状态：${buildChapterStatusLabel(spotlightChapter.status)}`
                : "先出现章节结构，随后才会出现逐段增长的正文预览。"}
            </p>
          </div>
        </div>

        <div className="mt-5 grid gap-5 xl:grid-cols-[minmax(0,1.08fr)_minmax(320px,0.92fr)]">
          <div className="space-y-4">
            <section className="rounded-[28px] border border-stone-200/80 bg-white/90 p-5 shadow-[0_18px_52px_-42px_rgba(28,25,23,0.32)]">
              <div className="flex items-center gap-2 text-stone-900">
                <BookOpen className="h-4 w-4 text-stone-500" />
                <h3 className="text-sm font-semibold">学习骨架</h3>
              </div>

              <p
                className="mt-4 text-[14px] leading-7 text-stone-600"
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
                      className="rounded-2xl border border-stone-200/80 bg-stone-50/75 px-3 py-2"
                    >
                      <div className="flex items-start gap-2">
                        <span className="mt-0.5 text-[11px] font-medium text-stone-300">
                          {String(index + 1).padStart(2, "0")}
                        </span>
                        <span className="text-[13px] leading-6 text-stone-700">{title}</span>
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
                      className="rounded-[22px] border border-stone-200/80 bg-white px-3.5 py-3 shadow-[0_12px_32px_-28px_rgba(28,25,23,0.35)]"
                    >
                      <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-stone-400">
                        {card.card_type || "info"}
                      </p>
                      <p className="mt-2 text-sm font-medium text-stone-800">{card.title}</p>
                      <p className="mt-1 text-[12px] leading-5 text-stone-500">{card.summary}</p>
                    </motion.div>
                  ))}
                </div>
              ) : null}
            </section>

            <div className="grid gap-4 md:grid-cols-2">
              <section className="rounded-[26px] border border-stone-200/80 bg-white/88 p-4 shadow-[0_16px_40px_-34px_rgba(28,25,23,0.32)]">
                <div className="flex items-center gap-2 text-stone-900">
                  <FileText className="h-4 w-4 text-stone-500" />
                  <h3 className="text-sm font-semibold">资料范围</h3>
                </div>
                <div className="mt-4 flex flex-wrap gap-2">
                  <span className="rounded-full border border-stone-200 bg-stone-50 px-2.5 py-1 text-[11px] text-stone-500">
                    {buildPreview?.digest_mode === "sprint" ? "冲刺模式" : buildPreview?.digest_mode === "systematic" ? "系统模式" : "模式待定"}
                  </span>
                  {buildPreview?.mode_reason?.trim() ? (
                    <span className="rounded-full border border-stone-200 bg-white px-2.5 py-1 text-[11px] text-stone-500">
                      {buildPreview.mode_reason.trim()}
                    </span>
                  ) : null}
                </div>
                <div className="mt-4 space-y-2">
                  {sourceNames.length > 0 ? (
                    sourceNames.map((name) => (
                      <div
                        key={name}
                        className="rounded-2xl border border-stone-200/80 bg-stone-50/70 px-3 py-2 text-[12px] text-stone-600"
                      >
                        {name}
                      </div>
                    ))
                  ) : (
                    <p className="text-[12px] leading-5 text-stone-500">
                      当前没有本地资料，本轮会先以搜索结果作为主输入，再回填为可读的知识文档。
                    </p>
                  )}
                </div>
              </section>

              <section className="rounded-[26px] border border-stone-200/80 bg-white/88 p-4 shadow-[0_16px_40px_-34px_rgba(28,25,23,0.32)]">
                <div className="flex items-center gap-2 text-stone-900">
                  <CheckCircle2 className="h-4 w-4 text-stone-500" />
                  <h3 className="text-sm font-semibold">执行脉络</h3>
                </div>
                <div className="mt-4 grid grid-cols-2 gap-3">
                  <div className="rounded-2xl border border-stone-200/80 bg-stone-50/70 px-3 py-3">
                    <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-stone-400">已稳定</p>
                    <p className="mt-2 text-xl font-semibold text-stone-900">{stableCount}</p>
                  </div>
                  <div className="rounded-2xl border border-stone-200/80 bg-stone-50/70 px-3 py-3">
                    <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-stone-400">进行中</p>
                    <p className="mt-2 text-xl font-semibold text-stone-900">{activeCount}</p>
                  </div>
                </div>
                <p className="mt-4 text-[12px] leading-5 text-stone-500">
                  阶段切换时会尽量保留上一份稳定产物，因此你会先看到章节结构，再看到越来越接近最终版的正文。
                </p>
              </section>
            </div>
          </div>

          <section className="relative overflow-hidden rounded-[30px] border border-stone-200/80 bg-[linear-gradient(180deg,#ffffff_0%,#fbfbfa_62%,#f4f4f3_100%)] p-5 shadow-[0_22px_64px_-48px_rgba(28,25,23,0.36)]">
            <div className="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-sky-400 via-cyan-400 to-sky-500" />

            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-2 text-stone-900">
                <FileText className="h-4 w-4 text-stone-500" />
                <h3 className="text-sm font-semibold">实时正文预览</h3>
              </div>
              <span className="rounded-full border border-stone-200 bg-white px-2.5 py-1 text-[11px] text-stone-500">
                {draftExcerpt ? "持续覆盖更新" : "等待第一段正文"}
              </span>
            </div>

            {chapterTitles.length > 0 ? (
              <div className="mt-4 flex flex-wrap gap-2">
                {chapterTitles.slice(0, 4).map((title) => (
                  <span
                    key={title}
                    className="rounded-full border border-stone-200/80 bg-stone-50/80 px-2.5 py-1 text-[11px] text-stone-500"
                  >
                    {title}
                  </span>
                ))}
              </div>
            ) : null}

            {draftExcerpt ? (
              <pre
                className="mt-5 max-h-[420px] overflow-y-auto whitespace-pre-wrap text-[13.5px] leading-[2] text-stone-600"
                style={{ fontFamily: "var(--font-serif)" }}
              >
                {draftExcerpt}
                <span className="ml-0.5 inline-block h-[15px] w-[2px] animate-blink rounded-sm bg-sky-500 align-middle" />
              </pre>
            ) : (
              <div className="mt-5 space-y-3">
                <div className="h-3 w-3/4 animate-pulse rounded-full bg-stone-200" />
                <div className="h-3 w-full animate-pulse rounded-full bg-stone-200/90" />
                <div className="h-3 w-[92%] animate-pulse rounded-full bg-stone-200/90" />
                <div className="h-3 w-[82%] animate-pulse rounded-full bg-stone-200/90" />
                <div className="h-3 w-[66%] animate-pulse rounded-full bg-stone-200/90" />
                <p className="pt-2 text-[12px] leading-6 text-stone-500">
                  当前还没有可展示的草稿片段，系统会先固定章节结构和资料范围，再把第一段可读正文推到这里。
                </p>
              </div>
            )}

            <div className="mt-5 rounded-[22px] border border-stone-200/80 bg-white/88 px-3.5 py-3">
              <div className="flex items-center justify-between gap-2">
                <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-stone-400">Last Movement</p>
                {lastEvent?.created_at ? (
                  <span className="text-[11px] text-stone-400">{formatBuildEventTime(lastEvent.created_at)}</span>
                ) : null}
              </div>
              <p className="mt-2 text-[13px] leading-6 text-stone-600">
                {lastEvent?.summary?.trim() || "一旦后端返回最近事件，这里会优先展示当前最关键的一条 build movement。"}
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
        "overflow-hidden rounded-[28px] border border-stone-200/80 bg-white/92 p-4 shadow-[0_20px_60px_-48px_rgba(28,25,23,0.35)] backdrop-blur-sm md:p-5",
        className,
      )}
    >
      <div className="flex items-center justify-between gap-3 border-b border-stone-200/70 pb-3">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-stone-400">Live Feed</p>
          <h3 className="mt-1 text-sm font-semibold text-stone-900">最近进展</h3>
        </div>
        <span className="rounded-full border border-stone-200 bg-stone-50 px-2.5 py-1 text-[11px] text-stone-500">
          {events.length} 条
        </span>
      </div>

      {events.length === 0 ? (
        <div className="mt-4 rounded-2xl border border-stone-200/80 bg-stone-50/70 px-3.5 py-3 text-[12px] leading-6 text-stone-500">
          构建请求已经受理，等第一条稳定事件写入后，这里会开始滚动显示 DocGen 的真实动作。
        </div>
      ) : (
        <div className="mt-4 space-y-2.5">
          {events.slice(0, 7).map((event, index) => {
            const stageLabel = EVENT_STAGE_LABELS[(event.stage ?? "").trim()] ?? (event.stage?.trim() || "构建事件");
            const chapterLabel =
              event.title?.trim() ||
              (event.chapter_index ? `第 ${event.chapter_index} 章` : "");

            return (
              <motion.div
                key={`${event.stage}-${event.chapter_index ?? "global"}-${index}`}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: index * 0.03, duration: 0.22 }}
                className="rounded-2xl border border-stone-200/80 bg-stone-50/65 px-3.5 py-3"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span className="rounded-full border border-stone-200 bg-white px-2 py-0.5 text-[10px] font-medium text-stone-500">
                    {stageLabel}
                  </span>
                  {chapterLabel ? (
                    <span className="rounded-full border border-stone-200 bg-white px-2 py-0.5 text-[10px] text-stone-400">
                      {chapterLabel}
                    </span>
                  ) : null}
                  {event.created_at ? (
                    <span className="ml-auto text-[10px] text-stone-400">{formatBuildEventTime(event.created_at)}</span>
                  ) : null}
                </div>

                <p className="mt-2 text-[13px] leading-6 text-stone-600">{event.summary}</p>
              </motion.div>
            );
          })}
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

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.35 }}
      className={cn("mx-auto w-full max-w-[1280px] py-4", className)}
    >
      <section className="overflow-hidden rounded-[30px] border border-stone-200/80 bg-[linear-gradient(180deg,#ffffff_0%,#faf9f6_100%)] shadow-[0_34px_100px_-78px_rgba(28,25,23,0.55)]">
        <div className="px-5 py-5 md:px-7 md:py-6">
          <div className="flex flex-col gap-5 xl:flex-row xl:items-end xl:justify-between">
            <div className="max-w-3xl">
              <div className="inline-flex items-center gap-2 rounded-full border border-stone-200 bg-white/90 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.24em] text-stone-500">
                <Sparkles className="h-3.5 w-3.5 text-sky-600" />
                DocGen Build Workspace
              </div>

              <h1 className="mt-4 text-[26px] font-semibold tracking-tight text-stone-950">
                {currentStep?.title ?? "知识文档构建中"}
              </h1>
              <p className="mt-2 text-sm leading-7 text-stone-600">
                {statusText}
              </p>
              {buildPreview?.mode_reason?.trim() ? (
                <p className="mt-2 text-[12px] leading-6 text-stone-500">{buildPreview.mode_reason.trim()}</p>
              ) : null}
            </div>

            <div className="flex items-center gap-3 rounded-[24px] border border-stone-200/80 bg-white/90 px-4 py-3 shadow-[0_14px_44px_-36px_rgba(28,25,23,0.35)]">
              <div className="relative shrink-0">
                <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-stone-950 shadow-sm">
                  <Sparkles className="h-4 w-4 text-white" />
                </div>
                <motion.div
                  className="absolute -inset-1 rounded-2xl border border-stone-300/50"
                  animate={{ scale: [1, 1.18, 1], opacity: [0.45, 0, 0.45] }}
                  transition={{ duration: 2, repeat: Infinity, ease: "easeInOut" }}
                />
              </div>

              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <p className="text-sm font-semibold text-stone-900">{roundedProgress}%</p>
                  {isFetching ? <Loader2 className="h-3.5 w-3.5 animate-spin text-stone-400" /> : null}
                </div>
                <p className="mt-1 text-[12px] leading-5 text-stone-500">页面通过 polling 持续恢复最新 build snapshot。</p>
              </div>
            </div>
          </div>

          <div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
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

          <BuildMetricsBadges metrics={buildMetrics} preview={buildPreview} className="mt-4" />

          <div className="mt-5 h-2 overflow-hidden rounded-full bg-stone-100">
            <motion.div
              initial={{ width: 0 }}
              animate={{ width: `${roundedProgress}%` }}
              transition={{ duration: 0.7, ease: "easeOut" }}
              className="h-full rounded-full bg-[linear-gradient(90deg,#111827_0%,#0ea5e9_58%,#22c55e_100%)]"
            />
          </div>
        </div>
      </section>

      <div className="mt-5 grid gap-5 xl:grid-cols-[248px_minmax(0,1fr)_296px]">
        <div className="order-2 space-y-4 xl:order-1">
          <BuildProcessTimeline steps={timelineSteps} />
          <BuildMaterialPipeline files={sourceFiles} isFetching={sourceFilesFetching} />
        </div>

        <div className="order-1 space-y-4 xl:order-2">
          <ArtifactCanvas
            buildPreview={buildPreview}
            chapters={chapters}
            events={events}
            sourceFiles={sourceFiles}
            currentStepTitle={currentStep?.title ?? "知识文档构建中"}
            currentStepDescription={currentStep?.description ?? ""}
          />
          <BuildChapterProgress chapters={chapters} />
        </div>

        <div className="order-3 space-y-4">
          <BuildLiveFeed events={events} />
          <BuildResearchSources events={events} />
        </div>
      </div>
    </motion.div>
  );
}
