import { useCallback, useEffect, useMemo, useRef, type Dispatch, type SetStateAction } from "react";
import { AlertTriangle, ArrowLeft, FileDown, Loader2 } from "lucide-react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";

import { useExamDetailApiV1CoursesCourseIdExamsExamPaperIdGet } from "../api/generated/exams";
import type { ExamPaperDetailResponse } from "../api/generated/model";
import { getApiErrorMessage } from "../api/client";
import { Button } from "../components/ui/Button";
import { ExamPaperSheet } from "../components/exams/ExamPaperSheet";
import {
  buildExamExportFilename,
  buildExamPaperExportDetail,
  getExamPaperExportAvailability,
  waitForExamPrintImages,
} from "../components/exams/examPaperExport";
import { getExamPaperDisplayTitle } from "../components/exams/examDisplay";
import { buildCoursePath } from "../lib/courseNavigation";
import { unwrapOrvalResponse } from "../lib/unwrapOrvalResponse";

const PRINT_PAGE_STYLES = `
  @page {
    size: A4 portrait;
    margin: 12mm 14mm 16mm;
  }

  @page examFlow {
    size: A4 portrait;
    margin: 12mm 14mm 14mm;
  }

  @page examPaper {
    size: A4 portrait;
    margin: 12mm 14mm 16mm;
  }

  .exam-export-flow {
    page: examFlow;
  }

  .exam-export-paper {
    page: examPaper;
  }

  @media print {
    html,
    body,
    #root {
      width: auto !important;
      min-width: 0 !important;
      height: auto !important;
      min-height: 0 !important;
      max-height: none !important;
      margin: 0 !important;
      overflow: visible !important;
      background: #ffffff !important;
    }

    *,
    *::before,
    *::after {
      -webkit-print-color-adjust: exact !important;
      print-color-adjust: exact !important;
    }

    .electron-window-frame,
    .electron-window-content {
      display: block !important;
      width: auto !important;
      height: auto !important;
      min-height: 0 !important;
      max-height: none !important;
      overflow: visible !important;
      background: #ffffff !important;
      transform: none !important;
    }

    .electron-window-titlebar,
    .exam-export-toolbar {
      display: none !important;
    }

    .exam-export-shell,
    .exam-export-preview {
      width: auto !important;
      min-height: 0 !important;
      margin: 0 !important;
      padding: 0 !important;
      overflow: visible !important;
      background: #ffffff !important;
    }

    .exam-export-flow [data-exam-paper-sheet="true"] {
      width: auto !important;
      max-width: none !important;
      margin: 0 !important;
      padding: 0 !important;
    }

    .exam-export-flow [data-exam-paper-sheet="true"] > article {
      min-height: 0 !important;
      overflow: visible !important;
      border: 0 !important;
      box-shadow: none !important;
    }

    .exam-export-flow [data-exam-print-header="true"] {
      padding: 32px 32px 16px !important;
    }

    .exam-export-flow [data-exam-print-header-divider="true"] {
      margin-top: 12px !important;
    }

    .exam-export-flow [data-exam-print-summary="true"] {
      margin-top: 10px !important;
    }

    .exam-export-flow [data-exam-print-instructions="true"] {
      margin-top: 18px !important;
      padding-top: 10px !important;
      padding-bottom: 10px !important;
      line-height: 1.75 !important;
    }

    .exam-export-flow [data-question-anchor="true"] {
      padding-top: 20px !important;
      padding-bottom: 20px !important;
      break-inside: auto;
      orphans: 3;
      widows: 3;
    }

    .exam-export-flow [data-exam-question-main="true"] {
      break-inside: auto;
      orphans: 3;
      widows: 3;
    }

    .exam-export-flow [data-exam-question-prompt="true"] {
      break-inside: auto;
      orphans: 3;
      widows: 3;
    }

    .exam-export-flow [data-exam-question-options="true"] {
      break-inside: auto;
    }

    .exam-export-flow [data-exam-question-main="true"] [role="radio"],
    .exam-export-flow [data-exam-question-main="true"] [role="checkbox"] {
      break-inside: avoid-page;
    }

    .exam-export-flow [data-exam-question-review="true"] {
      margin-top: 16px !important;
      padding-top: 12px !important;
      break-inside: auto;
      orphans: 3;
      widows: 3;
    }

    .exam-export-flow [data-exam-review-block="true"] {
      break-inside: auto;
      orphans: 3;
      widows: 3;
    }

    .exam-export-flow [data-exam-review-block="true"] > p:first-child {
      break-after: avoid-page;
    }

    .exam-export-flow [data-exam-review-result="true"] {
      break-inside: avoid-page;
    }

    .exam-export-flow [data-exam-question-answer="true"] {
      break-inside: auto;
      -webkit-box-decoration-break: clone;
      box-decoration-break: clone;
    }

    .exam-export-flow textarea {
      opacity: 1 !important;
      color: #0f172a !important;
      background: #ffffff !important;
      -webkit-text-fill-color: #0f172a !important;
    }

    .exam-export-paper,
    .exam-export-paper [data-paper-print-flow="true"] {
      display: block !important;
      width: auto !important;
      height: auto !important;
      min-height: 0 !important;
      overflow: visible !important;
      margin: 0 !important;
      padding: 0 !important;
      background: #ffffff !important;
      box-shadow: none !important;
    }

    .exam-export-paper [data-paper-print-document="true"] {
      display: block !important;
      width: auto !important;
      max-width: none !important;
      height: auto !important;
      min-height: 0 !important;
      margin: 0 !important;
      padding: 0 !important;
      overflow: visible !important;
      border: 0 !important;
      box-shadow: none !important;
    }

    .exam-export-paper [data-paper-print-cover="true"] {
      break-inside: avoid-page;
    }

    .exam-export-paper [data-paper-print-question="true"],
    .exam-export-paper [data-paper-print-question-main="true"],
    .exam-export-paper [data-paper-print-question-prompt="true"],
    .exam-export-paper [data-paper-print-options="true"],
    .exam-export-paper [data-paper-print-answer="true"],
    .exam-export-paper [data-paper-print-review="true"],
    .exam-export-paper [data-paper-print-review-block="true"] {
      break-inside: auto;
      orphans: 3;
      widows: 3;
    }

    .exam-export-paper [data-paper-print-question="true"] {
      padding-top: 14px !important;
      padding-bottom: 14px !important;
    }

    .exam-export-paper [data-paper-print-section-title="true"],
    .exam-export-paper [data-paper-print-review-label="true"] {
      break-after: avoid-page;
    }

    .exam-export-paper [data-paper-print-option="true"],
    .exam-export-paper [data-paper-print-document-footer="true"],
    .exam-export-paper .katex-display,
    .exam-export-paper img,
    .exam-export-paper svg,
    .exam-export-paper table {
      break-inside: avoid-page;
    }

    .exam-export-paper [data-paper-print-answer="true"] {
      white-space: pre-wrap !important;
    }

    .exam-export-paper [data-paper-print-option-splittable="true"] {
      break-inside: auto;
      orphans: 3;
      widows: 3;
    }
  }
`;

