import { useEffect, useMemo, useState } from "react";
import { RefreshCw } from "lucide-react";
import { useParams, useSearchParams } from "react-router-dom";

function encodePathSegments(path: string): string {
  return path
    .split("/")
    .filter(Boolean)
    .map((part) => encodeURIComponent(part))
    .join("/");
}

function normalizeAssetPath(raw: string | null): string {
  const normalized = String(raw ?? "").replace(/\\/g, "/").trim().replace(/^\/+/, "");
  if (!normalized || normalized.includes("..")) return "";
  return normalized;
}

export function KnowledgeInteractivePage() {
  const { courseId } = useParams<{ courseId: string }>();
  const [searchParams] = useSearchParams();
  const assetPath = normalizeAssetPath(searchParams.get("asset"));
  const title = (searchParams.get("title") || "知识文档交互演示").trim();
  const [html, setHtml] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const assetUrl = useMemo(() => {
    if (!courseId || !assetPath) return "";
    return `/api/v1/courses/${encodeURIComponent(courseId)}/files/assets/${encodePathSegments(assetPath)}`;
  }, [assetPath, courseId]);

  useEffect(() => {
    document.title = `${title} - AITeachMe`;
  }, [title]);

  useEffect(() => {
    let cancelled = false;

    async function loadHtml() {
      if (!assetUrl) {
        setError("缺少可预览的交互资产地址。");
        setLoading(false);
        return;
      }
      setLoading(true);
      setError(null);
      try {
        const response = await fetch(assetUrl, { method: "GET" });
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }
        const text = await response.text();
        if (!cancelled) {
          setHtml(text);
          setLoading(false);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "交互页加载失败");
          setLoading(false);
        }
      }
    }

    void loadHtml();
    return () => {
      cancelled = true;
    };
  }, [assetUrl]);

  return (
    <div className="min-h-dvh bg-slate-950 text-slate-100">
      <div className="mx-auto flex min-h-dvh max-w-7xl flex-col px-3 py-4 sm:px-6 sm:py-6">
        <header className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-slate-800 bg-slate-900/80 px-4 py-4 sm:px-5">
          <div className="min-w-0">
            <p className="text-xs uppercase tracking-[0.18em] text-slate-400">Interactive Sidecar</p>
            <h1 className="mt-1 truncate text-lg font-semibold text-white">{title}</h1>
            <p className="mt-1 text-sm text-slate-400">本页使用沙箱 iframe 预览交互资产，避免直接把原始 HTML 当同源页面打开。</p>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => window.location.reload()}
              className="inline-flex items-center gap-1.5 rounded-xl border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200 hover:bg-slate-800"
            >
              <RefreshCw className="h-4 w-4" />
              刷新
            </button>
          </div>
        </header>

        <main className="flex-1 overflow-hidden rounded-2xl border border-slate-800 bg-white">
          {loading ? (
            <div className="flex h-[78vh] items-center justify-center text-sm text-slate-500">正在加载交互页…</div>
          ) : error ? (
            <div className="flex h-[78vh] flex-col items-center justify-center gap-3 px-6 text-center">
              <p className="text-base font-medium text-slate-900">交互页加载失败</p>
              <p className="text-sm text-slate-500">{error}</p>
            </div>
          ) : (
            <iframe
              title={title}
              srcDoc={html}
              sandbox="allow-scripts"
              className="h-[78vh] w-full border-0 bg-white"
            />
          )}
        </main>
      </div>
    </div>
  );
}
