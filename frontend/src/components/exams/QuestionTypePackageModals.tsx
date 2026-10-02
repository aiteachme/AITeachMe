import { useCallback, useMemo, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  Download,
  FileArchive,
  Loader2,
  PackageCheck,
  ShieldCheck,
  Upload,
} from "lucide-react";

import {
  confirmQuestionTypeImportApiApiV1CoursesCourseIdQuestionTypesImportsImportIdConfirmPost,
  getDownloadQuestionTypeExampleApiApiV1CoursesCourseIdQuestionTypesExamplesExampleIdGetUrl,
  listQuestionTypeExamplesApiApiV1CoursesCourseIdQuestionTypesExamplesGet,
  previewQuestionTypeImportApiApiV1CoursesCourseIdQuestionTypesImportsPost,
} from "../../api/generated/question-type-packages";
import type {
  QuestionTypeExampleResponse,
  QuestionTypePackageInstallData,
  QuestionTypePackagePreviewData,
} from "../../api/generated/model";
import { downloadApiFile, getApiErrorMessage } from "../../api/client";
import { unwrapOrvalResponse } from "../../lib/unwrapOrvalResponse";
import { Button } from "../ui/Button";
import { useFileDropZone } from "../ui/FileDropZone";
import { Modal } from "../ui/Modal";
import { useToast } from "../ui/Toast";


const MAX_PACKAGE_BYTES = 8 * 1024 * 1024;
const MODE_LABELS: Record<string, string> = {
  question_bank: "题库",
  mastery_drill: "闯关",
  web_practice: "测验",
  paper_exam: "考卷",
  pdf: "PDF",
};

export function formatQuestionTypeModeLabel(mode: string): string {
  return MODE_LABELS[mode] ?? mode;
}

type QuestionTypeImportModalProps = {
  courseId: string;
  open: boolean;
  onClose: () => void;
  onInstalled: (result: QuestionTypePackageInstallData) => void | Promise<void>;
};

function conflictLabel(preview: QuestionTypePackagePreviewData): string | null {
  if (preview.conflict === "already_installed") return "相同版本已经安装，再次确认不会重复创建。";
  if (preview.conflict === "version_conflict") return "相同版本存在不同内容，请提升版本号后重新上传。";
  if (preview.conflict === "new_version") return "检测到已安装的旧版本，本次将新增不可变版本。";
  return null;
}

