import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowLeft,
  BookOpenText,
  Bot,
  CheckCircle2,
  Clock3,
  Loader2,
  RefreshCw,
  Sparkles,
  TriangleAlert,
} from "lucide-react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";

import { getApiErrorMessage } from "../api/client";
import { fetchDocGenResult } from "../api/graphApi";
import { TopBar } from "../components/layout/TopBar";
import { Button } from "../components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/Card";
import { MarkdownViewer } from "../components/ui/MarkdownViewer";

function formatDateTime(value: string | null): string {
  if (!value) {
    return "暂无";
  }
  return new Date(value).toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function getJobTone(status: string | undefined): string {
  if (status === "completed") {
    return "border-emerald-200 bg-emerald-50 text-emerald-700";
  }
  if (status === "failed") {
    return "border-red-200 bg-red-50 text-red-700";
  }
  return "border-blue-200 bg-blue-50 text-blue-700";
}

export function DocPage() {
  const navigate = useNavigate();
  const { subjectId = "" } = useParams<{ subjectId: string }>();
  const [searchParams] = useSearchParams();
  const requestedJobId = searchParams.get("job_id");

  const {
    data,
    isLoading,
    isError,
    error,
    refetch,
  } = useQuery({
    queryKey: ["docgen-result", subjectId],
    queryFn: () => fetchDocGenResult(subjectId),
    enabled: !!subjectId,
    refetchInterval: (query) => {
      const result = query.state.data;
      if (!result) {
        return 2500;
      }
      const status = result.job?.status;
      if (!result.exists && (!status || status === "pending" || status === "processing")) {
        return 2500;
      }
      return false;
    },
  });

  const progress = data?.job?.progress ?? 0;
  const isProcessing = useMemo(() => {
    if (!data) {
      return isLoading;
    }
    if (data.exists) {
      return false;
    }
    const status = data.job?.status;
    return !status || status === "pending" || status === "processing";
  }, [data, isLoading]);

  return (
    <div className="min-h-screen bg-[linear-gradient(180deg,#f8fafc_0%,#eef5ff_100%)]">
      <div className="fixed right-4 top-3 z-50">
        <TopBar />
      </div>

      <main className="mx-auto flex w-full max-w-6xl flex-col gap-6 px-4 pb-10 pt-20 md:px-6">
        <section className="overflow-hidden rounded-[28px] border border-slate-200 bg-[radial-gradient(circle_at_top_left,_rgba(14,165,233,0.16),_transparent_35%),radial-gradient(circle_at_bottom_right,_rgba(251,191,36,0.16),_transparent_28%),linear-gradient(135deg,#ffffff_0%,#f8fafc_60%,#eef6ff_100%)] shadow-sm">
          <div className="flex flex-col gap-5 p-6 md:flex-row md:items-start md:justify-between md:p-8">
            <div className="space-y-3">
              <div className="inline-flex items-center gap-2 rounded-full border border-sky-200 bg-white/80 px-3 py-1 text-xs font-medium text-sky-700">
                <Sparkles className="h-3.5 w-3.5" />
                知识文档页
              </div>
              <div className="space-y-2">
                <h1 className="text-3xl font-semibold tracking-tight text-slate-900 md:text-4xl">
                  知识文档已切到真实数据链路
                </h1>
                <p className="max-w-3xl text-sm leading-6 text-slate-600 md:text-base">
                  这个页面现在直接读取后端 `knowledge/docgen/get`。如果文档还在生成，就显示任务进度；一旦本地 merged 文档落盘，就直接展示最终 Markdown。
                </p>
              </div>
            </div>

            <div className="flex flex-wrap gap-3">
              <Button
                variant="outline"
                onClick={() => navigate(`/subject/${subjectId}/upload`)}
              >
                <ArrowLeft className="h-4 w-4" />
                返回上传页
              </Button>
              <Button
                variant="outline"
                onClick={() => void refetch()}
              >
                <RefreshCw className="h-4 w-4" />
                刷新
              </Button>
              <Button onClick={() => navigate(`/subject/${subjectId}/chat`)}>
                <Bot className="h-4 w-4" />
                前往对话
              </Button>
            </div>
          </div>
        </section>

        <section className="grid gap-6 xl:grid-cols-[320px_minmax(0,1fr)]">
          <div className="space-y-6">
            <Card className="rounded-[24px]">
              <CardHeader className="pb-4">
                <CardTitle className="text-xl text-slate-900">生成状态</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                {isLoading && (
                  <div className="flex items-center gap-3 rounded-2xl border border-blue-200 bg-blue-50 px-4 py-4 text-sm text-blue-700">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    正在加载知识文档状态...
                  </div>
                )}

                {isError && (
                  <div className="space-y-3 rounded-2xl border border-red-200 bg-red-50 px-4 py-4 text-sm text-red-600">
                    <div className="flex items-center gap-2 font-medium">
                      <TriangleAlert className="h-4 w-4" />
                      文档状态加载失败
                    </div>
                    <p>{getApiErrorMessage(error, "请稍后重试")}</p>
                  </div>
                )}

                {!isLoading && !isError && (
                  <>
                    <div className={`rounded-2xl border px-4 py-4 ${getJobTone(data?.job?.status)}`}>
                      <div className="flex items-start gap-3">
                        {data?.exists ? (
                          <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-emerald-500" />
                        ) : isProcessing ? (
                          <Loader2 className="mt-0.5 h-5 w-5 shrink-0 animate-spin text-blue-500" />
                        ) : (
                          <Clock3 className="mt-0.5 h-5 w-5 shrink-0 text-blue-500" />
                        )}
                        <div className="min-w-0 flex-1 space-y-2">
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <p className="text-sm font-semibold">
                              {data?.exists
                                ? "知识文档已生成"
                                : data?.job?.status === "failed"
                                  ? "知识文档生成失败"
                                  : isProcessing
                                    ? "知识文档生成中"
                                    : "等待生成"}
                            </p>
                            {data?.job && (
                              <span className="text-xs font-medium">
                                {data.job.progress}%
                              </span>
                            )}
                          </div>
                          {!data?.exists && data?.job && (
                            <div className="h-2 overflow-hidden rounded-full bg-white/70">
                              <div
                                className={`h-full rounded-full transition-all duration-500 ${
                                  data.job.status === "failed" ? "bg-red-400" : "bg-blue-500"
                                }`}
                                style={{ width: `${Math.min(progress, 100)}%` }}
                              />
                            </div>
                          )}
                          <p className="text-xs leading-5 opacity-90">
                            {data?.job?.current_step
                              ? `当前步骤：${data.job.current_step}`
                              : data?.exists
                                ? "本地 merged 文档已存在，页面正在直接展示最终 Markdown。"
                                : "等待后台工作流继续推进。"}
                          </p>
                          {data?.job?.error_message && (
                            <p className="rounded-xl bg-white/70 px-3 py-2 text-xs leading-5 text-red-600">
                              {data.job.error_message}
                            </p>
                          )}
                        </div>
                      </div>
                    </div>

                    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-1">
                      <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
                        <p className="text-xs uppercase tracking-[0.2em] text-slate-400">
                          关联文件
                        </p>
                        <p className="mt-2 text-2xl font-semibold text-slate-900">
                          {data?.source_file_ids.length ?? 0}
                        </p>
                      </div>
                      <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
                        <p className="text-xs uppercase tracking-[0.2em] text-slate-400">
                          最近更新
                        </p>
                        <p className="mt-2 text-sm font-medium text-slate-700">
                          {formatDateTime(data?.updated_at ?? null)}
                        </p>
                      </div>
                      <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4 sm:col-span-2 xl:col-span-1">
                        <p className="text-xs uppercase tracking-[0.2em] text-slate-400">
                          Job ID
                        </p>
                        <p className="mt-2 break-all text-sm font-medium text-slate-700">
                          {data?.job?.id ?? requestedJobId ?? "暂无"}
                        </p>
                      </div>
                    </div>

                    {data?.prompt && (
                      <div className="rounded-2xl border border-slate-200 bg-white px-4 py-4">
                        <p className="text-xs uppercase tracking-[0.2em] text-slate-400">
                          生成要求
                        </p>
                        <p className="mt-2 text-sm leading-6 text-slate-600">
                          {data.prompt}
                        </p>
                      </div>
                    )}
                  </>
                )}
              </CardContent>
            </Card>
          </div>

          <Card className="rounded-[28px]">
            <CardContent className="p-0">
              <div className="border-b border-slate-200 px-6 py-5 md:px-8">
                <div className="flex items-center gap-3">
                  <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-slate-100 text-slate-600">
                    <BookOpenText className="h-5 w-5" />
                  </div>
                  <div>
                    <h2 className="text-lg font-semibold text-slate-900">
                      知识文档正文
                    </h2>
                    <p className="text-sm text-slate-500">
                      {data?.exists
                        ? "已展示最终 merged Markdown"
                        : "文档生成完成后会自动切换为最终内容"}
                    </p>
                  </div>
                </div>
              </div>

              <div className="px-6 py-6 md:px-8 md:py-8">
                {isLoading && (
                  <div className="flex min-h-[360px] items-center justify-center rounded-[24px] border border-dashed border-slate-200 bg-slate-50 text-sm text-slate-500">
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    正在准备知识文档...
                  </div>
                )}

                {isError && (
                  <div className="flex min-h-[360px] flex-col items-center justify-center gap-3 rounded-[24px] border border-red-200 bg-red-50 px-6 text-center text-sm text-red-600">
                    <TriangleAlert className="h-6 w-6" />
                    <p>{getApiErrorMessage(error, "知识文档加载失败")}</p>
                  </div>
                )}

                {!isLoading && !isError && !data?.exists && (
                  <div className="flex min-h-[360px] flex-col items-center justify-center gap-4 rounded-[24px] border border-dashed border-slate-200 bg-slate-50 px-6 text-center">
                    {isProcessing ? (
                      <Loader2 className="h-8 w-8 animate-spin text-blue-500" />
                    ) : (
                      <Clock3 className="h-8 w-8 text-slate-400" />
                    )}
                    <div className="space-y-2">
                      <p className="text-lg font-medium text-slate-900">
                        {isProcessing ? "知识文档还在生成中" : "还没有可展示的知识文档"}
                      </p>
                      <p className="max-w-xl text-sm leading-6 text-slate-500">
                        {isProcessing
                          ? "页面会自动轮询同一个接口。一旦 merged_knowledge_base.md 落盘，这里会直接显示最终 Markdown。"
                          : "回到上传页后点击“开始对话”，系统会基于已解析文件启动知识文档生成。"}
                      </p>
                    </div>
                  </div>
                )}

                {!isLoading && !isError && data?.exists && (
                  <article className="prose prose-slate max-w-none">
                    <MarkdownViewer content={data.markdown} />
                  </article>
                )}
              </div>
            </CardContent>
          </Card>
        </section>
      </main>
    </div>
  );
}
