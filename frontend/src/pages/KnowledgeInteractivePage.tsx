import { useEffect, useMemo, useState } from "react";
import { RefreshCw } from "lucide-react";
import { useLocation, useParams, useSearchParams } from "react-router-dom";
import { getApiErrorMessage, runTrackedApiFetch } from "../api/client";
import { parseInteractivePreviewHref, patchHtmlForIframe } from "../lib/interactiveHtml";

export function KnowledgeInteractivePage() {
  const { courseId } = useParams<{ courseId: string }>();
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const isFigureRoute = location.pathname.includes("/html-figure");
  const fallbackTitle = isFigureRoute ? "知识文档静态图示" : "知识文档交互演示";
  const title = (searchParams.get("title") || fallbackTitle).trim();
  const [html, setHtml] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const preview = useMemo(() => {
    return parseInteractivePreviewHref(`${location.pathname}?${searchParams.toString()}`, {
      fallbackCourseId: courseId,
    });
  }, [courseId, location.pathname, searchParams]);

  const assetUrl = preview?.assetUrl ?? "";
  const pageLabel = preview?.kind === "figure" || isFigureRoute ? "静态图示" : "交互演示";

  const patchedHtml = useMemo(() => (html ? patchHtmlForIframe(html) : ""), [html]);

  useEffect(() => {
    document.title = `${title} - AITeachMe`;
  }, [title]);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();

    async function loadHtml() {
      if (!assetUrl) {
        setError("缺少可预览的资产地址。");
        setLoading(false);
        return;
      }
      setLoading(true);
      setError(null);
      try {
        const text = await runTrackedApiFetch(
          assetUrl,
          { method: "GET", signal: controller.signal },
          async (response) => {
            if (!response.ok) {
              throw new Error(`HTTP ${response.status}`);
            }
            return response.text();
          },
          "interactive_asset_disconnect",
        );
        if (!cancelled) {
          setHtml(text);
          setLoading(false);
        }
      } catch (err) {
        if (!cancelled) {
          setError(getApiErrorMessage(err, err instanceof Error ? err.message : "资产加载失败"));
          setLoading(false);
        }
      }
    }

    void loadHtml();
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [assetUrl]);

  return (
    <div className="min-h-dvh bg-slate-50 text-slate-900 dark:bg-slate-950 dark:text-slate-100">
      <div className="mx-auto flex min-h-dvh w-full max-w-[1680px] flex-col px-3 py-3 sm:px-5 sm:py-5">
        <header className="mb-3 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white px-4 py-3 shadow-sm dark:border-slate-800 dark:bg-slate-900">
          <div className="min-w-0">
            <p className="text-xs font-medium text-indigo-600 dark:text-indigo-300">{pageLabel}</p>
            <h1 className="mt-1 truncate text-lg font-semibold text-slate-950 dark:text-slate-50">{title}</h1>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => window.location.reload()}
              className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-600 transition hover:border-indigo-200 hover:text-indigo-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:border-indigo-500/50 dark:hover:text-indigo-200"
            >
              <RefreshCw className="h-4 w-4" />
              刷新
            </button>
          </div>
        </header>

        <main className="flex-1 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-950">
          {loading ? (
            <div className="flex h-[calc(100dvh-7.5rem)] min-h-[520px] items-center justify-center text-sm text-slate-500 dark:text-slate-400">正在加载{pageLabel}…</div>
          ) : error ? (
            <div className="flex h-[calc(100dvh-7.5rem)] min-h-[520px] flex-col items-center justify-center gap-3 px-6 text-center">
              <p className="text-base font-medium text-slate-900 dark:text-slate-100">{pageLabel}加载失败</p>
              <p className="text-sm text-slate-500">{error}</p>
            </div>
          ) : (
            <iframe
              title={title}
              srcDoc={patchedHtml}
              sandbox={preview?.kind === "figure" ? "" : "allow-scripts"}
              className="h-[calc(100dvh-7.5rem)] min-h-[520px] w-full border-0 bg-white"
            />
          )}
        </main>
      </div>
    </div>
  );
}
