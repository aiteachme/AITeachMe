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

  if (!open) {
    return null;
  }

  return (
    <CourseOperationModal
      eyebrow="危险操作"
      title="删除课程"
      description={`删除「${courseName}」及其关联学习数据。此操作不可恢复。`}
      icon={Trash2}
      tone="danger"
      onClose={onClose}
      className="max-w-[520px]"
      footer={
        <div className="flex justify-end gap-2">
          <Button
            variant="ghost"
            onClick={onClose}
            disabled={isDeleting}
            className="rounded-md text-slate-500 hover:text-slate-900 dark:hover:text-slate-100"
          >
            取消
          </Button>
          <Button
            onClick={onConfirm}
            disabled={isDeleting || !course}
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
                删除
              </>
            )}
          </Button>
        </div>
      }
    >
      <div className="space-y-3">
        <p className="text-sm leading-6 text-slate-600 dark:text-slate-400">
          会一并移除课程文档、知识图谱、测验、画像和对话记录。需要保留内容时，请先导出课程包。
        </p>

        {isPreviewLoading ? (
          <div className="flex items-center gap-2 rounded-md bg-slate-50 px-3 py-2 text-xs text-slate-500 dark:bg-slate-900 dark:text-slate-400">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            正在核对关联内容，不影响直接删除。
          </div>
        ) : null}

        {previewError || deleteError ? (
          <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm leading-6 text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
            {deleteError || previewError}
          </div>
        ) : null}
      </div>
    </CourseOperationModal>
  );
}
