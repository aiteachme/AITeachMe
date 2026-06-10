import { useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { FileArchive, Loader2, UploadCloud } from "lucide-react";

import { getApiErrorMessage } from "../../api/client";
import { importCoursePackage, type ImportResultData } from "../../lib/coursePackage";
import { notifyCoursesImported } from "../../lib/courseEvents";
import { cn } from "../../lib/utils";
import { Button } from "../ui/Button";
import { useToast } from "../ui/Toast";
import { CourseOperationModal } from "./CourseOperationModal";

interface CourseImportModalProps {
  onClose: () => void;
  onImported?: (result: ImportResultData) => void;
}

function formatFileSize(bytes?: number | null): string {
  if (bytes == null || !Number.isFinite(bytes)) return "未知大小";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  return `${value >= 10 || unitIndex === 0 ? value.toFixed(0) : value.toFixed(1)} ${units[unitIndex]}`;
}

function isSupportedPackage(file: File): boolean {
  const filename = file.name.toLowerCase();
  return filename.endsWith(".atmx") || filename.endsWith(".zip");
}

export function CourseImportModal({ onClose, onImported }: CourseImportModalProps) {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [customName, setCustomName] = useState("");
  const [dragOver, setDragOver] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const selectFile = (file: File | undefined) => {
    if (!file) {
      return;
    }
    if (!isSupportedPackage(file)) {
      setSelectedFile(null);
      setLocalError("请选择 .atmx 或 .zip 格式的课程包。");
      return;
    }
    setSelectedFile(file);
    setLocalError(null);
  };

  const importMutation = useMutation({
    mutationFn: () => {
      if (!selectedFile) {
        throw new Error("请先选择课程包文件");
      }
      return importCoursePackage(selectedFile, customName);
    },
    onSuccess: async (result) => {
      notifyCoursesImported({ courseId: result.course_id });
      await queryClient.invalidateQueries({ queryKey: ["courses"] });
      await queryClient.invalidateQueries({ queryKey: ["available-demo-courses"] });
      toast({
        title: "导入成功",
        description: `${result.course_name} 已加入课程列表。`,
        variant: "success",
      });
      onImported?.(result);
      onClose();
    },
  });

  return (
    <CourseOperationModal
      title="导入课程"
      icon={UploadCloud}
      tone="emerald"
      onClose={onClose}
      footer={
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose} className="rounded-md text-slate-500 hover:text-slate-900">
            取消
          </Button>
          <Button
            type="button"
            onClick={() => importMutation.mutate()}
            disabled={!selectedFile || importMutation.isPending}
            className="rounded-md bg-slate-950 px-4 text-white shadow-none hover:bg-slate-800 hover:shadow-none dark:bg-slate-100 dark:text-slate-950 dark:hover:bg-white"
          >
            {importMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <UploadCloud className="h-4 w-4" />}
            导入
          </Button>
        </div>
      }
    >
      <input
        ref={inputRef}
        type="file"
        accept=".atmx,.zip"
        className="hidden"
        onChange={(event) => {
          selectFile(event.target.files?.[0]);
          if (inputRef.current) {
            inputRef.current.value = "";
          }
        }}
      />

      <div className="space-y-4">
        <section>
          <button
            type="button"
            onDragOver={(event) => {
              event.preventDefault();
              setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(event) => {
              event.preventDefault();
              setDragOver(false);
              selectFile(event.dataTransfer.files[0]);
            }}
            onClick={() => inputRef.current?.click()}
            aria-label="选择或拖入课程包"
            className={cn(
              "flex min-h-40 w-full flex-col items-center justify-center rounded-lg border border-dashed px-6 py-8 text-center transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-300 dark:focus-visible:ring-slate-700",
              dragOver
                ? "border-emerald-300 bg-emerald-50 dark:border-emerald-500/40 dark:bg-emerald-950/20"
                : selectedFile
                  ? "border-slate-300 bg-slate-50 dark:border-slate-700 dark:bg-slate-900/55"
                  : "border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50/80 dark:border-slate-800 dark:bg-slate-950 dark:hover:border-slate-700 dark:hover:bg-slate-900/45",
            )}
          >
            <span className="flex h-12 w-12 items-center justify-center rounded-full border border-slate-200 bg-white text-slate-500 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
              {selectedFile ? <FileArchive className="h-5 w-5" /> : <UploadCloud className="h-5 w-5" />}
            </span>
            <span className="mt-4 min-w-0">
              {selectedFile ? (
                <>
                  <span className="block max-w-full truncate text-sm font-semibold text-slate-950 dark:text-slate-50">{selectedFile.name}</span>
                  <span className="mt-1 block text-xs text-slate-500 dark:text-slate-400">{formatFileSize(selectedFile.size)}</span>
                </>
              ) : (
                <>
                  <span className="block text-sm font-semibold text-slate-950 dark:text-slate-50">选择或拖入课程包</span>
                  <span className="mt-1 block text-xs text-slate-500 dark:text-slate-400">.atmx / .zip</span>
                </>
              )}
            </span>
          </button>
        </section>

        <section>
          <label className="block">
            <span className="text-sm font-medium text-slate-800 dark:text-slate-200">课程名称</span>
            <input
              type="text"
              value={customName}
              onChange={(event) => setCustomName(event.target.value)}
              placeholder="留空则使用课程包名称"
              className="mt-2 h-11 w-full rounded-md border border-slate-200 bg-white px-3 text-sm text-slate-900 placeholder:text-slate-400 transition focus:border-slate-400 focus:outline-none focus:ring-2 focus:ring-slate-200 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:placeholder:text-slate-500 dark:focus:border-slate-500 dark:focus:ring-slate-800"
            />
          </label>
        </section>

        {localError || importMutation.isError ? (
          <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm leading-6 text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
            {localError ?? getApiErrorMessage(importMutation.error, "导入失败，请重试")}
          </div>
        ) : null}
      </div>
    </CourseOperationModal>
  );
}
