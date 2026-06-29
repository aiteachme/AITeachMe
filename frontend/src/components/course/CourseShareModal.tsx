import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Copy, ExternalLink, Link2, Loader2, RotateCcw, Share2 } from "lucide-react";

import { apiClient, getApiErrorMessage } from "../../api/client";
import type { ApiResponse } from "../../api/types";
import type { CourseShareData, ExportOptions } from "../../api/generated/model";
import { Button } from "../ui/Button";
import { useToast } from "../ui/Toast";
import { CourseOperationModal } from "./CourseOperationModal";

const BASE_SHARE_OPTIONS: Required<ExportOptions> = {
  include_raw_files: false,
  include_raw_markdowns: true,
  include_knowledge_docs: true,
  include_chat_history: false,
  include_exam_history: false,
  include_profile: false,
};

function buildShareUrl(share: CourseShareData): string {
  const path = share.share_path || (share.token ? `/share/courses/${share.token}` : "");
  if (!path || typeof window === "undefined") {
    return path;
  }
  return new URL(path, window.location.origin).toString();
}

function formatDateTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

interface CourseShareModalProps {
  courseId: string;
  onClose: () => void;
}

export function CourseShareModal({ courseId, onClose }: CourseShareModalProps) {
  const [includeExam, setIncludeExam] = useState(false);
  const [copied, setCopied] = useState(false);
  const { toast } = useToast();
  const queryClient = useQueryClient();

  const queryKey = ["course-shares", courseId];
  const sharesQuery = useQuery({
    queryKey,
    queryFn: async (): Promise<CourseShareData[]> => {
      const response = await apiClient<ApiResponse<CourseShareData[]>>({
        method: "GET",
        url: `/api/v1/courses/${encodeURIComponent(courseId)}/shares`,
      });
      return response.data ?? [];
    },
  });

  const activeShare = useMemo(() => {
    return (sharesQuery.data ?? []).find((item) => item.status === "active" && item.can_import && item.token);
  }, [sharesQuery.data]);
  const shareUrl = activeShare ? buildShareUrl(activeShare) : "";

  const createMutation = useMutation({
    mutationFn: async () => {
      const exportOptions = {
        ...BASE_SHARE_OPTIONS,
        include_exam_history: includeExam,
      };
      const response = await apiClient<ApiResponse<CourseShareData>>({
        method: "POST",
        url: `/api/v1/courses/${encodeURIComponent(courseId)}/shares`,
        data: {
          expires_in_days: 30,
          export_options: exportOptions,
        },
      });
      if (!response.data) throw new Error("分享链接创建失败");
      return response.data;
    },
    onSuccess: async (data) => {
      await queryClient.invalidateQueries({ queryKey });
      const url = buildShareUrl(data);
      let copiedUrl = false;
      try {
        if (url && navigator.clipboard) {
          await navigator.clipboard.writeText(url);
          setCopied(true);
          copiedUrl = true;
        }
      } catch {
        setCopied(false);
      }
      toast({
        title: "分享链接已创建",
        description: copiedUrl ? "链接已复制，别人打开后可直接浏览课程。" : "链接已生成，别人打开后可直接浏览课程。",
        variant: "success",
      });
    },
  });

  const revokeMutation = useMutation({
    mutationFn: async (shareId: string) => {
      const response = await apiClient<ApiResponse<CourseShareData>>({
        method: "DELETE",
        url: `/api/v1/courses/${encodeURIComponent(courseId)}/shares/${encodeURIComponent(shareId)}`,
      });
      if (!response.data) throw new Error("撤销分享失败");
      return response.data;
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey });
      setCopied(false);
      toast({ title: "分享已撤销", description: "旧链接将不能继续访问这门课程。", variant: "success" });
    },
  });

  const copyShareUrl = async () => {
    if (!shareUrl) return;
    if (!navigator.clipboard) {
      toast({ title: "请手动复制链接", description: "当前浏览器不支持自动写入剪贴板。" });
      return;
    }
    try {
      await navigator.clipboard.writeText(shareUrl);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      toast({ title: "复制失败", description: "请手动选中链接复制。" });
    }
  };

  return (
    <CourseOperationModal
      title="分享课程"
      description="生成一个可打开浏览的课程链接；保存到自己的课程需要登录。"
      icon={Share2}
      tone="slate"
      onClose={onClose}
      className="max-w-[560px]"
      footer={
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose} className="rounded-md text-slate-500 hover:text-slate-900">
            {activeShare ? "完成" : "取消"}
          </Button>
          {activeShare ? (
            <Button
              type="button"
              variant="outline"
              disabled={revokeMutation.isPending}
              onClick={() => revokeMutation.mutate(activeShare.share_id)}
              className="rounded-md border-red-200 text-red-600 hover:bg-red-50 hover:text-red-700 dark:border-red-500/30 dark:text-red-300 dark:hover:bg-red-500/10"
            >
              {revokeMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <RotateCcw className="h-4 w-4" />}
              关闭分享
            </Button>
          ) : (
            <Button
              type="button"
              onClick={() => createMutation.mutate()}
              disabled={sharesQuery.isLoading || createMutation.isPending}
              className="rounded-md bg-slate-950 px-4 text-white shadow-none hover:bg-slate-800 hover:shadow-none dark:bg-slate-100 dark:text-slate-950 dark:hover:bg-white"
            >
              {createMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Share2 className="h-4 w-4" />}
              创建链接
            </Button>
          )}
        </div>
      }
    >
      <div className="space-y-4">
        {sharesQuery.isLoading ? (
          <div className="space-y-3">
            <div className="h-16 animate-pulse rounded-lg bg-slate-100 dark:bg-slate-800" />
            <div className="h-11 animate-pulse rounded-md bg-slate-100 dark:bg-slate-800" />
          </div>
        ) : activeShare ? (
          <section className="space-y-4">
            <div className="flex items-center justify-between gap-4 rounded-lg border border-slate-200 px-3 py-3 dark:border-slate-800">
              <div className="flex min-w-0 items-center gap-3">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-slate-100 text-slate-600 dark:bg-slate-900 dark:text-slate-300">
                  <Link2 className="h-4 w-4" />
                </span>
                <span className="min-w-0">
                  <span className="block text-sm font-semibold text-slate-950 dark:text-slate-50">拥有链接的人</span>
                  <span className="mt-0.5 block text-xs text-slate-500 dark:text-slate-400">可以浏览课程文档，登录后保存副本</span>
                </span>
              </div>
              <span className="shrink-0 rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300">
                已开启
              </span>
            </div>

            <div className="flex items-center gap-2 rounded-md border border-slate-200 bg-white p-1.5 dark:border-slate-800 dark:bg-slate-950">
              <Link2 className="ml-2 h-4 w-4 shrink-0 text-slate-400" />
              <input
                readOnly
                value={shareUrl}
                className="h-9 min-w-0 flex-1 bg-transparent text-sm text-slate-700 outline-none dark:text-slate-200"
                onFocus={(event) => event.currentTarget.select()}
              />
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() => window.open(shareUrl, "_blank", "noopener,noreferrer")}
                className="rounded-md px-3 shadow-none"
              >
                <ExternalLink className="h-4 w-4" />
                打开
              </Button>
              <Button type="button" size="sm" onClick={copyShareUrl} className="rounded-md bg-slate-950 px-3 text-white shadow-none hover:bg-slate-800 hover:shadow-none dark:bg-slate-100 dark:text-slate-950 dark:hover:bg-white">
                {copied ? <Check className="h-4 w-4 text-emerald-600" /> : <Copy className="h-4 w-4" />}
                {copied ? "已复制" : "复制"}
              </Button>
            </div>
            <p className="text-xs leading-5 text-slate-500 dark:text-slate-400">
              {formatDateTime(activeShare.expires_at)} 前有效 · 已保存 {activeShare.import_count ?? 0} 次 · 不包含对话记录和学习画像。
            </p>
          </section>
        ) : (
          <section className="space-y-4">
            <div className="flex items-center justify-between gap-4 rounded-lg border border-slate-200 px-3 py-3 dark:border-slate-800">
              <div className="flex min-w-0 items-center gap-3">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-slate-100 text-slate-600 dark:bg-slate-900 dark:text-slate-300">
                  <Link2 className="h-4 w-4" />
                </span>
                <span className="min-w-0">
                  <span className="block text-sm font-semibold text-slate-950 dark:text-slate-50">拥有链接的人</span>
                  <span className="mt-0.5 block text-xs text-slate-500 dark:text-slate-400">
                    可以浏览课程文档，登录后保存为自己的课程
                  </span>
                </span>
              </div>
              <span className="shrink-0 rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-500 dark:bg-slate-900 dark:text-slate-400">
                未开启
              </span>
            </div>

            <label className="group flex cursor-pointer items-start gap-3 rounded-md px-2.5 py-3 transition hover:bg-slate-50 dark:hover:bg-slate-900/60">
              <input
                type="checkbox"
                checked={includeExam}
                onChange={(event) => setIncludeExam(event.target.checked)}
                className="peer sr-only"
              />
              <span
                aria-hidden="true"
                className={[
                  "mt-1 flex h-4 w-4 shrink-0 items-center justify-center rounded border transition",
                  includeExam
                    ? "border-slate-950 bg-slate-950 text-white dark:border-slate-100 dark:bg-slate-100 dark:text-slate-950"
                    : "border-slate-300 bg-white text-transparent group-hover:border-slate-400 dark:border-slate-700 dark:bg-slate-950 dark:group-hover:border-slate-500",
                ].join(" ")}
              >
                <Check className="h-3 w-3" />
              </span>
              <span className="min-w-0">
                <span className="block text-sm font-semibold text-slate-950 dark:text-slate-50">包含训练题库</span>
                <span className="mt-1 block text-xs leading-5 text-slate-500 dark:text-slate-400">
                  只分享题目，不分享作答记录。
                </span>
              </span>
            </label>
          </section>
        )}

        {sharesQuery.isError || createMutation.isError || revokeMutation.isError ? (
          <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm leading-6 text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
            {getApiErrorMessage(sharesQuery.error || createMutation.error || revokeMutation.error, "分享操作失败，请重试")}
          </div>
        ) : null}
      </div>
    </CourseOperationModal>
  );
}
