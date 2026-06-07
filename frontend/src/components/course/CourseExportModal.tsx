import { useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Check, CheckCircle2, Download, FileText, Loader2, MessageSquareText, Package, Radar } from "lucide-react";

import { apiClient, getApiErrorMessage } from "../../api/client";
import type { ExportOptions, ExportPreviewData } from "../../api/generated/model";
import type { ApiResponse } from "../../api/types";
import { downloadCoursePackage } from "../../lib/coursePackage";
import { cn } from "../../lib/utils";
import { Button } from "../ui/Button";
import { useToast } from "../ui/Toast";
import { CourseOperationModal } from "./CourseOperationModal";

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
  const canExport = Boolean(stats) && !previewQuery.isLoading && !exportMutation.isPending;

  const toggleOption = (key: ExportOptionKey) => {
    setOptions((current) => ({ ...current, [key]: !current[key] }));
  };

  return (
    <CourseOperationModal
      eyebrow="Export"
      title="导出课程"
      description={
        previewQuery.data?.course_name
          ? `将「${previewQuery.data.course_name}」整理为可迁移的 .atmx 课程包。`
          : "正在读取课程内容，稍后即可选择需要打包的范围。"
      }
      icon={Download}
      tone="blue"
      onClose={onClose}
      sidebar={
        <div className="grid gap-3 text-sm sm:grid-cols-3">
          <div>
            <div className="text-xs text-slate-500 dark:text-slate-400">预计写入</div>
            <div className="mt-1 font-mono text-lg font-semibold text-slate-950 dark:text-slate-50">
              {previewQuery.isLoading ? "--" : selectedDynamicCount + coreCount}
              <span className="ml-1 font-sans text-xs font-normal text-slate-500 dark:text-slate-400">条</span>
            </div>
          </div>
          <div>
            <div className="text-xs text-slate-500 dark:text-slate-400">固定包含</div>
            <div className="mt-1 font-medium leading-5 text-slate-900 dark:text-slate-100">课程结构与知识图谱</div>
          </div>
          <div>
            <div className="text-xs text-slate-500 dark:text-slate-400">不会导出</div>
            <div className="mt-1 font-medium leading-5 text-slate-900 dark:text-slate-100">向量索引与运行锁</div>
          </div>
        </div>
      }
      footer={
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="text-xs leading-5 text-slate-500 dark:text-slate-400">
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
              className="rounded-lg bg-slate-950 px-4 text-white shadow-none hover:bg-slate-800 hover:shadow-none dark:bg-slate-100 dark:text-slate-950 dark:hover:bg-white"
            >
              {exportMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
              导出 .atmx
            </Button>
          </div>
        </div>
      }
    >
      {previewQuery.isLoading ? (
        <div className="space-y-4">
          <div className="border-b border-slate-100 pb-4 dark:border-slate-800">
            <div className="h-5 w-32 animate-pulse rounded bg-slate-100 dark:bg-slate-800" />
            <div className="mt-2 h-4 w-80 max-w-full animate-pulse rounded bg-slate-100 dark:bg-slate-800" />
          </div>
          {[0, 1, 2, 3].map((item) => (
            <div key={item} className="flex items-center gap-3 rounded-lg border border-slate-100 px-4 py-4 dark:border-slate-800">
              <div className="h-5 w-5 animate-pulse rounded bg-slate-100 dark:bg-slate-800" />
              <div className="h-8 w-8 animate-pulse rounded-lg bg-slate-100 dark:bg-slate-800" />
              <div className="min-w-0 flex-1">
                <div className="h-4 w-36 animate-pulse rounded bg-slate-100 dark:bg-slate-800" />
                <div className="mt-2 h-3 w-64 max-w-full animate-pulse rounded bg-slate-100 dark:bg-slate-800" />
              </div>
            </div>
          ))}
        </div>
      ) : stats ? (
        <div className="space-y-5">
          <section className="border-b border-slate-100 pb-5 dark:border-slate-800">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
              <div>
                <h3 className="text-base font-semibold text-slate-950 dark:text-slate-50">打包内容</h3>
                <p className="mt-1 text-sm leading-6 text-slate-500 dark:text-slate-400">
                  选择需要随课程迁移的学习上下文。核心课程结构会自动包含。
                </p>
              </div>
              <div className="rounded-md border border-slate-200 px-2.5 py-1 text-xs font-medium text-slate-500 dark:border-slate-800 dark:text-slate-400">
                核心 {coreCount}
              </div>
            </div>
            <div className="mt-4 rounded-lg border border-slate-200 bg-slate-50/70 px-4 py-3 dark:border-slate-800 dark:bg-slate-900/35">
              <div className="text-sm font-medium text-slate-900 dark:text-slate-100">课程信息、知识图谱节点与关系</div>
              <div className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">
                {(stats?.knowledge_unit_count ?? 0)} 个知识点 / {(stats?.knowledge_edge_count ?? 0)} 条关系会固定写入课程包。
              </div>
            </div>
          </section>

          <section className="divide-y divide-slate-100 overflow-hidden rounded-lg border border-slate-200 dark:divide-slate-800 dark:border-slate-800">
            {optionRows.map((row) => {
              const Icon = row.icon;
              const checked = options[row.key];
              return (
                <label
                  key={row.key}
                  className={cn(
                    "group relative flex cursor-pointer items-start gap-3 px-4 py-4 transition",
                    checked
                      ? "bg-white dark:bg-slate-950"
                      : "bg-slate-50/70 text-slate-500 dark:bg-slate-900/35",
                  )}
                >
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => toggleOption(row.key)}
                    className="peer sr-only"
                  />
                  <span
                    aria-hidden="true"
                    className={cn(
                      "mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded border transition",
                      checked
                        ? "border-slate-950 bg-slate-950 text-white dark:border-slate-100 dark:bg-slate-100 dark:text-slate-950"
                        : "border-slate-300 bg-white text-transparent group-hover:border-slate-400 dark:border-slate-700 dark:bg-slate-950 dark:group-hover:border-slate-500",
                    )}
                  >
                    <Check className="h-3.5 w-3.5" />
                  </span>
                  <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-500 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-400">
                    <Icon className="h-4 w-4" />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="flex items-start justify-between gap-3">
                      <span className="text-sm font-semibold text-slate-950 dark:text-slate-50">{row.title}</span>
                      <span className="shrink-0 rounded-md bg-slate-100 px-2 py-0.5 font-mono text-xs text-slate-500 dark:bg-slate-800 dark:text-slate-400">
                        {row.count}
                      </span>
                    </span>
                    <span className="mt-1 block text-xs leading-5 text-slate-500 dark:text-slate-400">{row.description}</span>
                  </span>
                </label>
              );
            })}
          </section>
        </div>
      ) : (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm leading-6 text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
          {getApiErrorMessage(previewQuery.error, "导出预览加载失败")}
        </div>
      )}

      {exportMutation.isError ? (
        <div className="mt-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm leading-6 text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
          {getApiErrorMessage(exportMutation.error, "导出失败，请重试")}
        </div>
      ) : null}
    </CourseOperationModal>
  );
}
