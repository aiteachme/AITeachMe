import {
  type ChangeEvent,
  type DragEvent,
  useCallback,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  AlertCircle,
  ArrowRight,
  CheckCircle2,
  Eye,
  FileText,
  Loader2,
  RefreshCw,
  Sparkles,
  Trash2,
  Upload,
} from "lucide-react";
import { useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { getApiErrorMessage } from "../api/client";
import { apiClient } from "../api/client";
import {
  deleteFilesApiApiV1SubjectsSubjectFilesDeletePost,
  getFileApiApiV1SubjectsSubjectFilesGetPost,
  listFilesApiApiV1SubjectsSubjectFilesListPost,
  retryUploadedFileApiV1SubjectsSubjectFilesRetryPost,
  uploadFilesApiV1SubjectsSubjectFilesUploadPost,
} from "../api/generated/files";
import type { FileGetData, FileItem, FilesUploadData } from "../api/generated/model";
import { unwrapOrvalResponse } from "../lib/unwrapOrvalResponse";
import { Button } from "../components/ui/Button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../components/ui/Card";
import { MarkdownViewer } from "../components/ui/MarkdownViewer";
import { Modal } from "../components/ui/Modal";

interface ApiResponse<T> {
  code: number;
  data: T;
}

interface DocGenBuildData {
  accepted_file_ids: number[];
  prompt: string | null;
  ready_file_count: number;
  requested_at: string;
}

async function fetchFiles(subject: string): Promise<FileItem[]> {
  const response = await listFilesApiApiV1SubjectsSubjectFilesListPost(subject, {
    page: 1,
    size: 100,
  });
  return unwrapOrvalResponse<{ items?: FileItem[] }>(response)?.items ?? [];
}

async function fetchFileResult(subject: string, fileId: number): Promise<FileGetData> {
  const response = await getFileApiApiV1SubjectsSubjectFilesGetPost(subject, {
    file_id: fileId,
  });
  const data = unwrapOrvalResponse<FileGetData>(response);
  if (!data) {
    throw new Error("加载文件解析结果失败");
  }
  return data;
}

async function uploadFiles(subject: string, files: File[]): Promise<FilesUploadData> {
  const response = await uploadFilesApiV1SubjectsSubjectFilesUploadPost(subject, {
    files,
  });
  const data = unwrapOrvalResponse<FilesUploadData>(response);
  if (!data) {
    throw new Error("上传文件失败");
  }
  return data;
}

async function retryFile(subject: string, fileId: number): Promise<void> {
  await retryUploadedFileApiV1SubjectsSubjectFilesRetryPost(subject, {
    file_id: fileId,
  });
}

async function deleteFile(subject: string, fileId: number): Promise<void> {
  await deleteFilesApiApiV1SubjectsSubjectFilesDeletePost(subject, {
    file_id: fileId,
  });
}

async function triggerDocGenBuild(
  subject: string,
  prompt?: string,
): Promise<DocGenBuildData> {
  const res = await apiClient<ApiResponse<DocGenBuildData>>({
    method: "POST",
    url: `/api/v1/subjects/${subject}/knowledge/build`,
    data: {
      prompt,
    },
  });
  return res.data;
}

const ACTIVE_FILE_STATUSES = new Set(["pending", "processing", "running"]);
const ACCEPT_TEXT = ".pdf,.docx,.doc,.md,.markdown,.txt,.png,.jpg,.jpeg";
const SUPPORTED_FORMATS = "PDF / DOCX / Markdown / TXT / PNG / JPG";

function formatFileSize(bytes: number | null | undefined): string {
  if (!bytes || bytes <= 0) {
    return "未知大小";
  }
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatTimestamp(value: string): string {
  return new Date(value).toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function getFileStatusMeta(file: FileItem): {
  label: string;
  description: string;
  tone: string;
  icon: JSX.Element;
} {
  if (file.markdown_ready) {
    return {
      label: "已就绪",
      description: file.parser_used ? `已生成 Markdown，解析器：${file.parser_used}` : "已生成 Markdown，可开始生成知识文档",
      tone: "border-emerald-200 bg-emerald-50 text-emerald-700",
      icon: <CheckCircle2 className="h-4 w-4 text-emerald-500" />,
    };
  }

  if (file.status === "failed") {
    return {
      label: "解析失败",
      description: file.error_message ?? "解析未完成，可直接重试",
      tone: "border-red-200 bg-red-50 text-red-700",
      icon: <AlertCircle className="h-4 w-4 text-red-500" />,
    };
  }

  if (ACTIVE_FILE_STATUSES.has(file.status) || file.ingest_status !== "pending") {
    return {
      label: "解析中",
      description: "上传成功后已自动进入 ingest 解析流程",
      tone: "border-blue-200 bg-blue-50 text-blue-700",
      icon: <Loader2 className="h-4 w-4 animate-spin text-blue-500" />,
    };
  }

  return {
    label: "等待处理",
    description: "已入队，正在等待后台处理",
    tone: "border-amber-200 bg-amber-50 text-amber-700",
    icon: <RefreshCw className="h-4 w-4 text-amber-500" />,
  };
}

export function UploadPage() {
  const { subjectId = "" } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [docPrompt, setDocPrompt] = useState("");
  const [previewFile, setPreviewFile] = useState<FileGetData | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [lastUpload, setLastUpload] = useState<FilesUploadData | null>(null);

  const {
    data: files = [],
    isLoading,
    isError,
    error,
  } = useQuery({
    queryKey: ["files", subjectId],
    queryFn: () => fetchFiles(subjectId),
    enabled: !!subjectId,
    refetchInterval: (query) => {
      const items = query.state.data ?? [];
      return items.some((item) => !item.markdown_ready && item.status !== "failed") ? 2500 : false;
    },
  });

  const readyFiles = useMemo(
    () => files.filter((file) => file.markdown_ready),
    [files],
  );
  const activeFiles = useMemo(
    () => files.filter((file) => !file.markdown_ready && file.status !== "failed"),
    [files],
  );

  const uploadMutation = useMutation({
    mutationFn: (selectedFiles: File[]) => uploadFiles(subjectId, selectedFiles),
    onSuccess: (data) => {
      setLastUpload(data);
      void queryClient.invalidateQueries({ queryKey: ["files", subjectId] });
    },
  });

  const retryMutation = useMutation({
    mutationFn: (fileId: number) => retryFile(subjectId, fileId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["files", subjectId] });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (fileId: number) => deleteFile(subjectId, fileId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["files", subjectId] });
    },
  });

  const buildMutation = useMutation({
    mutationFn: () =>
      triggerDocGenBuild(
        subjectId,
        docPrompt.trim() || undefined,
      ),
    onSuccess: (data) => {
      navigate(
        `/subject/${subjectId}/doc?requested_at=${encodeURIComponent(data.requested_at)}`,
      );
    },
  });

  const handleUpload = useCallback(
    async (selectedFiles: File[]) => {
      if (!selectedFiles.length) {
        return;
      }
      await uploadMutation.mutateAsync(selectedFiles);
    },
    [uploadMutation],
  );

  const handleFileInputChange = useCallback(
    async (event: ChangeEvent<HTMLInputElement>) => {
      const selectedFiles = Array.from(event.target.files ?? []);
      event.target.value = "";
      await handleUpload(selectedFiles);
    },
    [handleUpload],
  );

  const handleDrop = useCallback(
    async (event: DragEvent<HTMLDivElement>) => {
      event.preventDefault();
      const droppedFiles = Array.from(event.dataTransfer.files ?? []);
      await handleUpload(droppedFiles);
    },
    [handleUpload],
  );

  const handlePreview = useCallback(
    async (fileId: number) => {
      setPreviewLoading(true);
      try {
        const data = await fetchFileResult(subjectId, fileId);
        setPreviewFile(data);
      } finally {
        setPreviewLoading(false);
      }
    },
    [subjectId],
  );

  return (
    <div className="space-y-6">
      <section className="relative overflow-hidden rounded-[28px] border border-slate-200 bg-[radial-gradient(circle_at_top_left,_rgba(14,165,233,0.14),_transparent_35%),radial-gradient(circle_at_bottom_right,_rgba(251,191,36,0.18),_transparent_30%),linear-gradient(135deg,#ffffff_0%,#f8fafc_55%,#eef6ff_100%)] p-6 shadow-sm md:p-8">
        <div className="grid gap-6 lg:grid-cols-[1.2fr_0.9fr]">
          <div className="space-y-5">
            <div className="space-y-3">
              <div className="inline-flex items-center gap-2 rounded-full border border-sky-200 bg-white/80 px-3 py-1 text-xs font-medium text-sky-700 backdrop-blur">
                <Sparkles className="h-3.5 w-3.5" />
                上传即解析，开始对话即生成知识文档
              </div>
              <div className="space-y-2">
                <h1 className="text-3xl font-semibold tracking-tight text-slate-900 md:text-4xl">
                  先放资料，再直接进入你的知识文档
                </h1>
                <p className="max-w-2xl text-sm leading-6 text-slate-600 md:text-base">
                  这里先收集资料和你的生成要求。文件上传后会自动进入解析，至少有一个文件就绪后，就可以直接开始生成知识文档并跳转到文档页。
                </p>
              </div>
            </div>

            <div className="rounded-3xl border border-slate-200 bg-white/90 p-4 shadow-sm backdrop-blur">
              <label
                htmlFor="doc-prompt"
                className="mb-3 block text-sm font-medium text-slate-700"
              >
                知识文档生成要求
              </label>
              <textarea
                id="doc-prompt"
                value={docPrompt}
                onChange={(event) => setDocPrompt(event.target.value)}
                placeholder="比如：请整理成适合期末复习的知识文档，按章节归纳重点、常见误区和典型题型。"
                className="min-h-[180px] w-full resize-none rounded-2xl border border-slate-200 bg-slate-50/80 px-4 py-3 text-sm leading-6 text-slate-700 outline-none transition focus:border-sky-300 focus:bg-white focus:ring-2 focus:ring-sky-100"
              />
              <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div className="text-sm text-slate-500">
                  {readyFiles.length > 0
                    ? `当前已有 ${readyFiles.length} 个文件可直接用于生成知识文档`
                    : "至少等 1 个文件解析完成后，才会启用开始对话"}
                </div>
                <Button
                  size="lg"
                  onClick={() => buildMutation.mutate()}
                  disabled={readyFiles.length === 0 || buildMutation.isPending}
                  className="rounded-2xl bg-slate-900 px-6 text-white hover:bg-slate-800"
                >
                  {buildMutation.isPending ? (
                    <>
                      <Loader2 className="h-4 w-4 animate-spin" />
                      正在生成知识文档
                    </>
                  ) : (
                    <>
                      开始对话
                      <ArrowRight className="h-4 w-4" />
                    </>
                  )}
                </Button>
              </div>
              {buildMutation.isError && (
                <p className="mt-3 text-sm text-red-500">
                  {getApiErrorMessage(buildMutation.error, "知识文档构建失败，请稍后重试")}
                </p>
              )}
            </div>
          </div>

          <div className="rounded-[26px] border border-slate-200 bg-slate-950 p-5 text-white shadow-xl">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-slate-100">上传资料</p>
                <p className="mt-1 text-xs text-slate-400">{SUPPORTED_FORMATS}</p>
              </div>
              {uploadMutation.isPending && (
                <Loader2 className="h-5 w-5 animate-spin text-sky-300" />
              )}
            </div>

            <div
              className="mt-5 cursor-pointer rounded-[24px] border border-dashed border-slate-700 bg-white/5 p-6 transition hover:border-sky-400 hover:bg-white/10"
              onClick={() => fileInputRef.current?.click()}
              onDrop={(event) => void handleDrop(event)}
              onDragOver={(event) => event.preventDefault()}
            >
              <div className="flex flex-col items-center gap-4 text-center">
                <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-sky-400/15 text-sky-300">
                  <Upload className="h-7 w-7" />
                </div>
                <div className="space-y-2">
                  <p className="text-base font-medium text-white">
                    {uploadMutation.isPending ? "文件上传中..." : "拖拽文件到这里，或点击选择文件"}
                  </p>
                  <p className="text-sm leading-6 text-slate-400">
                    文件上传成功后会立即自动触发 ingest 解析，不需要再手动点一次解析按钮。
                  </p>
                </div>
                <Button
                  type="button"
                  variant="outline"
                  className="rounded-2xl border-slate-600 bg-transparent text-white hover:bg-white/10"
                >
                  选择文件
                </Button>
                <input
                  ref={fileInputRef}
                  type="file"
                  multiple
                  accept={ACCEPT_TEXT}
                  className="hidden"
                  onChange={(event) => void handleFileInputChange(event)}
                />
              </div>
            </div>

            <div className="mt-5 grid gap-3 sm:grid-cols-3">
              <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
                <p className="text-xs uppercase tracking-[0.2em] text-slate-400">总文件</p>
                <p className="mt-2 text-2xl font-semibold text-white">{files.length}</p>
              </div>
              <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
                <p className="text-xs uppercase tracking-[0.2em] text-slate-400">已就绪</p>
                <p className="mt-2 text-2xl font-semibold text-emerald-300">{readyFiles.length}</p>
              </div>
              <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
                <p className="text-xs uppercase tracking-[0.2em] text-slate-400">处理中</p>
                <p className="mt-2 text-2xl font-semibold text-sky-300">{activeFiles.length}</p>
              </div>
            </div>

            {lastUpload && (
              <div className="mt-4 rounded-2xl border border-emerald-400/20 bg-emerald-400/10 px-4 py-3 text-sm text-emerald-100">
                最近上传了 {lastUpload.filenames.length} 个文件，已自动受理 {lastUpload.started_parse_count} 个解析任务。
              </div>
            )}

            {uploadMutation.isError && (
              <div className="mt-4 rounded-2xl border border-red-400/20 bg-red-400/10 px-4 py-3 text-sm text-red-200">
                {getApiErrorMessage(uploadMutation.error, "上传失败，请稍后重试")}
              </div>
            )}
          </div>
        </div>
      </section>

      <Card className="rounded-[24px]">
        <CardHeader className="pb-4">
          <CardTitle className="text-xl text-slate-900">文件队列</CardTitle>
          <CardDescription>
            这里直接展示当前 subject 的文件状态，是否完成以本地 Markdown 产物是否存在为准。
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {isLoading && (
            <div className="flex items-center justify-center gap-2 rounded-2xl border border-dashed border-slate-200 px-4 py-10 text-sm text-slate-500">
              <Loader2 className="h-4 w-4 animate-spin" />
              正在加载文件列表...
            </div>
          )}

          {isError && (
            <div className="rounded-2xl border border-red-200 bg-red-50 px-4 py-6 text-sm text-red-600">
              {getApiErrorMessage(error, "文件列表加载失败")}
            </div>
          )}

          {!isLoading && !isError && files.length === 0 && (
            <div className="rounded-2xl border border-dashed border-slate-200 bg-slate-50 px-4 py-10 text-center text-sm text-slate-500">
              还没有上传资料，先把文档拖进来，我们就从这里开始。
            </div>
          )}

          {!isLoading && !isError && files.map((file) => {
            const meta = getFileStatusMeta(file);
            const showPreview = file.markdown_ready;

            return (
              <div
                key={file.id}
                className="flex flex-col gap-4 rounded-[22px] border border-slate-200 bg-white p-4 transition hover:border-slate-300 md:flex-row md:items-start md:justify-between"
              >
                <div className="min-w-0 flex-1 space-y-3">
                  <div className="flex items-start gap-3">
                    <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-slate-100 text-slate-600">
                      <FileText className="h-5 w-5" />
                    </div>
                    <div className="min-w-0 space-y-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="truncate text-sm font-medium text-slate-900 md:text-base">
                          {file.filename}
                        </p>
                        <span className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs font-medium ${meta.tone}`}>
                          {meta.icon}
                          {meta.label}
                        </span>
                      </div>
                      <p className="text-sm leading-6 text-slate-500">
                        {meta.description}
                      </p>
                    </div>
                  </div>

                  <div className="flex flex-wrap gap-2 text-xs text-slate-500">
                    <span className="rounded-full bg-slate-100 px-2.5 py-1">
                      类型：{file.filetype.toUpperCase()}
                    </span>
                    <span className="rounded-full bg-slate-100 px-2.5 py-1">
                      大小：{formatFileSize(file.file_size_bytes)}
                    </span>
                    <span className="rounded-full bg-slate-100 px-2.5 py-1">
                      更新时间：{formatTimestamp(file.latest_updated_at)}
                    </span>
                    {file.detected_language && (
                      <span className="rounded-full bg-slate-100 px-2.5 py-1">
                        语言：{file.detected_language}
                      </span>
                    )}
                    {file.estimated_pages != null && (
                      <span className="rounded-full bg-slate-100 px-2.5 py-1">
                        预估页数：{file.estimated_pages}
                      </span>
                    )}
                  </div>
                </div>

                <div className="flex flex-wrap items-center gap-2 md:justify-end">
                  {showPreview && (
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => void handlePreview(file.id)}
                    >
                      <Eye className="h-4 w-4" />
                      预览
                    </Button>
                  )}

                  {file.status === "failed" && (
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => retryMutation.mutate(file.id)}
                      disabled={retryMutation.isPending}
                    >
                      {retryMutation.isPending ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <RefreshCw className="h-4 w-4" />
                      )}
                      重试
                    </Button>
                  )}

                  <Button
                    variant="ghost"
                    size="sm"
                    className="text-slate-500 hover:bg-red-50 hover:text-red-600"
                    onClick={() => deleteMutation.mutate(file.id)}
                    disabled={deleteMutation.isPending}
                  >
                    <Trash2 className="h-4 w-4" />
                    删除
                  </Button>
                </div>
              </div>
            );
          })}
        </CardContent>
      </Card>

      {previewLoading && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/20">
          <div className="flex items-center gap-3 rounded-2xl bg-white px-5 py-4 shadow-xl">
            <Loader2 className="h-5 w-5 animate-spin text-slate-500" />
            <span className="text-sm text-slate-600">正在加载解析结果...</span>
          </div>
        </div>
      )}

      <Modal
        open={previewFile !== null}
        onClose={() => setPreviewFile(null)}
        title={previewFile?.filename ?? "文件预览"}
        className="max-w-4xl"
      >
        <div className="space-y-4">
          {previewFile && (
            <div className="flex flex-wrap gap-2 text-xs text-slate-500">
              <span className="rounded-full bg-slate-100 px-2.5 py-1">
                类型：{previewFile.filetype.toUpperCase()}
              </span>
              <span className="rounded-full bg-slate-100 px-2.5 py-1">
                状态：{previewFile.markdown_ready ? "可预览" : previewFile.status}
              </span>
              {previewFile.parser_used && (
                <span className="rounded-full bg-slate-100 px-2.5 py-1">
                  解析器：{previewFile.parser_used}
                </span>
              )}
            </div>
          )}

          {previewFile?.markdown_content ? (
            <article className="prose prose-slate max-w-none">
              <MarkdownViewer content={previewFile.markdown_content} />
            </article>
          ) : (
            <div className="rounded-2xl border border-dashed border-slate-200 bg-slate-50 px-4 py-10 text-center text-sm text-slate-500">
              当前还没有可预览的 Markdown 内容。
            </div>
          )}
        </div>
      </Modal>
    </div>
  );
}
