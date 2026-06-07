import { useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { CheckCircle2, Download, FileText, Loader2, MessageSquareText, Package, Radar, X } from "lucide-react";

import { apiClient, getApiErrorMessage } from "../../api/client";
import type { ExportOptions, ExportPreviewData } from "../../api/generated/model";
import type { ApiResponse } from "../../api/types";
import { downloadCoursePackage } from "../../lib/coursePackage";
import { cn } from "../../lib/utils";
import { Button } from "../ui/Button";
import { useToast } from "../ui/Toast";

const DEFAULT_EXPORT_OPTIONS: Required<ExportOptions> = {
  include_raw_files: false,
  include_raw_markdowns: true,
  include_knowledge_docs: true,
  include_chat_history: true,
  include_exam_history: true,
  include_profile: true,
};

type ExportOptionKey = keyof Required<ExportOptions>;

interface CourseExportModalProps {
  courseId: string;
  onClose: () => void;
}

async function fetchExportPreview(course: string): Promise<ExportPreviewData> {
  const response = await apiClient<ApiResponse<ExportPreviewData>>({
    method: "POST",
    url: `/api/v1/courses/${encodeURIComponent(course)}/export/preview`,
    data: DEFAULT_EXPORT_OPTIONS,
  });
  if (!response.data) {
    throw new Error("导出预览为空");
  }
  return response.data;
}

export function CourseExportModal({ courseId, onClose }: CourseExportModalProps) {
  const [options, setOptions] = useState<Required<ExportOptions>>(DEFAULT_EXPORT_OPTIONS);
  const { toast } = useToast();

  const previewQuery = useQuery({
    queryKey: ["course-export-preview", courseId],
    queryFn: () => fetchExportPreview(courseId),
  });

  const exportMutation = useMutation({
    mutationFn: () => downloadCoursePackage(courseId, options),
    onSuccess: () => {
      toast({
        title: "导出已开始",
        description: "浏览器正在下载 .atmx 课程包。",
        variant: "success",
      });
      onClose();
    },
  });

  const stats = previewQuery.data?.stats;
  const optionRows = useMemo(
    () => [
      {
        key: "include_raw_markdowns" as const,
        title: "资料解析缓存",
        description: "资料记录、解析 Markdown 字段与检索切片",
        count: stats?.raw_file_count ?? 0,
        icon: FileText,
      },
      {
        key: "include_knowledge_docs" as const,
        title: "知识文档与构建计划",
        description: "章节正文、封面与已确认构建方案",
        count: stats?.knowledge_document_count ?? 0,
        icon: Package,
      },
      {
        key: "include_exam_history" as const,
        title: "题库与考试记录",
        description: `${stats?.question_template_count ?? 0} 个题目模板，${stats?.exam_paper_count ?? 0} 份试卷`,
        count: (stats?.question_template_count ?? 0) + (stats?.exam_paper_count ?? 0),
        icon: CheckCircle2,
      },
      {
        key: "include_chat_history" as const,
        title: "对话记录",
        description: "课程内历史会话与消息",
        count: stats?.chat_session_count ?? 0,
        icon: MessageSquareText,
      },
      {
        key: "include_profile" as const,
        title: "学习画像",
        description: "知识点掌握度与复习状态",
        count: stats?.user_knowledge_state_count ?? 0,
        icon: Radar,
      },
    ],
    [stats],
  );

  const selectedRows = optionRows.filter((row) => options[row.key]);
  const selectedDynamicCount = selectedRows.reduce((sum, row) => sum + row.count, 0);
  const coreCount = (stats?.knowledge_unit_count ?? 0) + (stats?.knowledge_edge_count ?? 0);
  const canExport = !previewQuery.isLoading && !exportMutation.isPending;

  const toggleOption = (key: ExportOptionKey) => {
    setOptions((current) => ({ ...current, [key]: !current[key] }));
  };

  return (
    <div className="fixed inset-0 z-[120] flex items-center justify-center p-3 sm:p-6">
      <div className="absolute inset-0 modal-backdrop" onClick={onClose} />
      <div className="relative z-10 flex max-h-[calc(100dvh-1.5rem)] w-full max-w-2xl flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white text-slate-900 shadow-[0_22px_70px_rgba(15,23,42,0.14)] dark:border-slate-800 dark:bg-slate-950 dark:text-slate-100">
        <div className="flex shrink-0 items-start justify-between gap-4 border-b border-slate-100 px-5 py-4 dark:border-slate-800 sm:px-6">
          <div className="min-w-0">
            <div className="text-xs font-medium uppercase tracking-[0.16em] text-slate-400 dark:text-slate-500">Course Package</div>
            <h2 className="mt-1 truncate text-lg font-semibold tracking-tight">{previewQuery.data?.course_name ?? "导出课程"}</h2>
            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">选择要写入 .atmx 包的内容。</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-slate-400 transition hover:bg-slate-100 hover:text-slate-700 dark:text-slate-500 dark:hover:bg-slate-800 dark:hover:text-slate-100"
            aria-label="关闭导出面板"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4 sm:px-6">
          {previewQuery.isLoading ? (
            <div className="flex min-h-[300px] items-center justify-center gap-2 text-sm text-slate-500 dark:text-slate-400">
              <Loader2 className="h-4 w-4 animate-spin" />
              正在统计导出内容...
            </div>
          ) : stats ? (
            <div className="space-y-5">
              <div className="border-b border-slate-100 pb-4 dark:border-slate-800">
                <div className="text-xs font-medium uppercase tracking-[0.14em] text-slate-400 dark:text-slate-500">始终包含</div>
                <div className="mt-2 text-sm font-semibold text-slate-900 dark:text-slate-100">
                  课程信息、知识图谱节点与关系
                </div>
                <div className="mt-1 max-w-xl text-xs leading-5 text-slate-500 dark:text-slate-400">
                  {(stats?.knowledge_unit_count ?? 0)} 个知识点 / {(stats?.knowledge_edge_count ?? 0)} 条关系；原始上传文件、向量索引、临时构建状态和运行时锁不会导出。
                </div>
              </div>

              <div className="divide-y divide-slate-100 rounded-xl border border-slate-200 dark:divide-slate-800 dark:border-slate-800">
                {optionRows.map((row) => {
                  const Icon = row.icon;
                  const checked = options[row.key];
                  return (
                    <label
                      key={row.key}
                      className={cn(
                        "flex cursor-pointer items-start gap-3 px-4 py-3.5 transition",
                        checked
                          ? "bg-white dark:bg-slate-950"
                          : "bg-slate-50/60 opacity-75 dark:bg-slate-900/45",
                      )}
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggleOption(row.key)}
                        className="mt-1 h-4 w-4 rounded border-slate-300 text-slate-900 focus:ring-slate-400 dark:border-slate-600 dark:bg-slate-900"
                      />
                      <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center text-slate-400 dark:text-slate-500">
                        <Icon className="h-4 w-4" />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="flex items-center justify-between gap-3">
                          <span className="text-sm font-medium text-slate-900 dark:text-slate-100">{row.title}</span>
                          <span className="shrink-0 font-mono text-xs text-slate-400 dark:text-slate-500">
                            {row.count}
                          </span>
                        </span>
                        <span className="mt-1 block text-xs leading-5 text-slate-500 dark:text-slate-400">{row.description}</span>
                      </span>
                    </label>
                  );
                })}
              </div>
            </div>
          ) : (
            <div className="rounded-xl border border-red-100 bg-red-50 px-4 py-3 text-sm text-red-600 dark:border-red-900/60 dark:bg-red-950/30 dark:text-red-300">
              {getApiErrorMessage(previewQuery.error, "导出预览加载失败")}
            </div>
          )}

          {exportMutation.isError ? (
            <div className="mt-4 rounded-xl border border-red-100 bg-red-50 px-4 py-3 text-sm text-red-600 dark:border-red-900/60 dark:bg-red-950/30 dark:text-red-300">
              {getApiErrorMessage(exportMutation.error, "导出失败，请重试")}
            </div>
          ) : null}
        </div>

        <div className="flex shrink-0 flex-col gap-3 border-t border-slate-100 bg-white px-5 py-4 dark:border-slate-800 dark:bg-slate-950 sm:flex-row sm:items-center sm:justify-between sm:px-6">
          <div className="text-xs text-slate-500 dark:text-slate-400">
            已选择 {selectedRows.length} 类可选内容，约 {selectedDynamicCount + coreCount} 条记录
          </div>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={onClose} className="rounded-lg text-slate-500 hover:text-slate-900">
              取消
            </Button>
            <Button
              type="button"
              onClick={() => exportMutation.mutate()}
              disabled={!canExport}
              className="rounded-lg bg-slate-900 px-4 text-white shadow-none hover:bg-slate-800 hover:shadow-none dark:bg-slate-100 dark:text-slate-950 dark:hover:bg-white"
            >
              {exportMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
              导出
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
