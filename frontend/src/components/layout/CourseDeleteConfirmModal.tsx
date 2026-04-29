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
    <Modal open={open} onClose={onClose} title="确认删除课程" className="max-w-2xl">
      <div className="space-y-4">
        <div className="flex items-start gap-3 rounded-lg bg-red-50 p-4 dark:bg-red-500/10">
          <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-red-500 dark:text-red-300" />
          <div className="space-y-2 text-sm text-red-700 dark:text-red-300">
            <p>
              删除 <span className="font-medium">{courseName}</span> 后，课程下的文件、知识数据、试卷记录和学习画像都会一起被删除。
            </p>
            <p className="font-medium">这个操作不可撤销。</p>
          </div>
        </div>

        {isPreviewLoading ? (
          <div className="flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-500 dark:border-slate-800 dark:bg-slate-900/80 dark:text-slate-400">
            <Loader2 className="h-4 w-4 animate-spin" />
            正在计算将被删除的内容...
          </div>
        ) : null}

        {!isPreviewLoading && preview ? (
          <div className="space-y-3">
            <div className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700 dark:border-slate-800 dark:bg-slate-900/80 dark:text-slate-300">
              共检测到{" "}
              <span className="font-semibold text-slate-900 dark:text-slate-100">
                {preview.total_related_records}
              </span>{" "}
              条关联记录。
            </div>

            <div className="space-y-2">
              {impactItems.length > 0 ? (
                impactItems.map((item) => (
                  <div
                    key={item.key}
                    className="rounded-lg border border-slate-200 px-4 py-3 dark:border-slate-800"
                  >
                    <div className="flex items-center justify-between gap-3">
                      <div className="font-medium text-slate-900 dark:text-slate-100">
                        {item.label}
                      </div>
                      <div className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                        {item.count}
                      </div>
                    </div>
                    <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                      {item.description}
                    </p>
                  </div>
                ))
              ) : (
                <div className="rounded-lg border border-slate-200 px-4 py-3 text-sm text-slate-500 dark:border-slate-800 dark:text-slate-400">
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

        <div className="flex justify-end gap-2 pt-2">
          <Button variant="outline" onClick={onClose} disabled={isDeleting}>
            取消
          </Button>
          <Button
            onClick={onConfirm}
            disabled={isPreviewLoading || !preview || isDeleting}
            className="bg-red-500 text-white hover:bg-red-600 dark:bg-red-500 dark:text-white dark:hover:bg-red-400"
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
