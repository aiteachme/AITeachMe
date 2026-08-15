import { useEffect, useState, type ReactNode } from "react";
import { Layers3, ListChecks, Target, ThumbsUp } from "lucide-react";

import type { ExamPaperDetailResponse } from "../../api/generated/model";
import { cn } from "../../lib/utils";
import { MarkdownViewer } from "../ui/MarkdownViewer";
import type { ExamStudyGuideFocusUnit, ExamStudyGuideResponse } from "./types";
import { formatDateTime, getExamPaperDisplayTitle } from "./examDisplay";
import {
  getStudyGuideGenerationProgress,
  getNextStudyGuideSection,
  getStudyGuideProgressValue,
  getStudyGuideSectionVisibility,
  mergeStudyGuideActionItems,
  type StudyGuideSectionVisibility,
} from "./studyGuideDisplay";

const GUIDE_MARKDOWN_CLASS =
  "min-w-0 break-words font-serif text-slate-700 dark:text-slate-300 [&_p]:mb-2 [&_p]:text-[15px] [&_p]:leading-7 [&_p:last-child]:mb-0 [&_ul]:my-2 [&_ol]:my-2 [&_li]:leading-7 [&_.katex-display]:my-3 [&_.katex-display]:rounded-md [&_.katex-display]:border [&_.katex-display]:border-slate-200 [&_.katex-display]:bg-slate-50/80 [&_.katex-display]:px-3 [&_.katex-display]:py-2 dark:[&_.katex-display]:border-slate-800 dark:[&_.katex-display]:bg-slate-900/70 [&_.katex]:text-inherit";

const EMPTY_SECTION_VISIBILITY: StudyGuideSectionVisibility = {
  strengths: false,
  focusUnits: false,
  priorityGaps: false,
  actionSteps: false,
};

const STREAMED_SECTION_REVEAL_DELAY_MS = 800;

type GuideSectionTone = "strength" | "focus" | "gap" | "action";

const GUIDE_SECTION_TONES: Record<GuideSectionTone, {
  icon: string;
  item: string;
  number: string;
}> = {
  strength: {
    icon: "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-300",
    item: "border-emerald-100/90 bg-emerald-50/35 dark:border-emerald-500/20 dark:bg-emerald-500/[0.06]",
    number: "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/20 dark:text-emerald-300",
  },
  focus: {
    icon: "border-sky-200 bg-sky-50 text-sky-700 dark:border-sky-500/30 dark:bg-sky-500/10 dark:text-sky-300",
    item: "border-sky-100/90 bg-sky-50/30 dark:border-sky-500/20 dark:bg-sky-500/[0.06]",
    number: "bg-sky-100 text-sky-700 dark:bg-sky-500/20 dark:text-sky-300",
  },
  gap: {
    icon: "border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300",
    item: "border-amber-100/90 bg-amber-50/30 dark:border-amber-500/20 dark:bg-amber-500/[0.06]",
    number: "bg-amber-100 text-amber-700 dark:bg-amber-500/20 dark:text-amber-300",
  },
  action: {
    icon: "border-indigo-200 bg-indigo-50 text-indigo-700 dark:border-indigo-500/30 dark:bg-indigo-500/10 dark:text-indigo-300",
    item: "border-indigo-100/90 bg-indigo-50/30 dark:border-indigo-500/20 dark:bg-indigo-500/[0.06]",
    number: "bg-indigo-100 text-indigo-700 dark:bg-indigo-500/20 dark:text-indigo-300",
  },
};

function clampPercent(value: number) {
  return Math.max(0, Math.min(100, value));
}

function formatRatePercent(value?: number | null) {
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  return Math.round(clampPercent(value <= 1 ? value * 100 : value));
}

function getPerformanceBarColor(percent: number) {
  if (percent <= 30) return "bg-rose-500";
  if (percent <= 70) return "bg-amber-500";
  return "bg-emerald-500";
}

function getPerformanceTextColor(percent: number) {
  if (percent <= 30) return "text-rose-600 dark:text-rose-400";
  if (percent <= 70) return "text-amber-600 dark:text-amber-400";
  return "text-emerald-600 dark:text-emerald-400";
}

