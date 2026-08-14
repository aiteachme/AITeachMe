import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Copy, ExternalLink, Link2, Loader2, RotateCcw, Share2 } from "lucide-react";

import { apiClient, getApiErrorMessage } from "../../api/client";
import type { ApiResponse } from "../../api/types";
import type { CourseShareData } from "../../api/generated/model";
import { buildCourseShareUrl } from "../../lib/courseSharing";
import { Button } from "../ui/Button";
import { useToast } from "../ui/Toast";
import { CourseOperationModal } from "./CourseOperationModal";

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
  const shareUrl = activeShare ? buildCourseShareUrl(activeShare) : "";

  const createMutation = useMutation({
    mutationFn: async () => {
      const response = await apiClient<ApiResponse<CourseShareData>>({
        method: "POST",
        url: `/api/v1/courses/${encodeURIComponent(courseId)}/shares`,
        data: {
          expires_in_days: 30,
        },
      });
      if (!response.data) throw new Error("分享链接创建失败");
      return response.data;
    },
    onSuccess: async (data) => {
      await queryClient.invalidateQueries({ queryKey });
      const url = buildCourseShareUrl(data);
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
        description: copiedUrl ? "链接已复制，别人打开后可浏览已发布课程内容。" : "链接已生成，别人打开后可浏览已发布课程内容。",
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
      description="生成只读课程快照链接；仅分享已发布内容，不包含学习画像、对话和作答记录。"
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
              {formatDateTime(activeShare.expires_at)} 前有效 · 已保存 {activeShare.import_count ?? 0} 次 · 仅包含已发布课程内容，不含学习画像、对话和作答记录。
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

            <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-3 dark:border-slate-800 dark:bg-slate-900/60">
              <p className="text-sm font-semibold text-slate-950 dark:text-slate-50">分享范围</p>
              <p className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">
                分享已发布的课程知识内容及其引用资源，不包含学习画像、对话和作答记录。
              </p>
            </div>
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
