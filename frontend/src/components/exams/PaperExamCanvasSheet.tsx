import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type Dispatch,
  type ReactNode,
  type SetStateAction,
} from "react";
import {
  AlertTriangle,
  Bookmark,
  ChevronLeft,
  ChevronRight,
  Columns2,
  FileText,
  Lightbulb,
  MessageSquareText,
} from "lucide-react";

import type { ExamPaperDetailResponse, ExamPaperItemResponse, PaperPreviewRow } from "../../api/generated/model";
import { cn } from "../../lib/utils";
import { ExamMarkdown } from "./ExamMarkdown";
import {
  formatAnswerDisplayValue,
  formatTrueFalseOptionLabel,
  getExamPaperDisplayTitle,
  getExamTotalScore,
  getOptionLabel,
  splitMultiChoiceAnswer,
} from "./examDisplay";

type QuestionEntry = {
  item: ExamPaperItemResponse | null;
  row: PaperPreviewRow | null;
};

type PaperLayoutPage = {
  page_number: number;
  question_orders: number[];
  section_numbers?: number[];
};

type PaperLayoutSection = {
  section_number: number;
  title: string;
  question_type_group?: string;
  question_orders: number[];
  page_start?: number;
  page_end?: number;
  total_score?: number;
};

type PaperLayoutSide = {
  side_number: number;
  label: string;
  pages: number[];
};

type PaperLayoutAllocation = {
  item_order: number;
  page_number: number;
  section_number?: number;
  score?: number;
};

type PaperLayout = {
  mode: string;
  paper_style: string;
  display_name: string;
  total_pages: number;
  pages_per_side: number;
  sides: PaperLayoutSide[];
  pages: PaperLayoutPage[];
  sections: PaperLayoutSection[];
  question_allocations: PaperLayoutAllocation[];
};