function getPaperAttemptSummary(unit: ExamStudyGuideFocusUnit) {
  const attempts = Number.isFinite(unit.paper_attempts) ? Math.max(0, Math.floor(unit.paper_attempts ?? 0)) : 0;
  const correctAttempts = Number.isFinite(unit.paper_correct_attempts)
    ? Math.min(attempts, Math.max(0, Math.floor(unit.paper_correct_attempts ?? 0)))
    : 0;
  return attempts > 0 ? `本卷答对 ${correctAttempts}/${attempts} 题` : null;
}

function getGuideItems(items?: string[] | null, limit = Number.POSITIVE_INFINITY) {
  return (items ?? [])
    .filter((item) => typeof item === "string" && item.trim().length > 0)
    .slice(0, limit);
}

function getGuideUnits(units?: ExamStudyGuideFocusUnit[] | null) {
  return (units ?? []).slice(0, 3);
}

function GuideMarkdown({
  content,
  className,
}: {
  content?: string | null;
  className?: string;
}) {
  const markdown = typeof content === "string" && content.trim() ? content : " ";

  return (
    <div className={cn(GUIDE_MARKDOWN_CLASS, className)}>
      <MarkdownViewer content={markdown} variant="default" />
    </div>
  );
}

function GuideSection({
  icon,
  title,
  description,
  items,
  tone,
}: {
  icon: ReactNode;
  title: string;
  description: string;
  items?: string[] | null;
  tone: GuideSectionTone;
}) {
  const visibleItems = getGuideItems(items);
  if (!visibleItems.length) return null;
  const toneClasses = GUIDE_SECTION_TONES[tone];

  return (
    <section className="border-t border-slate-200 py-8 dark:border-slate-800" data-study-guide-section={tone}>
      <div className="flex items-center gap-3">
        <span
          className={cn("grid h-10 w-10 shrink-0 place-items-center rounded-lg border", toneClasses.icon)}
          aria-hidden="true"
        >
          {icon}
        </span>
        <div className="min-w-0">
          <h2 className="font-serif text-[20px] font-bold leading-7 text-slate-950 dark:text-slate-100">{title}</h2>
          <p className="mt-0.5 font-serif text-[13px] leading-5 text-slate-500 dark:text-slate-400">{description}</p>
        </div>
      </div>

      <ol className="mt-5 space-y-3">
        {visibleItems.map((item, index) => (
          <li
            key={`${title}-${index}`}
            className={cn("flex gap-3 rounded-xl border px-4 py-3.5", toneClasses.item)}
          >
            <span className={cn("grid h-6 w-6 shrink-0 place-items-center rounded-full text-[11px] font-bold", toneClasses.number)}>
              {index + 1}
            </span>
            <div className="min-w-0 flex-1 pt-px">
              <GuideMarkdown content={item} />
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}

function FocusUnitRow({ unit }: { unit: ExamStudyGuideFocusUnit }) {
  const paperScorePercent = formatRatePercent(unit.paper_score_rate);
  const attemptSummary = getPaperAttemptSummary(unit);
  const barColor = paperScorePercent !== null ? getPerformanceBarColor(paperScorePercent) : "";
  const textColor = paperScorePercent !== null ? getPerformanceTextColor(paperScorePercent) : "";

  return (
    <article className={cn("rounded-xl border px-5 py-4", GUIDE_SECTION_TONES.focus.item)}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <GuideMarkdown
          content={unit.knowledge_unit_name}
          className="min-w-0 flex-1 [&_p]:text-[16px] [&_p]:font-bold [&_p]:leading-7 [&_p]:text-slate-950 dark:[&_p]:text-slate-100"
        />
        {attemptSummary ? (
          <span className="shrink-0 rounded-full border border-sky-200/80 bg-white/75 px-2.5 py-1 text-[11px] font-semibold text-sky-700 dark:border-sky-500/30 dark:bg-slate-900/70 dark:text-sky-300">
            {attemptSummary}
          </span>
        ) : null}
      </div>

      {paperScorePercent !== null ? (
        <div className="mt-3 flex items-center gap-3">
          <div
            className="h-2.5 min-w-0 flex-1 overflow-hidden rounded-full bg-slate-200/80 dark:bg-slate-800"
            role="progressbar"
            aria-label={`${unit.knowledge_unit_name}本卷得分率`}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={paperScorePercent}
          >
            <div className={`h-full rounded-full transition-all ${barColor}`} style={{ width: `${Math.max(paperScorePercent, 2)}%` }} />
          </div>
          <span className={`shrink-0 text-xs font-bold ${textColor}`}>
            本卷得分率 {paperScorePercent}%
          </span>
        </div>
      ) : null}

      <GuideMarkdown
        content={unit.reason}
        className="mt-3 [&_p]:text-[13px] [&_p]:leading-6 [&_p]:text-slate-500 dark:[&_p]:text-slate-400"
      />
    </article>
  );
}

function FocusUnitsSection({ units }: { units?: ExamStudyGuideFocusUnit[] | null }) {
  const visibleUnits = getGuideUnits(units);
  if (!visibleUnits.length) return null;

  return (
    <section className="border-t border-slate-200 py-8 dark:border-slate-800" data-study-guide-section="focus">
      <div className="flex items-center gap-3">
        <span
          className={cn("grid h-10 w-10 shrink-0 place-items-center rounded-lg border", GUIDE_SECTION_TONES.focus.icon)}
          aria-hidden="true"
        >
          <Target className="h-4 w-4" />
        </span>
        <div className="min-w-0">
          <h2 className="font-serif text-[20px] font-bold leading-7 text-slate-950 dark:text-slate-100">重点知识点</h2>
          <p className="mt-0.5 font-serif text-[13px] leading-5 text-slate-500 dark:text-slate-400">按本卷关联题目的得分表现排序</p>
        </div>
      </div>

      <div className="mt-5 space-y-3">
        {visibleUnits.map((unit, index) => (
          <FocusUnitRow key={`${unit.knowledge_unit_id ?? unit.knowledge_unit_name}-${index}`} unit={unit} />
        ))}
      </div>
    </section>
  );
}

function useStreamedGuidePresentation(
  availability: StudyGuideSectionVisibility,
  isStreaming: boolean,
) {
  const [usesStagedReveal, setUsesStagedReveal] = useState(isStreaming);
  const [visibility, setVisibility] = useState<StudyGuideSectionVisibility>(() => (
    isStreaming ? EMPTY_SECTION_VISIBILITY : availability
  ));

  useEffect(() => {
    if (!isStreaming) return;
    setUsesStagedReveal(true);
  }, [isStreaming]);

  const stagedReveal = usesStagedReveal || isStreaming;
  const nextSection = stagedReveal
    ? getNextStudyGuideSection(availability, visibility)
    : null;
  const hasVisibleSection = Object.values(visibility).some(Boolean);

  useEffect(() => {
    if (stagedReveal) return;
    setVisibility((current) => (
      current.strengths === availability.strengths
        && current.focusUnits === availability.focusUnits
        && current.priorityGaps === availability.priorityGaps
        && current.actionSteps === availability.actionSteps
        ? current
        : availability
    ));
  }, [
    availability.actionSteps,
    availability.focusUnits,
    availability.priorityGaps,
    availability.strengths,
    stagedReveal,
  ]);

  useEffect(() => {
    if (!stagedReveal) return;
    if (!nextSection) return;

    const timer = window.setTimeout(() => {
      setVisibility((current) => ({ ...current, [nextSection]: true }));
    }, hasVisibleSection ? STREAMED_SECTION_REVEAL_DELAY_MS : 180);
    return () => window.clearTimeout(timer);
  }, [
    hasVisibleSection,
    nextSection,
    stagedReveal,
  ]);

  const hasPendingSection = nextSection !== null;
  return {
    hasPendingSection,
    usesStagedReveal: stagedReveal,
    visibility: stagedReveal
      ? {
          strengths: availability.strengths && visibility.strengths,
          focusUnits: availability.focusUnits && visibility.focusUnits,
          priorityGaps: availability.priorityGaps && visibility.priorityGaps,
          actionSteps: availability.actionSteps && visibility.actionSteps,
        }
      : availability,
  };
}

function GuideGenerationProgress({
  isStreaming,
  hasPendingSection,
  label,
}: {
  isStreaming: boolean;
  hasPendingSection: boolean;
  label: string;
}) {
  const [isVisible, setIsVisible] = useState(true);
  const progressValue = getStudyGuideProgressValue({ isStreaming, hasPendingSection });
  const isActive = progressValue === undefined;

  useEffect(() => {
    if (isActive) {
      setIsVisible(true);
      return;
    }
    const timer = window.setTimeout(() => setIsVisible(false), 480);
    return () => window.clearTimeout(timer);
  }, [isActive]);

  if (!isVisible) return null;

  return (
    <div
      className="mx-auto mt-5 w-full max-w-sm text-left"
      role="status"
      aria-live="polite"
    >
      <div className="mb-2 flex items-center justify-between gap-4 text-xs font-semibold text-indigo-600 dark:text-indigo-300">
        <span>{isActive ? label : "复习指南已生成"}</span>
        <span className="inline-flex items-center gap-1.5" aria-hidden="true">
          {isActive ? <span className="build-live-dot h-1.5 w-1.5 bg-indigo-500" /> : null}
          {isActive ? "生成中" : `${progressValue}%`}
        </span>
      </div>
      <div
        className={`h-1.5 overflow-hidden rounded-full bg-indigo-100 dark:bg-indigo-950/80 ${
          isActive ? "build-loading-progress-track" : ""
        }`}
        role="progressbar"
        aria-label="复习指南生成进度"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={progressValue}
        aria-valuetext={isActive ? `${label}，内容仍在生成` : "复习指南生成完成"}
      >
        <div
          className={`h-full rounded-full bg-gradient-to-r from-indigo-500 to-violet-500 transition-[width] duration-300 ease-out ${
            isActive ? "build-loading-progress-fill w-[44%]" : "w-full"
          }`}
        />
      </div>
    </div>
  );
}

export function ExamStudyGuideView({
  guide,
  paper,
  isStreaming = false,
}: {
  guide: ExamStudyGuideResponse;
  paper: ExamPaperDetailResponse;
  isStreaming?: boolean;
}) {
  const strengths = getGuideItems(guide.strengths, 2);
  const focusUnits = getGuideUnits(guide.focus_units);
  const priorityGaps = getGuideItems(guide.priority_gaps, 3);
  const actionSteps = mergeStudyGuideActionItems(guide.action_steps, guide.review_tasks);
  const sectionAvailability = getStudyGuideSectionVisibility({
    strengths: strengths.length > 0,
    focusUnits: focusUnits.length > 0,
    priorityGaps: priorityGaps.length > 0,
    actionSteps: actionSteps.length > 0,
  });
  const streamedPresentation = useStreamedGuidePresentation(sectionAvailability, isStreaming);
  const sectionVisibility = streamedPresentation.visibility;
  const generationProgress = getStudyGuideGenerationProgress({
    hasSummary: guide.overall_summary.trim().length > 0,
    ...sectionVisibility,
  });

  return (
    <div className="relative mx-auto w-full max-w-[1040px] pb-12">
      <div className="absolute bottom-8 -right-5 top-5 hidden w-full border border-slate-200 bg-white shadow-[0_18px_36px_rgba(15,23,42,0.08)] dark:border-slate-800 dark:bg-slate-900/80 dark:shadow-[0_18px_36px_rgba(0,0,0,0.42)] lg:block" />
      <div className="absolute bottom-4 -right-2 top-2 hidden w-full border border-slate-200 bg-white shadow-[0_14px_30px_rgba(15,23,42,0.06)] dark:border-slate-800 dark:bg-slate-900/90 dark:shadow-[0_14px_30px_rgba(0,0,0,0.36)] lg:block" />

      <article
        className="relative min-h-[1470px] overflow-hidden border border-slate-200 bg-white shadow-[0_26px_70px_rgba(15,23,42,0.15)] dark:border-slate-800 dark:bg-slate-950 dark:shadow-[0_28px_76px_-34px_rgba(0,0,0,0.9)]"
        aria-busy={isStreaming || streamedPresentation.hasPendingSection}
      >
        <header className="px-6 pb-6 pt-12 text-center sm:px-10 sm:pt-16 lg:px-16">
          <h1 className="break-words font-serif text-3xl font-bold tracking-[0.08em] text-slate-950 dark:text-slate-100 sm:text-4xl">
            {getExamPaperDisplayTitle(paper)}
          </h1>
          <div className="mx-auto mt-5 flex max-w-md items-center justify-center gap-3 text-slate-400 dark:text-slate-600">
            <span className="h-px flex-1 bg-slate-300 dark:bg-slate-700" />
            <span className="h-2 w-2 rotate-45 bg-slate-800 dark:bg-slate-300" />
            <span className="h-px flex-1 bg-slate-300 dark:bg-slate-700" />
          </div>
          <p className="mt-4 font-serif text-base font-semibold text-slate-600 dark:text-slate-400">
            复习指南
          </p>
          {streamedPresentation.usesStagedReveal ? (
            <GuideGenerationProgress
              isStreaming={isStreaming}
              hasPendingSection={streamedPresentation.hasPendingSection}
              label={generationProgress.label}
            />
          ) : null}

          <div className="mt-8 border-y border-dashed border-slate-300 py-5 text-left font-serif text-sm leading-8 text-slate-700 dark:border-slate-700 dark:text-slate-300 sm:text-base">
            <GuideMarkdown
              content={guide.overall_summary}
              className="[&_p]:font-serif [&_p]:text-sm [&_p]:leading-8 [&_p]:text-slate-700 [&_p]:text-justify dark:[&_p]:text-slate-300 sm:[&_p]:text-base"
            />
          </div>

          <div className="mt-5 flex flex-wrap items-center gap-2 text-xs font-semibold text-slate-500 dark:text-slate-400">
            {paper.score_obtained != null && paper.total_score != null ? (
              <span className="rounded-md bg-slate-100 px-2.5 py-1 dark:bg-slate-800">
                得分 {paper.score_obtained}/{paper.total_score}
              </span>
            ) : null}
            {paper.score_obtained != null && paper.total_score != null && paper.total_score > 0 ? (
              <span className="rounded-md bg-slate-100 px-2.5 py-1 dark:bg-slate-800">
                得分率 {Math.round((paper.score_obtained / paper.total_score) * 100)}%
              </span>
            ) : null}
            {!isStreaming ? (
              <span className="rounded-md bg-slate-100 px-2.5 py-1 dark:bg-slate-800">
                生成时间 {formatDateTime(guide.generated_at)}
              </span>
            ) : null}
          </div>
        </header>

        <div className="px-6 pb-10 sm:px-10 lg:px-14">
          {sectionVisibility.strengths ? (
            <GuideSection
              icon={<ThumbsUp className="h-[18px] w-[18px]" />}
              title="做得不错"
              description="本次已经表现稳定的部分"
              items={strengths}
              tone="strength"
            />
          ) : null}
          {sectionVisibility.focusUnits ? <FocusUnitsSection units={focusUnits} /> : null}
          {sectionVisibility.priorityGaps ? (
            <GuideSection
              icon={<Layers3 className="h-[18px] w-[18px]" />}
              title="优先补漏"
              description="从失分表现提炼出的关键缺口"
              items={priorityGaps}
              tone="gap"
            />
          ) : null}
          {sectionVisibility.actionSteps ? (
            <GuideSection
              icon={<ListChecks className="h-[18px] w-[18px]" />}
              title="下一步怎么学"
              description="按顺序执行，并用完成标准检验"
              items={actionSteps}
              tone="action"
            />
          ) : null}
        </div>
      </article>
    </div>
  );
}