export function QuestionTypeImportModal({
  courseId,
  open,
  onClose,
  onInstalled,
}: QuestionTypeImportModalProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const { toast } = useToast();
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<QuestionTypePackagePreviewData | null>(null);
  const [clientError, setClientError] = useState("");

  const previewMutation = useMutation({
    mutationFn: async (selectedFile: File) => {
      const response = await previewQuestionTypeImportApiApiV1CoursesCourseIdQuestionTypesImportsPost(
        courseId,
        { file: selectedFile },
      );
      const data = unwrapOrvalResponse<QuestionTypePackagePreviewData>(response);
      if (!data) throw new Error("题型包校验结果为空。");
      return data;
    },
    onSuccess: (data) => {
      setPreview(data);
      setClientError("");
    },
    onError: (error) => {
      setClientError(getApiErrorMessage(error, "题型包上传失败"));
    },
  });

  const installMutation = useMutation({
    mutationFn: async (importId: string) => {
      const response =
        await confirmQuestionTypeImportApiApiV1CoursesCourseIdQuestionTypesImportsImportIdConfirmPost(
          courseId,
          importId,
          { set_current: true },
        );
      const data = unwrapOrvalResponse<QuestionTypePackageInstallData>(response);
      if (!data) throw new Error("题型包安装结果为空。");
      return data;
    },
    onSuccess: async (data) => {
      await onInstalled(data);
      toast({
        title: data.already_installed ? "题型已存在" : "题型已导入",
        description: data.status === "archived"
          ? "该题型仍为归档状态，可在题型详情中恢复并启用。"
          : !data.runtime_ready
            ? "已加入当前课程目录，当前版本暂不支持出题。"
            : data.status !== "active"
              ? "该题型当前已停用，可在题型详情中启用后出题。"
              : "题型已启用，可在支持的训练模式中选择出题和自动判分。",
        variant: "success",
      });
      setFile(null);
      setPreview(null);
      setClientError("");
      if (inputRef.current) inputRef.current.value = "";
      onClose();
    },
    onError: (error) => {
      setClientError(getApiErrorMessage(error, "题型包安装失败"));
    },
  });

  const resetSelection = useCallback(() => {
    setFile(null);
    setPreview(null);
    setClientError("");
    previewMutation.reset();
    installMutation.reset();
    if (inputRef.current) inputRef.current.value = "";
  }, [installMutation, previewMutation]);

  const handleClose = useCallback(() => {
    if (previewMutation.isPending || installMutation.isPending) return;
    resetSelection();
    onClose();
  }, [installMutation.isPending, onClose, previewMutation.isPending, resetSelection]);

  const handleFileChange = useCallback((selected: File | null) => {
    setPreview(null);
    setClientError("");
    if (!selected) {
      setFile(null);
      return;
    }
    const suffix = selected.name.toLowerCase();
    if (!suffix.endsWith(".atqskill") && !suffix.endsWith(".zip")) {
      setFile(null);
      setClientError("请选择 .atqskill 文件，或内容合同相同的 .zip 文件。");
      if (inputRef.current) inputRef.current.value = "";
      return;
    }
    if (selected.size > MAX_PACKAGE_BYTES) {
      setFile(null);
      setClientError("题型包不能超过 8 MB。");
      if (inputRef.current) inputRef.current.value = "";
      return;
    }
    setFile(selected);
  }, []);

  const handleDroppedFiles = useCallback((files: File[]) => {
    if (inputRef.current) inputRef.current.value = "";
    if (files.length !== 1) {
      setFile(null);
      setPreview(null);
      setClientError("每次只能导入一个题型包。");
      return;
    }
    handleFileChange(files[0] ?? null);
  }, [handleFileChange]);
  const isImportPending = previewMutation.isPending || installMutation.isPending;
  const { isDragActive, dropZoneHandlers } = useFileDropZone<HTMLButtonElement>({
    disabled: isImportPending,
    onDropFiles: handleDroppedFiles,
  });

  const issueItems = preview?.valid ? preview.warnings : preview?.errors;
  const packageConflict = preview ? conflictLabel(preview) : null;
  const canInstall = Boolean(
    preview?.valid && preview.import_id && preview.conflict !== "version_conflict",
  );

  return (
    <Modal
      open={open}
      onClose={handleClose}
      title="导入自定义题型"
      className="max-w-2xl rounded-[22px]"
      bodyClassName="sm:p-5"
    >
      <div className="space-y-4">
        {!preview ? (
          <>
            <button
              type="button"
              onClick={() => {
                if (!isImportPending) inputRef.current?.click();
              }}
              aria-disabled={isImportPending}
              {...dropZoneHandlers}
              className={`flex w-full flex-col items-center rounded-2xl border border-dashed px-6 py-9 text-center outline-none transition focus-visible:ring-2 focus-visible:ring-indigo-300 ${
                isDragActive
                  ? "border-indigo-400 bg-indigo-50/70 ring-4 ring-indigo-100 dark:border-indigo-400 dark:bg-indigo-500/10 dark:ring-indigo-500/10"
                  : "border-slate-300 bg-slate-50/70 hover:border-indigo-300 hover:bg-indigo-50/40 dark:border-slate-700 dark:bg-slate-900/60 dark:hover:border-indigo-500/50 dark:hover:bg-indigo-500/5"
              } ${isImportPending ? "cursor-not-allowed opacity-60" : "cursor-pointer"}`}
            >
              <span className="grid h-11 w-11 place-items-center rounded-xl bg-white text-indigo-600 shadow-sm ring-1 ring-slate-200 dark:bg-slate-950 dark:text-indigo-300 dark:ring-slate-700">
                <FileArchive className="h-5 w-5" />
              </span>
              <span className="mt-3 text-sm font-semibold text-slate-900 dark:text-slate-100">
                {isDragActive ? "松手添加题型包" : file?.name ?? "拖入或选择 .atqskill 题型包"}
              </span>
              <span className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">
                支持兼容 ZIP，最大 8 MB；校验过程不会执行包内代码。
              </span>
            </button>
            <input
              ref={inputRef}
              type="file"
              accept=".atqskill,.zip,application/zip"
              className="hidden"
              onChange={(event) => handleFileChange(event.target.files?.[0] ?? null)}
            />

            {clientError ? (
              <p className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-200">
                {clientError}
              </p>
            ) : null}

            <div className="flex items-center justify-end gap-2">
              <Button type="button" variant="ghost" onClick={handleClose}>取消</Button>
              <Button
                type="button"
                disabled={!file || previewMutation.isPending}
                onClick={() => file && previewMutation.mutate(file)}
              >
                {previewMutation.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <ShieldCheck className="h-4 w-4" />
                )}
                {previewMutation.isPending ? "正在校验" : "校验题型包"}
              </Button>
            </div>
          </>
        ) : (
          <>
            <section className="rounded-2xl border border-slate-200 bg-slate-50/60 p-4 dark:border-slate-800 dark:bg-slate-900/60">
              <div className="flex items-start gap-3">
                <span className={`mt-0.5 grid h-9 w-9 shrink-0 place-items-center rounded-xl ${
                  preview.valid
                    ? "bg-emerald-50 text-emerald-600 dark:bg-emerald-500/10 dark:text-emerald-300"
                    : "bg-red-50 text-red-600 dark:bg-red-500/10 dark:text-red-300"
                }`}>
                  {preview.valid ? <CheckCircle2 className="h-4 w-4" /> : <AlertTriangle className="h-4 w-4" />}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="text-base font-semibold text-slate-950 dark:text-slate-100">
                      {preview.name || "题型包校验失败"}
                    </h3>
                    {preview.version ? (
                      <span className="rounded-md bg-white px-2 py-0.5 text-xs font-medium text-slate-500 ring-1 ring-slate-200 dark:bg-slate-950 dark:text-slate-400 dark:ring-slate-700">
                        v{preview.version}
                      </span>
                    ) : null}
                  </div>
                  <p className="mt-1 text-sm leading-6 text-slate-600 dark:text-slate-300">
                    {preview.description || "请按错误位置修正文件后重新上传。"}
                  </p>
                </div>
              </div>
            </section>

            {preview.valid ? (
              <div className="grid gap-3 sm:grid-cols-2">
                <section className="rounded-xl border border-slate-200 px-4 py-3 dark:border-slate-800">
                  <p className="text-xs font-semibold text-slate-400">作答结构</p>
                  <p className="mt-1 text-sm text-slate-700 dark:text-slate-300">
                    {(preview.answer_fields ?? []).map((item) => item.label).join("、") || "未配置"}
                  </p>
                </section>
                <section className="rounded-xl border border-slate-200 px-4 py-3 dark:border-slate-800">
                  <p className="text-xs font-semibold text-slate-400">评分维度</p>
                  <p className="mt-1 text-sm text-slate-700 dark:text-slate-300">
                    {(preview.rubric ?? []).map((item) => item.label).join("、") || "未配置"}
                  </p>
                </section>
                <section className="rounded-xl border border-slate-200 px-4 py-3 dark:border-slate-800 sm:col-span-2">
                  <p className="text-xs font-semibold text-slate-400">支持场景</p>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {(preview.modes ?? []).map((mode) => (
                      <span key={mode} className="rounded-md bg-slate-100 px-2 py-1 text-xs text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                        {formatQuestionTypeModeLabel(mode)}
                      </span>
                    ))}
                  </div>
                </section>
              </div>
            ) : null}

            {packageConflict ? (
              <p className={`rounded-xl border px-4 py-3 text-sm ${
                preview.conflict === "version_conflict"
                  ? "border-red-200 bg-red-50 text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-200"
                  : "border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200"
              }`}>
                {packageConflict}
              </p>
            ) : null}

            {issueItems && issueItems.length > 0 ? (
              <section className="rounded-xl border border-slate-200 px-4 py-3 dark:border-slate-800">
                <p className="text-xs font-semibold text-slate-400">
                  {preview.valid ? "校验提醒" : "需要修正"}
                </p>
                <ul className="mt-2 space-y-2 text-sm text-slate-600 dark:text-slate-300">
                  {issueItems.map((issue, index) => (
                    <li key={`${issue.code}-${issue.path}-${index}`}>
                      <span className="font-medium text-slate-800 dark:text-slate-100">{issue.path}</span>
                      ：{issue.message}
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}

            {preview.valid ? (
              <p className="rounded-xl bg-indigo-50 px-4 py-3 text-sm leading-6 text-indigo-700 dark:bg-indigo-500/10 dark:text-indigo-200">
                {preview.runtime_message}
              </p>
            ) : null}
            {clientError ? (
              <p className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-200">
                {clientError}
              </p>
            ) : null}

            <div className="flex flex-wrap items-center justify-between gap-2">
              <Button type="button" variant="outline" onClick={resetSelection} disabled={installMutation.isPending}>
                重新选择
              </Button>
              <div className="flex items-center gap-2">
                <Button type="button" variant="outline" onClick={handleClose} disabled={installMutation.isPending}>
                  取消
                </Button>
                <Button
                  type="button"
                  disabled={!canInstall || installMutation.isPending}
                  onClick={() => preview.import_id && installMutation.mutate(preview.import_id)}
                >
                  {installMutation.isPending ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <PackageCheck className="h-4 w-4" />
                  )}
                  {installMutation.isPending ? "正在导入" : "导入到本课程"}
                </Button>
              </div>
            </div>
          </>
        )}
      </div>
    </Modal>
  );
}


type QuestionTypeExamplesModalProps = {
  courseId: string;
  open: boolean;
  onClose: () => void;
};

export function QuestionTypeExamplesModal({
  courseId,
  open,
  onClose,
}: QuestionTypeExamplesModalProps) {
  const { toast } = useToast();
  const [downloadingKey, setDownloadingKey] = useState<string | null>(null);
  const examplesQuery = useQuery({
    queryKey: ["question-type-package-examples", courseId],
    enabled: open,
    queryFn: async () => {
      const response = await listQuestionTypeExamplesApiApiV1CoursesCourseIdQuestionTypesExamplesGet(
        courseId,
      );
      return unwrapOrvalResponse<QuestionTypeExampleResponse[]>(response) ?? [];
    },
    staleTime: 10 * 60 * 1000,
  });
  const examples = useMemo(() => examplesQuery.data ?? [], [examplesQuery.data]);

  const handleDownload = useCallback(async (item: QuestionTypeExampleResponse) => {
    setDownloadingKey(item.example_id);
    try {
      await downloadApiFile(
        getDownloadQuestionTypeExampleApiApiV1CoursesCourseIdQuestionTypesExamplesExampleIdGetUrl(
          courseId,
          item.example_id,
        ),
        item.filename,
      );
    } catch (error) {
      toast({
        title: "示例下载失败",
        description: getApiErrorMessage(error, "请稍后重试"),
        variant: "error",
      });
    } finally {
      setDownloadingKey(null);
    }
  }, [courseId, toast]);

  return (
    <Modal open={open} onClose={onClose} title="下载题型示例" className="max-w-lg rounded-[22px]">
      <p className="text-sm leading-6 text-slate-500 dark:text-slate-400">
        下载后可修改提示词、作答字段和评分维度，再作为新的自定义题型导入。
      </p>
      {examplesQuery.isLoading ? (
        <div className="flex items-center justify-center gap-2 py-10 text-sm text-slate-500">
          <Loader2 className="h-4 w-4 animate-spin" />正在加载示例...
        </div>
      ) : examplesQuery.error ? (
        <p className="mt-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {getApiErrorMessage(examplesQuery.error, "示例列表加载失败")}
        </p>
      ) : (
        <div className="mt-4 grid gap-2">
          {examples.map((item) => (
            <button
              key={item.example_id}
              type="button"
              onClick={() => void handleDownload(item)}
              disabled={downloadingKey !== null}
              className="flex items-center justify-between gap-4 rounded-xl border border-slate-200 px-4 py-3 text-left outline-none transition hover:border-indigo-200 hover:bg-indigo-50/40 focus-visible:ring-2 focus-visible:ring-indigo-300 disabled:opacity-60 dark:border-slate-800 dark:hover:border-indigo-500/40 dark:hover:bg-indigo-500/5"
            >
              <span className="min-w-0">
                <span className="block text-sm font-semibold text-slate-800 dark:text-slate-100">{item.name}</span>
                <span className="mt-0.5 block truncate text-xs text-slate-400">{item.filename}</span>
              </span>
              {downloadingKey === item.example_id ? (
                <Loader2 className="h-4 w-4 shrink-0 animate-spin text-indigo-500" />
              ) : (
                <Download className="h-4 w-4 shrink-0 text-indigo-500" />
              )}
            </button>
          ))}
        </div>
      )}
      <div className="mt-5 flex justify-end">
        <Button type="button" variant="outline" onClick={onClose}>关闭</Button>
      </div>
    </Modal>
  );
}


export function QuestionTypePackageHeaderActions({
  onOpenExamples,
  onOpenImport,
}: {
  onOpenExamples: () => void;
  onOpenImport: () => void;
}) {
  return (
    <div
      role="group"
      aria-label="自定义题型导入"
      className="relative flex min-w-0 flex-col gap-2 rounded-xl border-2 border-indigo-200/70 bg-gradient-to-r from-slate-50 via-white to-indigo-50 p-2 dark:border-indigo-500/25 dark:from-slate-900 dark:via-slate-900 dark:to-indigo-950/40 sm:w-fit sm:flex-row sm:items-center sm:gap-3"
    >
      <span className="shrink-0 whitespace-nowrap px-2 py-1 text-sm font-bold text-slate-500 dark:text-slate-400 sm:py-0 sm:pl-3 sm:pr-0">
        自定义题型
      </span>
      <span aria-hidden="true" className="hidden h-6 w-0.5 shrink-0 rounded-full bg-indigo-200 dark:bg-indigo-400/40 sm:block" />
      <div className="grid grid-cols-2 gap-2 sm:flex sm:items-center">
        <Button type="button" variant="outline" onClick={onOpenExamples} className="rounded-lg focus-visible:ring-indigo-400">
          <Download aria-hidden="true" className="h-4 w-4" />
          下载示例
        </Button>
        <Button type="button" variant="outline" onClick={onOpenImport} className="rounded-lg border-indigo-200 bg-transparent text-indigo-700 hover:border-indigo-400 hover:bg-transparent focus-visible:ring-indigo-400 dark:border-indigo-500/30 dark:bg-transparent dark:text-indigo-300 dark:hover:border-indigo-400/50 dark:hover:bg-transparent">
          <Upload aria-hidden="true" className="h-4 w-4" />
          导入题型
        </Button>
      </div>
    </div>
  );
}
