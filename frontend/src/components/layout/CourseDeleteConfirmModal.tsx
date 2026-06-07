import { AlertTriangle, Loader2, Trash2 } from "lucide-react";

import type { CourseDeletePreviewData, CourseItem } from "../../api/generated/model";
import { CourseOperationModal } from "../course/CourseOperationModal";
import { Button } from "../ui/Button";

interface CourseDeleteConfirmModalProps {
  open: boolean;
  course: CourseItem | null;
  preview: CourseDeletePreviewData | null;
  isPreviewLoading: boolean;
  previewError?: string;
  isDeleting: boolean;
  deleteError?: string;
  onClose: () => void;
  onConfirm: () => void;
}

export function CourseDeleteConfirmModal({
  open,
  course,
  preview,
  isPreviewLoading,
  previewError,
  isDeleting,
  deleteError,
  onClose,
  onConfirm,
}: CourseDeleteConfirmModalProps) {
  const courseName = preview?.course_name || course?.name || "该课程";
  const impactItems = preview?.impact_items ?? [];

  if (!open) {
    return null;
  }

  return (
    <CourseOperationModal
      eyebrow="Delete"
      title="删除课程"
      description={`你正在删除「${courseName}」。系统会先核对关联内容，再执行不可撤销的删除。`}
      icon={Trash2}
      tone="danger"
      onClose={onClose}
      sidebar={
        <div className="space-y-4">
          <div className="rounded-2xl border border-red-100 bg-white/75 p-4 dark:border-red-500/20 dark:bg-slate-950/35">
            <div className="text-xs font-medium text-red-700 dark:text-red-300">风险级别</div>
            <div className="mt-2 text-sm font-semibold text-slate-950 dark:text-slate-50">不可撤销</div>
            <p className="mt-2 text-xs leading-5 text-slate-500 dark:text-slate-400">
              删除后课程文件关联、知识数据、试卷记录和学习画像会一并移除。
            </p>
          </div>
          <div className="text-xs leading-5 text-slate-500 dark:text-slate-400">
            如果只是暂时不想看到课程，后续应优先做归档能力；当前删除会真实清理数据。
          </div>
        </div>
      }
      footer={
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="text-xs leading-5 text-slate-500 dark:text-slate-400">
            {preview
              ? `将影响 ${preview.total_related_records} 条关联记录`
              : isPreviewLoading
                ? "正在核对删除影响"
                : "等待删除预览"}
          </div>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={onClose} disabled={isDeleting} className="rounded-xl text-slate-500 hover:text-slate-900">
              取消
            </Button>
            <Button
              onClick={onConfirm}
              disabled={isPreviewLoading || !preview || isDeleting}
              className="rounded-xl border border-red-200 bg-white px-4 text-red-700 shadow-none hover:border-red-300 hover:bg-red-50 hover:shadow-none dark:border-red-500/30 dark:bg-slate-950 dark:text-red-300 dark:hover:bg-red-500/10"
            >
              {isDeleting ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  删除中
                </>
              ) : (
                <>
                  <Trash2 className="h-4 w-4" />
                  确认删除
                </>
              )}
            </Button>
          </div>
        </div>
      }
    >
      <div className="space-y-5">
        <section className="border-b border-slate-100 pb-5 dark:border-slate-800">
          <div className="flex items-start gap-3">
            <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-2xl border border-red-100 bg-red-50 text-red-600 dark:border-red-500/20 dark:bg-red-500/10 dark:text-red-300">
              <AlertTriangle className="h-4 w-4" />
            </span>
            <div className="min-w-0">
              <h3 className="text-base font-semibold tracking-tight text-slate-950 dark:text-slate-50">删除影响</h3>
              <p className="mt-1 text-sm leading-6 text-slate-500 dark:text-slate-400">
                请核对下方项目。确认后，课程和这些关联内容会从当前空间中移除。
              </p>
            </div>
          </div>
        </section>

        {isPreviewLoading ? (
          <div className="space-y-3">
            {[0, 1, 2].map((item) => (
              <div key={item} className="rounded-2xl border border-slate-100 px-4 py-4 dark:border-slate-800">
                <div className="flex items-center justify-between gap-4">
                  <div className="h-4 w-32 animate-pulse rounded bg-slate-100 dark:bg-slate-800" />
                  <div className="h-4 w-8 animate-pulse rounded bg-slate-100 dark:bg-slate-800" />
                </div>
                <div className="mt-3 h-3 w-72 max-w-full animate-pulse rounded bg-slate-100 dark:bg-slate-800" />
              </div>
            ))}
          </div>
        ) : null}

        {!isPreviewLoading && preview ? (
          <div className="space-y-4">
            <div className="flex items-end justify-between gap-4 rounded-2xl border border-slate-200 bg-slate-50/70 px-4 py-3 dark:border-slate-800 dark:bg-slate-900/35">
              <div>
                <div className="text-xs font-medium text-slate-500 dark:text-slate-400">关联记录</div>
                <div className="mt-1 text-sm font-semibold text-slate-950 dark:text-slate-50">即将被删除</div>
              </div>
              <div className="font-mono text-2xl font-semibold tracking-tight text-slate-950 dark:text-slate-50">
                {preview.total_related_records}
              </div>
            </div>

            <div className="divide-y divide-slate-100 overflow-hidden rounded-2xl border border-slate-200 dark:divide-slate-800 dark:border-slate-800">
              {impactItems.length > 0 ? (
                impactItems.map((item) => (
                  <div key={item.key} className="px-4 py-3.5">
                    <div className="flex items-start justify-between gap-4">
                      <div className="min-w-0">
                        <div className="text-sm font-semibold text-slate-950 dark:text-slate-50">{item.label}</div>
                        <p className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">{item.description}</p>
                      </div>
                      <div className="shrink-0 rounded-full bg-slate-100 px-2 py-0.5 font-mono text-xs text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                        {item.count}
                      </div>
                    </div>
                  </div>
                ))
              ) : (
                <div className="px-4 py-3.5 text-sm text-slate-500 dark:text-slate-400">
                  当前课程下没有关联内容，只会删除课程本身。
                </div>
              )}
            </div>
          </div>
        ) : null}

        {previewError || deleteError ? (
          <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm leading-6 text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
            {deleteError || previewError}
          </div>
        ) : null}
      </div>
    </CourseOperationModal>
  );
}