function buildAnswerMap(paper: ExamPaperDetailResponse, includeAnswers: boolean): Record<number, string> {
  if (!includeAnswers) return {};
  return Object.fromEntries((paper.items ?? []).map((item) => [item.item_order, item.user_answer ?? ""]));
}

export function ExamPaperPrintPage() {
  const { courseId, examPaperId } = useParams();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const autoPrint = searchParams.get("auto") !== "0";
  const paperId = Number(examPaperId);
  const hasAutoPrintedRef = useRef(false);

  const examDetailQuery = useExamDetailApiV1CoursesCourseIdExamsExamPaperIdGet(courseId ?? "", paperId, {
    query: {
      enabled: Boolean(courseId && Number.isFinite(paperId) && paperId > 0),
      retry: false,
    },
  });
  const paper = useMemo(
    () => unwrapOrvalResponse<ExamPaperDetailResponse>(examDetailQuery.data),
    [examDetailQuery.data],
  );
  const exportAvailability = getExamPaperExportAvailability(paper?.status, paper?.exam_mode);
  const exportPaper = useMemo(
    () => paper && exportAvailability.kind
      ? buildExamPaperExportDetail(paper, exportAvailability.kind)
      : null,
    [exportAvailability.kind, paper],
  );
  const answers = useMemo(
    () => exportPaper ? buildAnswerMap(exportPaper, exportAvailability.kind === "graded") : {},
    [exportAvailability.kind, exportPaper],
  );
  const ignoreAnswerChanges = useCallback<Dispatch<SetStateAction<Record<number, string>>>>(() => undefined, []);
  const filename = useMemo(
    () => exportPaper && exportAvailability.kind
      ? buildExamExportFilename(
          getExamPaperDisplayTitle(exportPaper),
          exportAvailability.kind,
          exportPaper.created_at,
        )
      : "训练记录.pdf",
    [exportAvailability.kind, exportPaper],
  );

  useEffect(() => {
    const root = document.documentElement;
    const hadDarkTheme = root.classList.contains("dark");
    root.classList.remove("dark");
    return () => {
      if (hadDarkTheme) root.classList.add("dark");
    };
  }, []);

  useEffect(() => {
    if (!exportPaper || !exportAvailability.available || !exportAvailability.kind) return;
    const previousTitle = document.title;
    document.title = filename.replace(/\.pdf$/i, "");
    return () => {
      document.title = previousTitle;
    };
  }, [exportAvailability.available, exportAvailability.kind, exportPaper, filename]);

  useEffect(() => {
    if (!autoPrint || !exportPaper || !exportAvailability.available || hasAutoPrintedRef.current) return;
    hasAutoPrintedRef.current = true;
    let cancelled = false;
    const controller = new AbortController();
    const printWhenReady = async () => {
      const fontsReady = document.fonts?.ready
        ? document.fonts.ready.then(() => undefined, () => undefined)
        : Promise.resolve();
      await Promise.all([
        fontsReady,
        waitForExamPrintImages(Array.from(document.images), controller.signal),
      ]);
      await new Promise<void>((resolve) => window.requestAnimationFrame(() => resolve()));
      await new Promise<void>((resolve) => window.requestAnimationFrame(() => resolve()));
      if (!cancelled) window.print();
    };
    void printWhenReady();
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [autoPrint, exportAvailability.available, exportPaper]);

  if (!courseId || !Number.isFinite(paperId) || paperId <= 0) {
    return <div className="p-8 text-sm text-rose-700">缺少有效的训练记录标识。</div>;
  }

  if (examDetailQuery.isLoading) {
    return (
      <div className="grid min-h-screen place-items-center bg-slate-50 text-sm text-slate-500">
        <span className="inline-flex items-center gap-2"><Loader2 className="h-4 w-4 animate-spin" />正在准备 PDF 预览...</span>
      </div>
    );
  }

  if (examDetailQuery.error || !paper) {
    return (
      <div className="grid min-h-screen place-items-center bg-slate-50 px-6">
        <div className="max-w-lg rounded-2xl border border-rose-200 bg-white px-6 py-5 text-sm text-rose-700 shadow-sm">
          {getApiErrorMessage(examDetailQuery.error, "读取训练记录失败，无法导出 PDF。")}
        </div>
      </div>
    );
  }

  if (!exportAvailability.available || !exportAvailability.kind || !exportPaper) {
    return (
      <div className="grid min-h-screen place-items-center bg-slate-50 px-6">
        <div className="max-w-lg rounded-2xl border border-amber-200 bg-white px-6 py-6 text-center shadow-sm">
          <AlertTriangle className="mx-auto h-8 w-8 text-amber-500" />
          <h1 className="mt-3 text-lg font-semibold text-slate-950">暂不允许导出</h1>
          <p className="mt-2 text-sm text-slate-600">题目尚未完整生成</p>
          <Button variant="outline" className="mt-5" onClick={() => navigate(buildCoursePath(courseId, "exams"))}>
            返回训练中心
          </Button>
        </div>
      </div>
    );
  }

  const isPaperExam = exportPaper.exam_mode === "paper_exam";
  const isGradedExport = exportAvailability.kind === "graded";

  return (
    <div
      className="exam-export-shell h-full min-h-screen w-full min-w-0 flex-1 overflow-y-auto overscroll-contain bg-slate-100 text-slate-950"
      data-exam-export-ready="true"
      data-exam-export-kind={exportAvailability.kind}
      data-exam-export-mode={exportPaper.exam_mode}
    >
      <style>{PRINT_PAGE_STYLES}</style>
      <header className="exam-export-toolbar sticky top-0 z-50 border-b border-slate-200 bg-white/95 px-4 py-3 shadow-sm backdrop-blur">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3">
          <div className="flex min-w-0 items-center gap-3">
            <Button
              type="button"
              variant="outline"
              size="icon"
              aria-label="返回训练中心"
              onClick={() => navigate(buildCoursePath(courseId, "exams"))}
            >
              <ArrowLeft className="h-4 w-4" />
            </Button>
            <div className="min-w-0">
              <h1 className="truncate text-sm font-semibold text-slate-950">PDF 预览</h1>
              <p className="truncate text-xs text-slate-500">{filename}</p>
            </div>
          </div>
          <Button type="button" className="gap-2" onClick={() => window.print()}>
            <FileDown className="h-4 w-4" />
            导出 PDF
          </Button>
        </div>
      </header>

      <main className={`exam-export-preview ${isPaperExam ? "exam-export-paper py-8" : "exam-export-flow mx-auto max-w-[210mm] px-6 py-8"}`}>
        <ExamPaperSheet
          paper={exportPaper}
          answers={answers}
          activeStage={isGradedExport ? 2 : 1}
          pageScale={1}
          setAnswers={ignoreAnswerChanges}
          showInlineReviewDetails={isGradedExport}
          isReviewAnalysisVisible={isGradedExport}
          isPrintView
        />
      </main>
    </div>
  );
}
