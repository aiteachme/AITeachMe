import { useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, FileArchive, Loader2, PackagePlus, UploadCloud } from "lucide-react";

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
      eyebrow="Import"
      title="导入课程包"
      description="把本地课程包恢复为一门新课程，保留知识文档、题库记录和学习画像等可迁移内容。"
      icon={PackagePlus}
      tone="emerald"
      onClose={onClose}
      sidebar={
        <div className="grid gap-3 text-sm sm:grid-cols-3">
          {[
            { label: "文件格式", value: ".atmx / .zip" },
            { label: "导入方式", value: "创建新课程" },
            { label: "完成后", value: "刷新课程列表" },
          ].map((item) => (
            <div key={item.label} className="flex items-start gap-2.5 text-slate-600 dark:text-slate-400">
              <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600 dark:text-emerald-300" />
              <span className="min-w-0">
                <span className="block text-xs text-slate-500 dark:text-slate-400">{item.label}</span>
                <span className="block font-medium leading-5 text-slate-900 dark:text-slate-100">{item.value}</span>
              </span>
            </div>
          ))}
        </div>
      }
      footer={
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="text-xs leading-5 text-slate-500 dark:text-slate-400">
            {selectedFile ? `已选择 ${formatFileSize(selectedFile.size)} 的课程包` : "选择课程包后即可开始导入"}
          </div>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={onClose} className="rounded-lg text-slate-500 hover:text-slate-900">
              取消
            </Button>
            <Button
              type="button"
              onClick={() => importMutation.mutate()}
              disabled={!selectedFile || importMutation.isPending}
              className="rounded-lg bg-slate-950 px-4 text-white shadow-none hover:bg-slate-800 hover:shadow-none dark:bg-slate-100 dark:text-slate-950 dark:hover:bg-white"
            >
              {importMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <PackagePlus className="h-4 w-4" />}
              导入课程
            </Button>
          </div>
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

      <div className="space-y-6">
        <section>
          <div className="flex flex-col gap-2 border-b border-slate-100 pb-4 dark:border-slate-800 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <h3 className="text-base font-semibold text-slate-950 dark:text-slate-50">课程包文件</h3>
              <p className="mt-1 text-sm leading-6 text-slate-500 dark:text-slate-400">
                拖入或选择由 AITeachMe 导出的课程包，系统会在导入前校验格式。
              </p>
            </div>
            <span className="w-fit rounded-md border border-slate-200 px-2.5 py-1 text-xs font-medium text-slate-500 dark:border-slate-800 dark:text-slate-400">
              .atmx / .zip
            </span>
          </div>

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
              "mt-5 flex w-full items-center gap-4 rounded-lg border border-dashed px-4 py-5 text-left transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-300 dark:focus-visible:ring-slate-700 sm:px-5",
              dragOver
                ? "border-emerald-300 bg-emerald-50 dark:border-emerald-500/40 dark:bg-emerald-950/20"
                : selectedFile
                  ? "border-slate-300 bg-slate-50 dark:border-slate-700 dark:bg-slate-900/55"
                  : "border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50/80 dark:border-slate-800 dark:bg-slate-950 dark:hover:border-slate-700 dark:hover:bg-slate-900/45",
            )}
          >
            <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-500 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
              {selectedFile ? <FileArchive className="h-5 w-5" /> : <UploadCloud className="h-5 w-5" />}
            </span>
            <span className="min-w-0 flex-1">
              {selectedFile ? (
                <>
                  <span className="block truncate text-sm font-semibold text-slate-950 dark:text-slate-50">{selectedFile.name}</span>
                  <span className="mt-1 block text-xs leading-5 text-slate-500 dark:text-slate-400">
                    {formatFileSize(selectedFile.size)}，点击可重新选择文件
                  </span>
                </>
              ) : (
                <>
                  <span className="block text-sm font-semibold text-slate-950 dark:text-slate-50">选择或拖入课程包</span>
                  <span className="mt-1 block text-xs leading-5 text-slate-500 dark:text-slate-400">
                    文件不会上传到第三方服务，仅用于恢复课程数据。
                  </span>
                </>
              )}
            </span>
          </button>
        </section>

        <section className="border-t border-slate-100 pt-5 dark:border-slate-800">
          <label className="block">
            <span className="text-sm font-medium text-slate-800 dark:text-slate-200">课程名称</span>
            <span className="mt-1 block text-xs leading-5 text-slate-500 dark:text-slate-400">
              可选。留空时会沿用课程包内保存的名称。
            </span>
            <input
              type="text"
              value={customName}
              onChange={(event) => setCustomName(event.target.value)}
              placeholder="例如：初中数学复习全图谱"
              className="mt-3 h-11 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-900 placeholder:text-slate-400 transition focus:border-slate-400 focus:outline-none focus:ring-2 focus:ring-slate-200 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:placeholder:text-slate-500 dark:focus:border-slate-500 dark:focus:ring-slate-800"
            />
          </label>
        </section>

        {localError || importMutation.isError ? (
          <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm leading-6 text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
            {localError ?? getApiErrorMessage(importMutation.error, "导入失败，请重试")}
          </div>
        ) : null}
      </div>
    </CourseOperationModal>
  );
}
