import { Loader2, Trash2 } from "lucide-react";

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
      eyebrow="危险操作"
      title="删除课程"
      description={`将从当前空间移除「${courseName}」及其关联学习数据。确认前请核对影响范围。`}
      icon={Trash2}
      tone="danger"
      onClose={onClose}
      className="max-w-[640px]"
      sidebar={
        <div className="text-sm leading-6 text-slate-500 dark:text-slate-400">
          <span className="font-medium text-slate-950 dark:text-slate-50">不可撤销。</span>
          需要保留内容时，请先导出课程包。
        </div>
      }
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose} disabled={isDeleting} className="rounded-md text-slate-500 hover:text-slate-900 dark:hover:text-slate-100">
            取消
          </Button>
          <Button
            onClick={onConfirm}
            disabled={isPreviewLoading || !preview || isDeleting}
            className="rounded-md bg-red-600 px-4 text-white shadow-none hover:bg-red-700 hover:shadow-none dark:bg-red-500 dark:text-white dark:hover:bg-red-400"
          >
            {isDeleting ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                删除中
              </>
            ) : (
              <>
                <Trash2 className="h-4 w-4" />
                永久删除
              </>
            )}
          </Button>
        </div>
      }
    >
      <div className="space-y-4">
        {isPreviewLoading ? (
          <div className="space-y-3">
            {[0, 1, 2].map((item) => (
              <div key={item} className="rounded-md px-2 py-3">
                <div className="h-4 w-32 animate-pulse rounded bg-slate-100 dark:bg-slate-800" />
                <div className="mt-3 h-3 w-72 max-w-full animate-pulse rounded bg-slate-100 dark:bg-slate-800" />
              </div>
            ))}
          </div>
        ) : null}

        {!isPreviewLoading && preview ? (
          <div className="space-y-4">
            <div>
              <div className="text-sm font-semibold text-slate-950 dark:text-slate-50">删除影响</div>
              <div className="mt-1 text-sm leading-6 text-slate-500 dark:text-slate-400">
                以下关联内容会随课程一起移除，确认后无法恢复。
              </div>
            </div>

            <div className="space-y-1">
              {impactItems.length > 0 ? (
                impactItems.map((item) => (
                  <div key={item.key} className="rounded-md px-2.5 py-3 transition hover:bg-slate-50 dark:hover:bg-slate-900/60">
                    <div className="flex items-start justify-between gap-4">
                      <div className="min-w-0">
                        <div className="text-sm font-semibold text-slate-950 dark:text-slate-50">{item.label}</div>
                        <p className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">{item.description}</p>
                      </div>
                    </div>
                  </div>
                ))
              ) : (
                <div className="rounded-md px-2.5 py-3 text-sm text-slate-500 dark:text-slate-400">
                  当前课程下没有关联内容，只会删除课程本身。
                </div>
              )}
            </div>
          </div>
        ) : null}

        {previewError || deleteError ? (
          <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm leading-6 text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
            {deleteError || previewError}
          </div>
        ) : null}
      </div>
    </CourseOperationModal>
  );
}
