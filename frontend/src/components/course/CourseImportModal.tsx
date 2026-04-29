import { useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { FileArchive, Loader2, PackagePlus, Upload, X } from "lucide-react";

import { getApiErrorMessage } from "../../api/client";
import { importCoursePackage, type ImportResultData } from "../../lib/coursePackage";
import { notifyCoursesImported } from "../../lib/courseEvents";
import { cn } from "../../lib/utils";
import { Button } from "../ui/Button";
import { useToast } from "../ui/Toast";

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
    <div className="fixed inset-0 z-[120] flex items-center justify-center p-3 sm:p-6">
      <div className="absolute inset-0 modal-backdrop" onClick={onClose} />
      <div className="relative z-10 flex max-h-[calc(100dvh-1.5rem)] w-full max-w-xl flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white text-slate-900 shadow-[0_18px_54px_rgba(15,23,42,0.16)] dark:border-slate-800 dark:bg-slate-950 dark:text-slate-100">
        <div className="flex shrink-0 items-center justify-between border-b border-slate-100 px-4 py-3 dark:border-slate-800 sm:px-6 sm:py-4">
          <div className="flex min-w-0 items-center gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-slate-900 text-white shadow-sm dark:bg-slate-100 dark:text-slate-900">
              <PackagePlus className="h-5 w-5" />
            </div>
            <div className="min-w-0">
              <h2 className="truncate text-base font-semibold">导入课程包</h2>
              <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">从 .atmx 包恢复课程、知识文档和学习记录</p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full text-slate-400 transition hover:bg-slate-100 hover:text-slate-700 dark:text-slate-500 dark:hover:bg-slate-800 dark:hover:text-slate-100"
            aria-label="关闭导入面板"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4 sm:px-6">
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
            className={cn(
              "flex min-h-[176px] w-full flex-col items-center justify-center rounded-2xl border border-dashed px-5 py-6 text-center transition",
              dragOver
                ? "border-slate-400 bg-slate-100 dark:border-slate-600 dark:bg-slate-900"
                : selectedFile
                  ? "border-slate-300 bg-slate-50 dark:border-slate-700 dark:bg-slate-900/70"
                  : "border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50 dark:border-slate-800 dark:bg-slate-950 dark:hover:border-slate-700 dark:hover:bg-slate-900/80",
            )}
          >
            <span className="flex h-12 w-12 items-center justify-center rounded-xl bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-300">
              {selectedFile ? <FileArchive className="h-6 w-6" /> : <Upload className="h-6 w-6" />}
            </span>
            {selectedFile ? (
              <>
                <span className="mt-4 max-w-full truncate text-sm font-semibold text-slate-900 dark:text-slate-100">{selectedFile.name}</span>
                <span className="mt-1 text-xs text-slate-500 dark:text-slate-400">{formatFileSize(selectedFile.size)}</span>
                <span className="mt-3 text-xs font-medium text-slate-500 underline underline-offset-4 dark:text-slate-400">重新选择文件</span>
              </>
            ) : (
              <>
                <span className="mt-4 text-sm font-semibold text-slate-800 dark:text-slate-100">选择或拖入课程包</span>
                <span className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">支持 AITeachMe 导出的 .atmx 文件，也兼容 .zip 包</span>
              </>
            )}
          </button>

          <label className="mt-4 block">
            <span className="text-xs font-medium text-slate-500 dark:text-slate-400">导入后的课程名称（可选）</span>
            <input
              type="text"
              value={customName}
              onChange={(event) => setCustomName(event.target.value)}
              placeholder="留空则沿用课程包内的原名"
              className="mt-1.5 h-11 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm text-slate-900 placeholder:text-slate-400 transition focus:border-slate-300 focus:outline-none focus:ring-2 focus:ring-slate-200 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:placeholder:text-slate-500 dark:focus:border-slate-600 dark:focus:ring-slate-800"
            />
          </label>

          {localError || importMutation.isError ? (
            <div className="mt-4 rounded-xl border border-red-100 bg-red-50 px-4 py-3 text-sm text-red-600 dark:border-red-900/60 dark:bg-red-950/30 dark:text-red-300">
              {localError ?? getApiErrorMessage(importMutation.error, "导入失败，请重试")}
            </div>
          ) : null}
        </div>

        <div className="flex shrink-0 flex-col gap-3 border-t border-slate-100 bg-slate-50/70 px-4 py-3 dark:border-slate-800 dark:bg-slate-900/70 sm:flex-row sm:items-center sm:justify-between sm:px-6">
          <div className="text-xs text-slate-500 dark:text-slate-400">
            导入成功后会出现在侧边栏和学习空间中
          </div>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={onClose}>
              取消
            </Button>
            <Button type="button" onClick={() => importMutation.mutate()} disabled={!selectedFile || importMutation.isPending}>
              {importMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <PackagePlus className="h-4 w-4" />}
              导入
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