interface PaperExamCanvasSheetProps {
  paper: ExamPaperDetailResponse;
  answers: Record<number, string>;
  activeStage: 1 | 2 | 3;
  questionEntries: QuestionEntry[];
  highlightedQuestionOrder?: number | null;
  setAnswers: Dispatch<SetStateAction<Record<number, string>>>;
  selectedItemId?: number | null;
  showInlineReviewDetails?: boolean;
  footerContent?: ReactNode;
  onSelectQuestion?: (item: ExamPaperItemResponse) => void;
  onQuestionAi?: (item: ExamPaperItemResponse, isReviewStage: boolean, answerValue: string) => void;
  onQuestionMarkToggle?: (item: ExamPaperItemResponse, isMarked: boolean) => void;
  markingQuestionTemplateId?: number | null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function toNumber(value: unknown, fallback = 0) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function normalizeNumberArray(value: unknown): number[] {
  return Array.isArray(value)
    ? value.map((item) => Math.trunc(toNumber(item))).filter((item) => item > 0)
    : [];
}

function normalizePaperLayout(raw: unknown): PaperLayout | null {
  if (!isRecord(raw)) return null;
  const pages = Array.isArray(raw.pages)
    ? raw.pages.flatMap((page): PaperLayoutPage[] => {
        if (!isRecord(page)) return [];
        const pageNumber = Math.trunc(toNumber(page.page_number));
        if (pageNumber <= 0) return [];
        return [{
          page_number: pageNumber,
          question_orders: normalizeNumberArray(page.question_orders),
          section_numbers: normalizeNumberArray(page.section_numbers),
        }];
      })
    : [];
  if (!pages.length) return null;

  const sides = Array.isArray(raw.sides)
    ? raw.sides.flatMap((side): PaperLayoutSide[] => {
        if (!isRecord(side)) return [];
        const sideNumber = Math.trunc(toNumber(side.side_number));
        const sidePages = normalizeNumberArray(side.pages);
        if (sideNumber <= 0 || !sidePages.length) return [];
        return [{
          side_number: sideNumber,
          label: typeof side.label === "string" && side.label.trim() ? side.label : `第 ${sideNumber} 面`,
          pages: sidePages,
        }];
      })
    : [];

  const sections = Array.isArray(raw.sections)
    ? raw.sections.flatMap((section): PaperLayoutSection[] => {
        if (!isRecord(section)) return [];
        const sectionNumber = Math.trunc(toNumber(section.section_number));
        if (sectionNumber <= 0) return [];
        return [{
          section_number: sectionNumber,
          title: typeof section.title === "string" && section.title.trim()
            ? section.title
            : `第 ${sectionNumber} 部分`,
          question_type_group: typeof section.question_type_group === "string" ? section.question_type_group : undefined,
          question_orders: normalizeNumberArray(section.question_orders),
          page_start: Math.trunc(toNumber(section.page_start, 1)),
          page_end: Math.trunc(toNumber(section.page_end, 1)),
          total_score: toNumber(section.total_score, 0),
        }];
      })
    : [];

  const questionAllocations = Array.isArray(raw.question_allocations)
    ? raw.question_allocations.flatMap((allocation): PaperLayoutAllocation[] => {
        if (!isRecord(allocation)) return [];
        const itemOrder = Math.trunc(toNumber(allocation.item_order));
        const pageNumber = Math.trunc(toNumber(allocation.page_number));
        if (itemOrder <= 0 || pageNumber <= 0) return [];
        const sectionNumber = Math.trunc(toNumber(allocation.section_number));
        return [{
          item_order: itemOrder,
          page_number: pageNumber,
          ...(sectionNumber > 0 ? { section_number: sectionNumber } : {}),
          score: toNumber(allocation.score, 0),
        }];
      })
    : [];

  return {
    mode: typeof raw.mode === "string" ? raw.mode : "standard_two_page",
    paper_style: typeof raw.paper_style === "string" ? raw.paper_style : "standard",
    display_name: typeof raw.display_name === "string" && raw.display_name.trim() ? raw.display_name : "整卷测试",
    total_pages: Math.max(1, Math.trunc(toNumber(raw.total_pages, pages.length))),
    pages_per_side: Math.max(1, Math.trunc(toNumber(raw.pages_per_side, 2))),
    sides: sides.length ? sides : [{ side_number: 1, label: "正面", pages: pages.map((page) => page.page_number) }],
    pages,
    sections,
    question_allocations: questionAllocations,
  };
}

function buildFallbackLayout(paper: ExamPaperDetailResponse, questionEntries: QuestionEntry[]): PaperLayout {
  const orders = questionEntries
    .map((entry) => entry.item?.item_order ?? entry.row?.order ?? 0)
    .filter((order) => order > 0)
    .sort((left, right) => left - right);
  const questionCount = Math.max(1, orders.length || paper.total_items || 1);
  const totalPages = questionCount >= 36 ? 8 : questionCount >= 28 ? 6 : questionCount >= 12 ? 4 : 2;
  const pagesPerSide = totalPages === 8 ? 4 : totalPages === 6 ? 3 : 2;
  const pages = Array.from({ length: totalPages }, (_, index) => ({
    page_number: index + 1,
    question_orders: [] as number[],
    section_numbers: [1],
  }));
  orders.forEach((order, index) => {
    const pageIndex = Math.min(totalPages - 1, Math.floor((index * totalPages) / Math.max(1, orders.length)));
    pages[pageIndex].question_orders.push(order);
  });
  const sideCount = Math.ceil(totalPages / pagesPerSide);
  return {
    mode: totalPages === 8
      ? "gaokao_eight_page"
      : totalPages === 6
        ? "gaokao_six_page"
        : totalPages === 4
          ? "gaokao_four_page"
          : "standard_two_page",
    paper_style: totalPages > 2 ? "gaokao" : "standard",
    display_name: totalPages > 2 ? `高考${totalPages}页仿真` : "标准两页测试",
    total_pages: totalPages,
    pages_per_side: pagesPerSide,
    sides: Array.from({ length: sideCount }, (_, index) => ({
      side_number: index + 1,
      label: index % 2 === 0 ? "正面" : "背面",
      pages: pages.slice(index * pagesPerSide, (index + 1) * pagesPerSide).map((page) => page.page_number),
    })),
    pages,
    sections: [{
      section_number: 1,
      title: "一、整卷作答",
      question_orders: orders,
      page_start: 1,
      page_end: totalPages,
      total_score: getExamTotalScore(paper),
    }],
    question_allocations: orders.map((order) => ({
      item_order: order,
      page_number: pages.find((page) => page.question_orders.includes(order))?.page_number ?? 1,
      section_number: 1,
      score: paper.items?.find((item) => item.item_order === order)?.score_max ?? 1,
    })),
  };
}

function getPaperLayout(paper: ExamPaperDetailResponse, questionEntries: QuestionEntry[]) {
  return normalizePaperLayout(paper.selection_context?.paper_layout) ?? buildFallbackLayout(paper, questionEntries);
}

function formatScore(value?: number | null) {
  const score = Number(value);
  if (!Number.isFinite(score) || score <= 0) return "";
  return Number.isInteger(score) ? String(score) : score.toFixed(1).replace(/\.0$/, "");
}

function isQuestionMarked(item: ExamPaperItemResponse) {
  return (item as ExamPaperItemResponse & { is_marked?: boolean | null }).is_marked === true;
}

type PaperPageSpec = {
  pageWidth: number;
  pageHeight: number;
  pageGap: number;
  contentColumnGap: number;
};

type RenderPaperPage = PaperLayoutPage & {
  sideNumber: number;
  sideLabel: string;
};

type PageSpread = {
  key: string;
  pages: RenderPaperPage[];
};

const GAOKAO_A4_PAGE_RATIO = 595.32 / 841.92;
const GAOKAO_PAGE_WIDTH = 794;
const GAOKAO_PAGE_HEIGHT = Math.round(GAOKAO_PAGE_WIDTH / GAOKAO_A4_PAGE_RATIO);
const GAOKAO_PAGE_PADDING_TOP = 104;
const GAOKAO_PAGE_PADDING_X = 118;
const GAOKAO_PAGE_PADDING_BOTTOM = 104;
const GAOKAO_CONTENT_HEIGHT = GAOKAO_PAGE_HEIGHT - GAOKAO_PAGE_PADDING_TOP - GAOKAO_PAGE_PADDING_BOTTOM;
const GAOKAO_COVER_ESTIMATED_HEIGHT = 330;
const GAOKAO_QUESTION_GAP = 10;
const VIEWER_HORIZONTAL_PADDING = 48;
const GAOKAO_TEXT_FONT_FAMILY = [
  "SimSun",
  "宋体",
  "Songti SC",
  "STSong",
  "Noto Serif CJK SC",
  "Times New Roman",
  "serif",
].join(", ");
const GAOKAO_HEADING_FONT_FAMILY = [
  "SimHei",
  "黑体",
  "Microsoft YaHei",
  "SimSun",
  "宋体",
  "serif",
].join(", ");
const gaokaoTextStyle: CSSProperties = { fontFamily: GAOKAO_TEXT_FONT_FAMILY };
const gaokaoHeadingStyle: CSSProperties = { fontFamily: GAOKAO_HEADING_FONT_FAMILY };
const gaokaoPageContentStyle: CSSProperties = {
  padding: `${GAOKAO_PAGE_PADDING_TOP}px ${GAOKAO_PAGE_PADDING_X}px ${GAOKAO_PAGE_PADDING_BOTTOM}px`,
};

function buildPaperPageSpec(pagesPerSide: number): PaperPageSpec {
  const pageWidth = GAOKAO_PAGE_WIDTH;
  const pageHeight = GAOKAO_PAGE_HEIGHT;
  const pageGap = pagesPerSide >= 4 ? 20 : pagesPerSide >= 3 ? 24 : 28;

  return {
    pageWidth,
    pageHeight,
    pageGap,
    contentColumnGap: 0,
  };
}

function getPaperFooterLabel(paper: ExamPaperDetailResponse) {
  const title = getExamPaperDisplayTitle(paper);
  const subject = ["语文", "数学", "英语", "物理", "化学", "生物", "历史", "地理", "政治"].find((item) =>
    title.includes(item),
  );
  return subject ? `${subject}试题` : "试题";
}

function getOptionVisualLength(value: unknown) {
  const text = String(value ?? "")
    .replace(/!\[[^\]]*]\([^)]*\)/g, "")
    .replace(/\[[^\]]*]\([^)]*\)/g, "")
    .replace(/[`*_~#>|]/g, "")
    .replace(/\\\(|\\\)|\\\[|\\\]|\$+/g, "")
    .replace(/\s+/g, " ")
    .trim();

  return Array.from(text).reduce((total, char) => {
    if (/[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]/.test(char)) return total + 2;
    if (/[A-Z]/.test(char)) return total + 1.05;
    if (/[a-z0-9]/.test(char)) return total + 0.9;
    if (/\s/.test(char)) return total + 0.45;
    return total + 1.15;
  }, 0);
}

function getOptionColumnCount(options: unknown[]) {
  if (options.length > 4) return 1;
  const longestOption = Math.max(0, ...options.map(getOptionVisualLength));
  if (longestOption > 34) return 1;
  if (longestOption > 12) return 2;
  return 4;
}

function getQuestionOrder(entry: QuestionEntry) {
  return entry.item?.item_order ?? entry.row?.order ?? 0;
}

function getOrderedQuestionOrders(layout: PaperLayout, questionEntries: QuestionEntry[]) {
  const entryOrders = new Set(questionEntries.map(getQuestionOrder).filter((order) => order > 0));
  const sectionOrders = layout.sections.flatMap((section) => section.question_orders).filter((order) => entryOrders.has(order));
  const ordered = sectionOrders.length ? sectionOrders : [...entryOrders].sort((left, right) => left - right);
  return [...new Set(ordered)];
}

function getSectionNumberForOrder(
  order: number,
  layout: PaperLayout,
  allocationByOrder: Map<number, PaperLayoutAllocation>,
) {
  const allocatedSection = allocationByOrder.get(order)?.section_number;
  if (allocatedSection && allocatedSection > 0) return allocatedSection;
  return layout.sections.find((section) => section.question_orders.includes(order))?.section_number ?? 1;
}

function estimateWrappedTextHeight(text: unknown, visualCharsPerLine: number, lineHeight = 24) {
  const visualLength = Math.max(1, getOptionVisualLength(text));
  return Math.max(lineHeight, Math.ceil(visualLength / visualCharsPerLine) * lineHeight);
}

function estimateOptionsHeight(options: unknown[]) {
  if (!options.length) return 0;
  const columnCount = getOptionColumnCount(options);
  const visualCharsPerLine = columnCount >= 4 ? 17 : columnCount === 2 ? 35 : 78;
  const rowLineCounts: number[] = [];
  options.forEach((option, index) => {
    const rowIndex = Math.floor(index / columnCount);
    const optionLines = Math.max(1, Math.ceil(getOptionVisualLength(option) / visualCharsPerLine));
    rowLineCounts[rowIndex] = Math.max(rowLineCounts[rowIndex] ?? 1, optionLines);
  });
  return 10 + rowLineCounts.reduce((total, lines) => total + lines * 24, 0);
}

function estimateQuestionBlockHeight(entry: QuestionEntry | null, includeReviewDetails: boolean) {
  if (!entry?.item) return 74;

  const item = entry.item;
  const type = String(item.question_type ?? "").toLowerCase();
  const stemHeight = estimateWrappedTextHeight(item.stem, 70);
  let height = Math.max(32, stemHeight + 12);

  if (type === "single_choice" || type === "multiple_choice" || type === "multi_choice" || type === "true_false") {
    const choiceOptions = type === "true_false" && !(item.options?.length) ? ["True", "False"] : item.options ?? [];
    height += estimateOptionsHeight(choiceOptions);
  } else if (type === "fill_blank") {
    height += 52;
  } else if (type === "short_answer" || type === "essay") {
    height += 82;
  } else {
    height += 64;
  }

  if (includeReviewDetails) {
    height += 190;
  }

  return Math.max(48, height);
}

function estimateSectionHeadingHeight(
  section: PaperLayoutSection | undefined,
  allocationByOrder: Map<number, PaperLayoutAllocation>,
) {
  if (!section) return 0;
  const text = getSectionHeadingText(section, allocationByOrder);
  return 8 + estimateWrappedTextHeight(text, 66, 28);
}

function buildDynamicRenderedPages(
  layout: PaperLayout,
  questionEntries: QuestionEntry[],
  allocationByOrder: Map<number, PaperLayoutAllocation>,
  includeReviewDetails: boolean,
): RenderPaperPage[] {
  const entryByOrder = new Map(questionEntries.map((entry) => [getQuestionOrder(entry), entry] as const));
  const sectionByNumber = new Map(layout.sections.map((section) => [section.section_number, section] as const));
  const orders = getOrderedQuestionOrders(layout, questionEntries);
  const pagesPerSide = Math.max(1, layout.pages_per_side || 2);
  const pages: RenderPaperPage[] = [];
  let currentOrders: number[] = [];
  let currentSections = new Set<number>();
  let currentHeight = GAOKAO_COVER_ESTIMATED_HEIGHT;
  let lastSectionNumber: number | null = null;

  const pushPage = () => {
    const pageNumber = pages.length + 1;
    const sideNumber = Math.max(1, Math.ceil(pageNumber / pagesPerSide));
    pages.push({
      page_number: pageNumber,
      question_orders: currentOrders,
      section_numbers: [...currentSections],
      sideNumber,
      sideLabel: sideNumber % 2 === 1 ? "正面" : "背面",
    });
    currentOrders = [];
    currentSections = new Set<number>();
    currentHeight = 0;
    lastSectionNumber = null;
  };

  orders.forEach((order) => {
    const entry = entryByOrder.get(order) ?? null;
    const sectionNumber = getSectionNumberForOrder(order, layout, allocationByOrder);
    const questionHeight = estimateQuestionBlockHeight(entry, includeReviewDetails);
    const getBlockHeight = () => {
      const needsSectionHeading = sectionNumber !== lastSectionNumber;
      return (currentOrders.length ? GAOKAO_QUESTION_GAP : 0)
        + (needsSectionHeading ? estimateSectionHeadingHeight(sectionByNumber.get(sectionNumber), allocationByOrder) : 0)
        + questionHeight;
    };

    let blockHeight = getBlockHeight();
    if (currentOrders.length && currentHeight + blockHeight > GAOKAO_CONTENT_HEIGHT) {
      pushPage();
      blockHeight = getBlockHeight();
    }

    currentOrders.push(order);
    currentSections.add(sectionNumber);
    currentHeight += blockHeight;
    lastSectionNumber = sectionNumber;
  });

  if (currentOrders.length || pages.length === 0) {
    pushPage();
  }

  return pages;
}

function getSectionHeadingText(
  section: PaperLayoutSection,
  allocationByOrder: Map<number, PaperLayoutAllocation>,
) {
  const title = section.title.replace(/\s*共\s*\d+(?:\.\d+)?\s*分\s*$/, "").replace(/[：:]\s*$/, "");
  const scores = section.question_orders
    .map((order) => allocationByOrder.get(order)?.score)
    .filter((score): score is number => Number.isFinite(score ?? NaN) && (score ?? 0) > 0);
  const firstScore = scores[0] ?? 0;
  const hasSameScore = scores.length === section.question_orders.length
    && firstScore > 0
    && scores.every((score) => Math.abs(score - firstScore) < 0.001);
  const totalScore = section.total_score ?? scores.reduce((total, score) => total + score, 0);
  const scoreText = hasSameScore
    ? `每小题 ${formatScore(firstScore)} 分，共 ${formatScore(totalScore)} 分`
    : `共 ${formatScore(totalScore)} 分`;
  const typeGroup = section.question_type_group ?? "";
  const instruction = typeGroup.includes("multiple") || section.title.includes("多选")
    ? "在每小题给出的选项中，有多项符合题目要求。"
    : typeGroup.includes("single") || section.title.includes("选择")
      ? "在每小题给出的四个选项中，只有一项是符合题目要求的。"
      : section.title.includes("解答")
        ? "解答应写出文字说明、证明过程或演算步骤。"
        : "";
  return `${title}：本题共 ${section.question_orders.length} 小题，${scoreText}。${instruction}`;
}

function PaperExamCoverIntro({ paper }: { paper: ExamPaperDetailResponse }) {
  return (
    <div className="mb-8 text-slate-950 dark:text-slate-100" style={gaokaoTextStyle}>
      <div className="text-[14px] font-bold leading-6">绝密★启用前</div>
      <div className="mt-7 text-center">
        <div className="text-[21px] leading-8">普通高等学校招生全国统一考试仿真卷</div>
        <div className="mt-4 text-[30px] font-black leading-9 tracking-[0.24em]" style={gaokaoHeadingStyle}>
          {getExamPaperDisplayTitle(paper)}
        </div>
      </div>
      <div className="mt-7 text-[15px] font-bold leading-7">注意事项：</div>
      <ol className="ml-8 mt-1 list-decimal space-y-1 text-[14px] leading-7">
        <li>答卷前，考生务必将自己的姓名、准考证号等填写在答题卡上。</li>
        <li>
          回答选择题时，选出每小题答案后，用铅笔把答题卡上对应题目的答案标号涂黑。如需改动，用橡皮擦干净后，再选涂其他答案标号。
        </li>
        <li>考试结束后，将本试卷和答题卡一并交回。</li>
      </ol>
    </div>
  );
}

function CanvasQuestionPlaceholder({ row }: { row: PaperPreviewRow }) {
  const isFailed = row.generation_status === "failed";
  return (
    <div
      id={`exam-question-${row.order}`}
      data-question-anchor="true"
      data-question-order={row.order}
      className="scroll-mt-28 rounded-sm border border-dashed border-slate-200 px-3 py-3 dark:border-slate-800"
    >
      <div className="flex items-center gap-2 text-sm font-semibold text-slate-500">
        <span>{row.order}.</span>
        {isFailed ? (
          <span className="inline-flex items-center gap-1 text-rose-600 dark:text-rose-300">
            <AlertTriangle className="h-3.5 w-3.5" />
            生成失败
          </span>
        ) : (
          <span>生成中</span>
        )}
      </div>
      {!isFailed ? (
        <div className="mt-3 space-y-2">
          <span className="block h-2.5 w-11/12 rounded-full bg-slate-200 dark:bg-slate-800" />
          <span className="block h-2.5 w-8/12 rounded-full bg-slate-200 dark:bg-slate-800" />
          <span className="block h-16 rounded-md border border-slate-100 bg-slate-50 dark:border-slate-800 dark:bg-slate-900" />
        </div>
      ) : null}
    </div>
  );
}

function CanvasReviewMark({ item }: { item: ExamPaperItemResponse }) {
  const isCorrect = item.is_correct === true;
  return (
    <span
      className={cn(
        "pointer-events-none absolute right-2 top-2 grid h-9 w-9 rotate-[-10deg] place-items-center rounded-full border-2 text-lg font-black",
        isCorrect
          ? "border-emerald-500/70 text-emerald-600 dark:border-emerald-400/70 dark:text-emerald-300"
          : "border-rose-500/70 text-rose-600 dark:border-rose-400/70 dark:text-rose-300",
      )}
      aria-hidden="true"
    >
      {isCorrect ? "✓" : "×"}
    </span>
  );
}

function PaperExamQuestionBlock({
  entry,
  paper,
  answers,
  activeStage,
  highlightedQuestionOrder,
  setAnswers,
  selectedItemId,
  showInlineReviewDetails,
  onSelectQuestion,
  onQuestionAi,
  onQuestionMarkToggle,
  markingQuestionTemplateId,
  score,
}: PaperExamCanvasSheetProps & {
  entry: QuestionEntry;
  score?: number;
}) {
  if (!entry.item) {
    return entry.row ? <CanvasQuestionPlaceholder row={entry.row} /> : null;
  }

  const item = entry.item;
  const answerValue = answers[item.item_order] ?? "";
  const isSingleChoice = item.question_type === "single_choice";
  const isMultipleChoice = item.question_type === "multiple_choice" || item.question_type === "multi_choice";
  const isTrueFalse = item.question_type === "true_false";
  const isChoice = isSingleChoice || isMultipleChoice || isTrueFalse;
  const choiceOptions = isTrueFalse && !(item.options?.length) ? ["True", "False"] : item.options ?? [];
  const selectedMultiChoice = splitMultiChoiceAnswer(answerValue);
  const correctMultiChoice = splitMultiChoiceAnswer(item.correct_answer);
  const isGraded = paper.status === "graded";
  const isReviewStage = isGraded && activeStage === 2;
  const isReadonly = isGraded;
  const isCorrect = item.is_correct === true;
  const isSelectedReviewItem = isReviewStage && selectedItemId === item.id;
  const isQuestionHighlighted = highlightedQuestionOrder === item.item_order;
  const isMarked = isQuestionMarked(item);
  const isMarking = markingQuestionTemplateId === item.question_template_id;
  const scoreLabel = formatScore(score ?? item.score_max);
  const optionColumnCount = getOptionColumnCount(choiceOptions);

  return (
    <div
      id={`exam-question-${item.item_order}`}
      data-question-anchor="true"
      data-question-order={item.item_order}
      onClick={() => {
        if (isReviewStage) {
          onSelectQuestion?.(item);
        }
      }}
      className={cn(
        "group relative scroll-mt-28 border border-transparent py-0.5 transition",
        isReviewStage && "cursor-pointer",
        (isSelectedReviewItem || isQuestionHighlighted) && "border-slate-300 bg-slate-50/70 px-2 dark:border-slate-700 dark:bg-slate-900/70",
      )}
      aria-selected={isSelectedReviewItem || undefined}
      style={gaokaoTextStyle}
    >
      {isReviewStage ? <CanvasReviewMark item={item} /> : null}
      <div className="flex items-start gap-2">
        <div className="w-6 shrink-0 text-right text-[14px] leading-6 text-slate-950 dark:text-slate-100">
          {item.item_order}.
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 items-start justify-between gap-2">
            <div className="min-w-0 break-words text-[14px] leading-6 text-slate-950 dark:text-slate-100 [&_p]:mb-0 [&_p]:text-[14px] [&_p]:leading-6 [&_.katex-display]:my-1 [&_.katex]:font-normal">
              <ExamMarkdown content={item.stem} />
            </div>
            {scoreLabel ? (
              <span className="shrink-0 whitespace-nowrap text-[11px] leading-5 text-slate-950 dark:text-slate-200">
                {scoreLabel} 分
              </span>
            ) : null}
          </div>

          {isChoice ? (
            <div
              className="mt-1.5 grid gap-x-7 gap-y-0.5"
              role={isMultipleChoice ? "group" : "radiogroup"}
              aria-label={`第 ${item.item_order} 题选项`}
              data-option-column-count={optionColumnCount}
              style={{ gridTemplateColumns: `repeat(${optionColumnCount}, minmax(0, 1fr))` }}
            >
              {choiceOptions.map((option, optionIndex) => {
                const optionLabel = isTrueFalse ? option : getOptionLabel(optionIndex);
                const optionValue = isTrueFalse ? option : optionLabel;
                const optionDisplay = isTrueFalse ? formatTrueFalseOptionLabel(option) : option;
                const isSelected = isMultipleChoice ? selectedMultiChoice.has(optionValue) : answerValue === optionValue;
                const isCorrectOption = isMultipleChoice
                  ? correctMultiChoice.has(optionValue)
                  : (item.correct_answer ?? "") === optionValue;
                const isWrongSelectedOption = isReviewStage && isSelected && !isCorrectOption;
                const isRightOption = isReviewStage && isCorrectOption;
                return (
                  <button
                    key={`${item.id}-${optionIndex}`}
                    type="button"
                    role={isMultipleChoice ? "checkbox" : "radio"}
                    aria-checked={isSelected}
                    disabled={isReadonly}
                    onClick={(event) => {
                      event.stopPropagation();
                      setAnswers((current) => {
                        if (!isMultipleChoice) {
                          return { ...current, [item.item_order]: isSelected ? "" : optionValue };
                        }
                        const next = splitMultiChoiceAnswer(current[item.item_order]);
                        if (next.has(optionValue)) {
                          next.delete(optionValue);
                        } else {
                          next.add(optionValue);
                        }
                        return { ...current, [item.item_order]: Array.from(next).sort().join(",") };
                      });
                    }}
                    className={cn(
                      "flex min-h-6 items-start gap-1.5 rounded-none border-0 bg-transparent px-0 py-0 text-left text-[14px] leading-6 text-slate-950 transition hover:bg-slate-100/60 dark:text-slate-100 dark:hover:bg-slate-900/70",
                      isReviewStage
                        ? isRightOption
                          ? "font-bold text-emerald-700 underline decoration-2 underline-offset-4 dark:text-emerald-300"
                          : isWrongSelectedOption
                            ? "font-bold text-rose-700 line-through decoration-2 dark:text-rose-300"
                            : "text-slate-950 dark:text-slate-200"
                        : isSelected
                          ? "font-bold underline decoration-2 underline-offset-4"
                          : "",
                      isReadonly && "cursor-default",
                    )}
                  >
                    <span className="shrink-0">{isTrueFalse ? "" : `${optionLabel}．`}</span>
                    <span className="min-w-0 flex-1 [&_p]:mb-0 [&_p]:text-[14px] [&_p]:leading-6">
                      <ExamMarkdown content={optionDisplay} />
                    </span>
                  </button>
                );
              })}
            </div>
          ) : (
            <textarea
              className={cn(
                "mt-1 min-h-8 w-full resize-none rounded-none border-0 border-b bg-transparent px-1 py-0.5 text-[14px] leading-6 outline-none transition",
                isReviewStage
                  ? isCorrect
                    ? "border-emerald-400 text-emerald-950 dark:border-emerald-400 dark:text-emerald-100"
                    : "border-rose-400 text-rose-950 dark:border-rose-400 dark:text-rose-100"
                  : isReadonly
                    ? "border-slate-300 text-slate-800 dark:border-slate-700 dark:text-slate-300"
                    : "border-slate-400 text-slate-900 focus:border-slate-900 dark:border-slate-700 dark:text-slate-100",
              )}
              placeholder={item.question_type === "fill_blank" ? "________________" : "在此作答"}
              value={answerValue}
              onClick={(event) => event.stopPropagation()}
              onChange={(event) => setAnswers((current) => ({ ...current, [item.item_order]: event.target.value }))}
              disabled={isReadonly}
            />
          )}

          <div className="pointer-events-none absolute right-0 top-0 flex flex-wrap items-center gap-2 text-[10px] font-semibold leading-4 text-slate-400 opacity-0 transition group-hover:opacity-100 group-focus-within:opacity-100">
            {onQuestionAi ? (
              <button
                type="button"
                onClick={(event) => {
                  event.stopPropagation();
                  onQuestionAi(item, isReviewStage, answerValue);
                }}
                className="pointer-events-auto inline-flex items-center gap-1 rounded-md bg-white/90 px-1 text-slate-400 transition hover:text-slate-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-300 dark:bg-slate-950/90 dark:hover:text-slate-200"
                title={`围绕第 ${item.item_order} 题问 AI`}
                aria-label={`围绕第 ${item.item_order} 题问 AI`}
              >
                <MessageSquareText className="h-3 w-3" />
                问AI
              </button>
            ) : null}
            <button
              type="button"
              onClick={(event) => {
                event.stopPropagation();
                onQuestionMarkToggle?.(item, !isMarked);
              }}
              disabled={!onQuestionMarkToggle || isMarking}
              className={cn(
                "pointer-events-auto inline-flex items-center gap-1 rounded-md bg-white/90 px-1 transition focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-300 dark:bg-slate-950/90",
                isMarked ? "text-slate-800 dark:text-slate-100" : "text-slate-400 hover:text-slate-700 dark:hover:text-slate-200",
                (!onQuestionMarkToggle || isMarking) && "cursor-default opacity-70",
              )}
              title={isMarked ? `取消标记第 ${item.item_order} 题` : `标记第 ${item.item_order} 题`}
              aria-label={isMarked ? `取消标记第 ${item.item_order} 题` : `标记第 ${item.item_order} 题`}
              aria-pressed={isMarked}
            >
              <Bookmark className={cn("h-3 w-3", isMarked && "fill-current")} />
              {isMarked ? "已标记" : "标记"}
            </button>
            {isReviewStage ? (
              <span className="inline-flex items-center gap-1">
                <Lightbulb className="h-3 w-3" />
                解析
              </span>
            ) : null}
          </div>

          {isReviewStage && showInlineReviewDetails ? (
            <div className="mt-3 border-t border-dashed border-slate-200 pt-2 text-[14px] leading-6 text-slate-600 dark:border-slate-800 dark:text-slate-300 [&_p]:mb-1 [&_p]:leading-6">
              <p className="text-xs font-semibold text-slate-400">你的答案</p>
              <ExamMarkdown content={formatAnswerDisplayValue(item.question_type, item.user_answer)} />
              <p className="mt-2 text-xs font-semibold text-slate-400">正确答案</p>
              <ExamMarkdown content={formatAnswerDisplayValue(item.question_type, item.correct_answer, "无标准答案")} />
              <p className="mt-2 text-xs font-semibold text-slate-400">解析</p>
              <ExamMarkdown content={item.explanation || "暂无解析"} />
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

export function PaperExamCanvasSheet({
  paper,
  answers,
  activeStage,
  questionEntries,
  highlightedQuestionOrder,
  setAnswers,
  selectedItemId,
  showInlineReviewDetails = true,
  footerContent,
  onSelectQuestion,
  onQuestionAi,
  onQuestionMarkToggle,
  markingQuestionTemplateId,
}: PaperExamCanvasSheetProps) {
  const layout = useMemo(() => getPaperLayout(paper, questionEntries), [paper, questionEntries]);
  const [pageViewMode, setPageViewMode] = useState<"single" | "double">("double");
  const [activePageNumber, setActivePageNumber] = useState(1);
  const [viewerWidth, setViewerWidth] = useState(1280);
  const viewerRef = useRef<HTMLDivElement | null>(null);
  const scrollFrameRef = useRef<number | null>(null);
  const entryByOrder = useMemo(
    () =>
      new Map(
        questionEntries.map((entry) => [
          entry.item?.item_order ?? entry.row?.order ?? 0,
          entry,
        ] as const),
      ),
    [questionEntries],
  );
  const sectionByNumber = useMemo(
    () => new Map(layout.sections.map((section) => [section.section_number, section] as const)),
    [layout.sections],
  );
  const allocationByOrder = useMemo(
    () => new Map(layout.question_allocations.map((allocation) => [allocation.item_order, allocation] as const)),
    [layout.question_allocations],
  );
  const renderedPages = useMemo<RenderPaperPage[]>(() => {
    return buildDynamicRenderedPages(
      layout,
      questionEntries,
      allocationByOrder,
      activeStage === 2 && showInlineReviewDetails,
    );
  }, [activeStage, allocationByOrder, layout, questionEntries, showInlineReviewDetails]);
  const renderedPageCount = renderedPages.length;

  const pageSpec = useMemo(() => buildPaperPageSpec(layout.pages_per_side), [layout.pages_per_side]);
  const pagesInRow = pageViewMode === "double" ? 2 : 1;
  const pageScale = useMemo(() => {
    const availableWidth = Math.max(320, viewerWidth - VIEWER_HORIZONTAL_PADDING);
    const requiredGap = 0;
    const fitScale = (availableWidth - requiredGap) / Math.max(1, pageSpec.pageWidth * pagesInRow);
    return Math.min(1, Math.max(0.38, fitScale));
  }, [pageSpec.pageWidth, pagesInRow, viewerWidth]);
  const displayedPageWidth = Math.round(pageSpec.pageWidth * pageScale);
  const displayedPageHeight = Math.round(pageSpec.pageHeight * pageScale);
  const displayedPageGap = Math.max(12, Math.round(pageSpec.pageGap * pageScale));
  const pageSpreads = useMemo<PageSpread[]>(() => {
    if (pageViewMode === "single") {
      return renderedPages.map((page) => ({
        key: `page-${page.page_number}`,
        pages: [page],
      }));
    }

    const spreads: PageSpread[] = [];
    for (let index = 0; index < renderedPages.length; index += 2) {
      const pages = renderedPages.slice(index, index + 2);
      spreads.push({
        key: `spread-${pages.map((page) => page.page_number).join("-")}`,
        pages,
      });
    }
    return spreads;
  }, [pageViewMode, renderedPages]);
  const currentSpreadIndex = pageSpreads.findIndex((spread) =>
    spread.pages.some((page) => page.page_number === activePageNumber),
  );
  const activeSpreadIndex = currentSpreadIndex >= 0 ? currentSpreadIndex : 0;
  const activeSpread = pageSpreads[activeSpreadIndex];
  const canGoPrevious = activeSpreadIndex > 0;
  const canGoNext = activeSpreadIndex < pageSpreads.length - 1;

  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer) return;

    const updateViewerWidth = () => {
      setViewerWidth(viewer.clientWidth || 1280);
    };
    updateViewerWidth();

    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", updateViewerWidth);
      return () => window.removeEventListener("resize", updateViewerWidth);
    }

    const observer = new ResizeObserver(updateViewerWidth);
    observer.observe(viewer);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    return () => {
      if (scrollFrameRef.current !== null) {
        window.cancelAnimationFrame(scrollFrameRef.current);
      }
    };
  }, []);

  useEffect(() => {
    const firstPageNumber = renderedPages[0]?.page_number ?? 1;
    if (!renderedPages.some((page) => page.page_number === activePageNumber)) {
      setActivePageNumber(firstPageNumber);
    }
  }, [activePageNumber, renderedPages]);

  const scrollToPage = useCallback((pageNumber: number) => {
    setActivePageNumber(pageNumber);
    window.requestAnimationFrame(() => {
      const viewer = viewerRef.current;
      const target = viewer?.querySelector<HTMLElement>(`#paper-page-${pageNumber}`);
      if (!viewer || !target) return;

      const viewerRect = viewer.getBoundingClientRect();
      const targetRect = target.getBoundingClientRect();
      const centeredOffset = Math.max(16, (viewer.clientHeight - targetRect.height) / 2);
      const nextTop = viewer.scrollTop + targetRect.top - viewerRect.top - centeredOffset;
      const normalizedTop = Math.max(0, nextTop);
      if (typeof viewer.scrollTo === "function") {
        viewer.scrollTo({ top: normalizedTop, behavior: "smooth" });
      } else {
        viewer.scrollTop = normalizedTop;
      }
    });
  }, []);

  const changePageViewMode = useCallback(
    (mode: "single" | "double") => {
      setPageViewMode(mode);
      window.setTimeout(() => scrollToPage(activePageNumber), 0);
    },
    [activePageNumber, scrollToPage],
  );

  const goSpread = useCallback(
    (direction: -1 | 1) => {
      const nextIndex = Math.max(0, Math.min(pageSpreads.length - 1, activeSpreadIndex + direction));
      const nextPage = pageSpreads[nextIndex]?.pages[0];
      if (nextPage) {
        scrollToPage(nextPage.page_number);
      }
    },
    [activeSpreadIndex, pageSpreads, scrollToPage],
  );

  const handleViewerScroll = useCallback(() => {
    const viewer = viewerRef.current;
    if (!viewer || scrollFrameRef.current !== null) return;
    scrollFrameRef.current = window.requestAnimationFrame(() => {
      scrollFrameRef.current = null;
      const viewerRect = viewer.getBoundingClientRect();
      const focusY = viewerRect.top + viewerRect.height * 0.42;
      let closestPageNumber: number | null = null;
      let closestDistance = Number.POSITIVE_INFINITY;

      viewer.querySelectorAll<HTMLElement>("[data-paper-page='true']").forEach((pageElement) => {
        const rect = pageElement.getBoundingClientRect();
        if (rect.bottom < viewerRect.top || rect.top > viewerRect.bottom) return;
        const distance = Math.abs((rect.top + rect.bottom) / 2 - focusY);
        if (distance < closestDistance) {
          closestDistance = distance;
          closestPageNumber = Number(pageElement.dataset.pageNumber);
        }
      });

      if (closestPageNumber !== null) {
        const nextPageNumber = closestPageNumber;
        setActivePageNumber((current) => (current === nextPageNumber ? current : nextPageNumber));
      }
    });
  }, []);
  const activePageLabel = activeSpread?.pages.length === 2
    ? `第 ${activeSpread.pages[0]?.page_number}-${activeSpread.pages[1]?.page_number} / ${renderedPageCount} 页`
    : `第 ${activePageNumber} / ${renderedPageCount} 页`;
  const isDoublePageMode = pageViewMode === "double";
  const pageTurnDirection: -1 | 1 | 0 = canGoNext ? 1 : canGoPrevious ? -1 : 0;
  const pageTurnLabel = pageTurnDirection === 1
    ? (isDoublePageMode ? "下一组页面" : "下一页")
    : pageTurnDirection === -1
      ? (isDoublePageMode ? "上一组页面" : "上一页")
      : "当前只有一页";

  const handleFloatingPageTurn = useCallback(() => {
    if (canGoNext) {
      goSpread(1);
      return;
    }

    if (canGoPrevious) {
      goSpread(-1);
    }
  }, [canGoNext, canGoPrevious, goSpread]);

  return (
    <div className="relative flex h-full min-h-0 w-full flex-col overflow-hidden">
      <div
        data-paper-floating-controls="true"
        className="pointer-events-none fixed right-4 top-[10.25rem] z-30 flex flex-col gap-3 xl:right-6"
      >
        <button
          type="button"
          onClick={() => changePageViewMode(isDoublePageMode ? "single" : "double")}
          className="pointer-events-auto grid h-10 w-10 place-items-center rounded-xl border border-slate-200/80 bg-white/92 text-slate-700 shadow-[0_18px_40px_rgba(15,23,42,0.08)] backdrop-blur transition hover:bg-slate-100 dark:border-slate-800 dark:bg-slate-950/88 dark:text-slate-300 dark:shadow-[0_18px_40px_-24px_rgba(0,0,0,0.9)] dark:hover:bg-slate-900 dark:hover:text-slate-100"
          aria-label={isDoublePageMode ? "切换到单页查看" : "切换到双页查看"}
          title={isDoublePageMode ? "双页查看，点击切换到单页" : "单页查看，点击切换到双页"}
        >
          {isDoublePageMode ? <Columns2 className="h-5.5 w-5.5" /> : <FileText className="h-5.5 w-5.5" />}
        </button>

        <button
          type="button"
          onClick={handleFloatingPageTurn}
          disabled={pageTurnDirection === 0}
          className="pointer-events-auto grid h-10 w-10 place-items-center rounded-xl border border-slate-200/80 bg-white/92 text-slate-700 shadow-[0_18px_40px_rgba(15,23,42,0.08)] backdrop-blur transition hover:bg-slate-100 disabled:cursor-default disabled:opacity-40 dark:border-slate-800 dark:bg-slate-950/88 dark:text-slate-300 dark:shadow-[0_18px_40px_-24px_rgba(0,0,0,0.9)] dark:hover:bg-slate-900 dark:hover:text-slate-100"
          aria-label={`${pageTurnLabel}，${activePageLabel}`}
          title={`${pageTurnLabel} · ${activePageLabel}`}
        >
          {pageTurnDirection === -1 ? <ChevronLeft className="h-5.5 w-5.5" /> : <ChevronRight className="h-5.5 w-5.5" />}
        </button>
      </div>

      <div
        ref={viewerRef}
        data-paper-viewer="true"
        className="min-h-0 flex-1 overflow-auto bg-slate-100 px-4 pb-7 pt-3 shadow-inner dark:bg-slate-950"
        onScroll={handleViewerScroll}
      >
        <div className="mx-auto flex min-h-full flex-col items-center gap-8 pb-16">
          {pageSpreads.map((spread) => {
            const isJoinedSpread = pageViewMode === "double";
            const shouldRenderBlankRightPage = isJoinedSpread && spread.pages.length === 1;
            return (
            <article
              key={spread.key}
              data-paper-spread="true"
              data-paper-spread-mode={isJoinedSpread ? "joined" : "single"}
              className={cn(
                "relative flex items-start justify-center",
                isJoinedSpread
                  && "paper-spread-joined overflow-hidden border border-slate-300 bg-white shadow-[0_28px_70px_rgba(15,23,42,0.16)] dark:border-slate-800 dark:bg-slate-950 dark:shadow-[0_28px_70px_-38px_rgba(0,0,0,0.92)]",
              )}
              style={{ gap: isJoinedSpread ? 0 : displayedPageGap }}
            >
              {spread.pages.map((page, pageIndex) => {
                  let lastSectionNumber: number | null = null;
                  return (
                    <div
                      key={page.page_number}
                      className="shrink-0"
                      style={{
                        width: displayedPageWidth,
                        height: displayedPageHeight,
                      }}
                    >
                      <section
                        id={`paper-page-${page.page_number}`}
                        data-paper-page="true"
                        data-page-number={page.page_number}
                        className={cn(
                          "relative flex flex-col overflow-hidden border border-slate-300 bg-white text-slate-950 dark:border-slate-800 dark:bg-slate-950 dark:text-slate-100",
                          isJoinedSpread
                            ? "border-0 shadow-none"
                            : "shadow-[0_28px_70px_rgba(15,23,42,0.16)] dark:shadow-[0_28px_70px_-38px_rgba(0,0,0,0.92)]",
                          !isJoinedSpread && "paper-page-sheet",
                          !isJoinedSpread && page.page_number % 2 === 0 && "paper-page-sheet-alt",
                          isJoinedSpread && pageIndex === 0 && "paper-spread-page-left",
                          isJoinedSpread && pageIndex === 1 && "paper-spread-page-right",
                          isJoinedSpread && pageIndex === 0 && "border-r-0",
                          isJoinedSpread && pageIndex === 1 && "border-l-0",
                        )}
                        style={{
                          width: pageSpec.pageWidth,
                          height: pageSpec.pageHeight,
                          transform: `scale(${pageScale})`,
                          transformOrigin: "top left",
                          ...gaokaoTextStyle,
                        }}
                      >
                        <div className="min-h-0 flex-1 overflow-hidden" style={gaokaoPageContentStyle}>
                          {page.page_number === 1 ? <PaperExamCoverIntro paper={paper} /> : null}

                          {page.question_orders.length === 0 ? (
                            <div className="flex flex-col justify-end gap-5 pt-12 text-slate-200 dark:text-slate-800" aria-hidden="true">
                              {Array.from({ length: 18 }, (_, index) => (
                                <span key={index} className="h-px w-full bg-current" />
                              ))}
                            </div>
                          ) : (
                            <div className="space-y-2.5">
                            {page.question_orders.map((order) => {
                              const entry = entryByOrder.get(order) ?? null;
                              const allocation = allocationByOrder.get(order);
                              const sectionNumber = allocation?.section_number ?? page.section_numbers?.[0] ?? 1;
                              const section = sectionByNumber.get(sectionNumber);
                              const shouldShowSection = sectionNumber !== lastSectionNumber;
                              lastSectionNumber = sectionNumber;
                              return (
                                <div key={order} className="space-y-2">
                                  {shouldShowSection && section ? (
                                    <div className="pt-1 text-[15px] font-bold leading-7 text-slate-950 dark:text-slate-100">
                                      {getSectionHeadingText(section, allocationByOrder)}
                                    </div>
                                  ) : null}
                                  {entry ? (
                                    <PaperExamQuestionBlock
                                      paper={paper}
                                      answers={answers}
                                      activeStage={activeStage}
                                      questionEntries={questionEntries}
                                      highlightedQuestionOrder={highlightedQuestionOrder}
                                      setAnswers={setAnswers}
                                      selectedItemId={selectedItemId}
                                      showInlineReviewDetails={showInlineReviewDetails}
                                      onSelectQuestion={onSelectQuestion}
                                      onQuestionAi={onQuestionAi}
                                      onQuestionMarkToggle={onQuestionMarkToggle}
                                      markingQuestionTemplateId={markingQuestionTemplateId}
                                      entry={entry}
                                      score={allocation?.score}
                                    />
                                  ) : null}
                                </div>
                              );
                            })}
                            </div>
                          )}
                        </div>
                        <footer className="absolute bottom-[54px] left-0 right-0 text-center text-[16px] leading-6 text-slate-950 dark:text-slate-100">
                          {getPaperFooterLabel(paper)}第 {page.page_number} 页 （共 {renderedPageCount} 页）
                        </footer>
                      </section>
                    </div>
                  );
                })}
              {shouldRenderBlankRightPage ? (
                <div
                  className="shrink-0"
                  style={{
                    width: displayedPageWidth,
                    height: displayedPageHeight,
                  }}
                  aria-hidden="true"
                >
                  <section
                    className={cn(
                      "relative flex flex-col overflow-hidden bg-white text-slate-950 dark:bg-slate-950 dark:text-slate-100",
                      "border-0 shadow-none paper-spread-page-right border-l-0",
                    )}
                    style={{
                      width: pageSpec.pageWidth,
                      height: pageSpec.pageHeight,
                      transform: `scale(${pageScale})`,
                      transformOrigin: "top left",
                      ...gaokaoTextStyle,
                    }}
                  />
                </div>
              ) : null}
              {isJoinedSpread ? (
                <span
                  data-paper-spread-fold="true"
                  className="paper-spread-fold"
                  style={{ left: displayedPageWidth, height: displayedPageHeight }}
                  aria-hidden="true"
                >
                  <span className="paper-spread-fold__grain" />
                </span>
              ) : null}
            </article>
            );
          })}
          {footerContent ? (
            <div
              data-paper-action-footer="true"
              className="flex w-full justify-center px-4 pb-14 pt-2"
            >
              {footerContent}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
