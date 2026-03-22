import { AlertTriangle, Loader2, Trash2 } from "lucide-react";

import type {
  SubjectDeletePreviewData,
  SubjectItem,
} from "../../api/generated/model";
import { Button } from "../ui/Button";
import { Modal } from "../ui/Modal";

interface SubjectDeleteConfirmModalProps {
  open: boolean;
  subject: SubjectItem | null;
  preview: SubjectDeletePreviewData | null;
  isPreviewLoading: boolean;
  previewError?: string;
  isDeleting: boolean;
  deleteError?: string;
  onClose: () => void;
  onConfirm: () => void;
}

export function SubjectDeleteConfirmModal({
  open,
  subject,
  preview,
  isPreviewLoading,
  previewError,
  isDeleting,
  deleteError,
  onClose,
  onConfirm,
}: SubjectDeleteConfirmModalProps) {
  const subjectName = preview?.subject_name || subject?.name || "该学科";
  const impactItems = preview?.impact_items ?? [];

  return (
    <Modal open={open} onClose={onClose} title="确认删除学科" className="max-w-2xl">
      <div className="space-y-4">
        <div className="flex items-start gap-3 rounded-lg bg-red-50 p-4">
          <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-red-500" />
          <div className="space-y-2 text-sm text-red-700">
            <p>
              删除“<span className="font-medium">{subjectName}</span>”后，学科下的文件、知识数据、试卷记录和学习画像都会一起被删除。
            </p>
            <p className="font-medium">这个操作不可撤销。</p>
          </div>
        </div>

        {isPreviewLoading && (
          <div className="flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-500">
            <Loader2 className="h-4 w-4 animate-spin" />
            正在计算将被删除的内容...
          </div>
        )}

        {!isPreviewLoading && preview && (
          <div className="space-y-3">
            <div className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700">
              共检测到 <span className="font-semibold text-slate-900">{preview.total_related_records}</span> 条关联记录。
            </div>
            <div className="space-y-2">
              {impactItems.length > 0 ? (
                impactItems.map((item) => (
                  <div
                    key={item.key}
                    className="rounded-lg border border-slate-200 px-4 py-3"
                  >
                    <div className="flex items-center justify-between gap-3">
                      <div className="font-medium text-slate-900">{item.label}</div>
                      <div className="text-sm font-semibold text-slate-900">{item.count}</div>
                    </div>
                    <p className="mt-1 text-sm text-slate-500">{item.description}</p>
                  </div>
                ))
              ) : (
                <div className="rounded-lg border border-slate-200 px-4 py-3 text-sm text-slate-500">
                  当前学科下没有关联内容，只会删除学科本身。
                </div>
              )}
            </div>
          </div>
        )}

        {(previewError || deleteError) && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-600">
            {deleteError || previewError}
          </div>
        )}

        <div className="flex justify-end gap-2 pt-2">
          <Button variant="outline" onClick={onClose} disabled={isDeleting}>
            取消
          </Button>
          <Button
            onClick={onConfirm}
            disabled={isPreviewLoading || !preview || isDeleting}
            className="bg-red-500 text-white hover:bg-red-600"
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
