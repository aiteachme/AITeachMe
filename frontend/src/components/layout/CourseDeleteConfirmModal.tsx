import { AlertTriangle, Loader2, Trash2 } from "lucide-react";

import type { CourseDeletePreviewData, CourseItem } from "../../api/generated/model";
import { Button } from "../ui/Button";
import { Modal } from "../ui/Modal";

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

  return (
    <Modal open={open} onClose={onClose} title="删除课程" className="max-w-2xl">
      <div className="space-y-5">
        <div className="border-b border-slate-100 pb-4 dark:border-slate-800">
          <div className="flex items-start gap-3">
            <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-red-50 text-red-600 dark:bg-red-500/10 dark:text-red-300">
              <AlertTriangle className="h-4 w-4" />
            </span>
            <div className="min-w-0">
              <p className="text-sm leading-6 text-slate-700 dark:text-slate-300">
                将删除 <span className="font-semibold text-slate-950 dark:text-slate-100">{courseName}</span> 及其关联内容。
              </p>
              <p className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">
                包括课程文件关联、知识数据、试卷记录和学习画像。此操作不可撤销。
              </p>
            </div>
          </div>
        </div>

        {isPreviewLoading ? (
          <div className="flex items-center gap-2 rounded-xl border border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-500 dark:border-slate-800 dark:bg-slate-900/80 dark:text-slate-400">
            <Loader2 className="h-4 w-4 animate-spin" />
            正在计算将被删除的内容...
          </div>
        ) : null}

        {!isPreviewLoading && preview ? (
          <div className="space-y-3">
            <div className="text-sm text-slate-600 dark:text-slate-400">
              将影响{" "}
              <span className="font-semibold text-slate-950 dark:text-slate-100">
                {preview.total_related_records}
              </span>{" "}
              条关联记录
            </div>

            <div className="divide-y divide-slate-100 rounded-xl border border-slate-200 dark:divide-slate-800 dark:border-slate-800">
              {impactItems.length > 0 ? (
                impactItems.map((item) => (
                  <div
                    key={item.key}
                    className="px-4 py-3"
                  >
                    <div className="flex items-center justify-between gap-3">
                      <div className="text-sm font-medium text-slate-900 dark:text-slate-100">
                        {item.label}
                      </div>
                      <div className="font-mono text-xs text-slate-500 dark:text-slate-400">
                        {item.count}
                      </div>
                    </div>
                    <p className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">
                      {item.description}
                    </p>
                  </div>
                ))
              ) : (
                <div className="px-4 py-3 text-sm text-slate-500 dark:text-slate-400">
                  当前课程下没有关联内容，只会删除课程本身。
                </div>
              )}
            </div>
          </div>
        ) : null}

        {previewError || deleteError ? (
          <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-600 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
            {deleteError || previewError}
          </div>
        ) : null}

        <div className="flex justify-end gap-2 border-t border-slate-100 pt-4 dark:border-slate-800">
          <Button variant="ghost" onClick={onClose} disabled={isDeleting} className="text-slate-500 hover:text-slate-900">
            取消
          </Button>
          <Button
            onClick={onConfirm}
            disabled={isPreviewLoading || !preview || isDeleting}
            className="rounded-lg border border-red-200 bg-white text-red-600 shadow-none hover:border-red-300 hover:bg-red-50 hover:shadow-none dark:border-red-500/30 dark:bg-slate-950 dark:text-red-300 dark:hover:bg-red-500/10"
          >
            {isDeleting ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                删除中...
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
    </Modal>
  );
}
