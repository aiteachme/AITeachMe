import { AlertTriangle, RefreshCcw } from "lucide-react";

import { Button } from "../ui/Button";
import { Modal } from "../ui/Modal";

interface SettingsResetConfirmModalProps {
  open: boolean;
  onClose: () => void;
  onConfirm: () => void;
}

export function SettingsResetConfirmModal({
  open,
  onClose,
  onConfirm,
}: SettingsResetConfirmModalProps) {
  return (
    <Modal open={open} onClose={onClose} title="确认恢复默认设置" className="max-w-xl">
      <div className="space-y-4">
        <div className="flex items-start gap-3 rounded-lg bg-amber-50 p-4">
          <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-500" />
          <div className="space-y-2 text-sm text-amber-700">
            <p>
              这会把当前设置页中的可编辑配置恢复为系统默认值，并清空对应的环境变量草稿。
            </p>
            <p>
              这一步还不会立刻写入后端，确认后你仍需要点击“保存更改”才会正式生效。
            </p>
          </div>
        </div>

        <div className="flex justify-end gap-2 pt-2">
          <Button variant="outline" onClick={onClose}>
            取消
          </Button>
          <Button onClick={onConfirm}>
            <RefreshCcw className="h-4 w-4" />
            确认恢复默认
          </Button>
        </div>
      </div>
    </Modal>
  );
}
