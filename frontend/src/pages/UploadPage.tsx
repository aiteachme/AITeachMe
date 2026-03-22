import { useRef, useCallback, useState } from "react";
import { Upload as UploadIcon, FileText, Loader2, CheckCircle, XCircle, Clock, RefreshCw, Eye } from "lucide-react";
import { useParams } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/Card";
import { Button } from "../components/ui/Button";
import { Modal } from "../components/ui/Modal";
import { MarkdownViewer } from "../components/ui/MarkdownViewer";
import {
  deleteFilesApiApiV1SubjectsSubjectFilesDeletePost,
  getFileApiApiV1SubjectsSubjectFilesGetPost,
  listFilesApiApiV1SubjectsSubjectFilesListPost,
  parseUploadedFilesApiV1SubjectsSubjectFilesParsePost,
  uploadFilesApiV1SubjectsSubjectFilesUploadPost,
} from "../api/generated/files";
import type { FileGetData, FileItem } from "../api/generated/model";
import { unwrapOrvalResponse } from "../api/generated/utils";

async function fetchFiles(subject: string): Promise<FileItem[]> {
  return unwrapOrvalResponse(
    await listFilesApiApiV1SubjectsSubjectFilesListPost(subject, {
      page: 1,
      size: 50,
    }),
  )?.items ?? [];
}

async function uploadFiles(subject: string, files: File[]): Promise<void> {
  await uploadFilesApiV1SubjectsSubjectFilesUploadPost(subject, {
    files,
  });
}

async function parseFiles(subject: string, fileIds: number[]): Promise<void> {
  await parseUploadedFilesApiV1SubjectsSubjectFilesParsePost(subject, {
    file_ids: fileIds,
  });
}

async function deleteFile(subject: string, fileId: number): Promise<void> {
  await deleteFilesApiApiV1SubjectsSubjectFilesDeletePost(subject, {
    file_id: fileId,
  });
}

async function fetchFileResult(subject: string, fileId: number): Promise<FileGetData> {
  const result = unwrapOrvalResponse(
    await getFileApiApiV1SubjectsSubjectFilesGetPost(subject, {
      file_id: fileId,
    }),
  );

  if (!result) {
    throw new Error("加载文件结果失败");
  }

  return result;
}

const STATUS_ICON: Record<string, React.ReactNode> = {
  done: <CheckCircle className="w-4 h-4 text-green-500" />,
  completed: <CheckCircle className="w-4 h-4 text-green-500" />,
  pending: <Clock className="w-4 h-4 text-yellow-500" />,
  running: <Loader2 className="w-4 h-4 text-blue-500 animate-spin" />,
  processing: <Loader2 className="w-4 h-4 text-blue-500 animate-spin" />,
  failed: <XCircle className="w-4 h-4 text-red-500" />,
};

const STATUS_LABEL: Record<string, string> = {
  done: "已解析",
  completed: "已解析",
  pending: "等待中",
  running: "解析中",
  processing: "解析中",
  failed: "解析失败",
};

const ACTIVE_FILE_STATUSES = new Set(["pending", "running", "processing"]);
const DONE_FILE_STATUSES = new Set(["done", "completed"]);

export function UploadPage() {
  const { subjectId = "" } = useParams();
  const queryClient = useQueryClient();
  const inputRef = useRef<HTMLInputElement>(null);
  const [previewFile, setPreviewFile] = useState<FileGetData | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);

  const { data: files = [], isLoading, isError } = useQuery({
    queryKey: ["files", subjectId],
    queryFn: () => fetchFiles(subjectId),
    enabled: !!subjectId,
    refetchInterval: (query) => {
      const items = query.state.data ?? [];
      return items.some((file) => ACTIVE_FILE_STATUSES.has(file.status)) ? 3000 : false;
    },
  });

  const uploadMutation = useMutation({
    mutationFn: (selectedFiles: File[]) => uploadFiles(subjectId, selectedFiles),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["files", subjectId] }),
  });

  const parseMutation = useMutation({
    mutationFn: (fileIds: number[]) => parseFiles(subjectId, fileIds),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["files", subjectId] }),
  });

  const deleteMutation = useMutation({
    mutationFn: (fileId: number) => deleteFile(subjectId, fileId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["files", subjectId] }),
  });

  const handleUpload = useCallback(async (selectedFiles: File[]) => {
    if (!selectedFiles.length) return;
    await uploadMutation.mutateAsync(selectedFiles);
    // 上传后自动触发解析（需要先拿到新文件 id，这里刷新列表后手动触发）
  }, [uploadMutation]);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    const dropped = Array.from(e.dataTransfer.files);
    if (dropped.length) handleUpload(dropped);
  }, [handleUpload]);

  const handleFileChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const selected = Array.from(e.target.files ?? []);
    if (selected.length) handleUpload(selected);
    e.target.value = "";
  }, [handleUpload]);

  const pendingFiles = files.filter((f) => f.status === "pending");

  const handlePreview = useCallback(async (fileId: number) => {
    setPreviewLoading(true);
    try {
      const data = await fetchFileResult(subjectId, fileId);
      setPreviewFile(data);
    } catch {
      // 静默处理，用户可重试
    } finally {
      setPreviewLoading(false);
    }
  }, [subjectId]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-slate-900">上传资料</h1>
        <p className="text-slate-500 mt-2">上传课程资料、笔记和教材</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>上传文件</CardTitle>
          <CardDescription>支持 PDF、Word、图片等格式，可多选</CardDescription>
        </CardHeader>
        <CardContent>
          <div
            className="border-2 border-dashed border-slate-300 rounded-lg p-12 text-center hover:border-slate-400 transition-colors cursor-pointer"
            onDrop={handleDrop}
            onDragOver={(e) => e.preventDefault()}
            onClick={() => inputRef.current?.click()}
          >
            {uploadMutation.isPending
              ? <Loader2 className="w-12 h-12 mx-auto text-slate-400 mb-4 animate-spin" />
              : <UploadIcon className="w-12 h-12 mx-auto text-slate-400 mb-4" />}
            <p className="text-sm text-slate-600 mb-2">
              {uploadMutation.isPending ? "上传中..." : "点击或拖拽文件到此处上传"}
            </p>
            <p className="text-xs text-slate-400">支持 PDF, DOCX, Markdown, TXT, PNG, JPG 格式</p>
            <input
              ref={inputRef}
              type="file"
              className="hidden"
              accept=".pdf,.docx,.doc,.md,.markdown,.txt,.png,.jpg,.jpeg"
              multiple
              onChange={handleFileChange}
            />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle>已上传文件</CardTitle>
              <CardDescription>管理您的学习资料</CardDescription>
            </div>
            {pendingFiles.length > 0 && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => parseMutation.mutate(pendingFiles.map((f) => f.id))}
                disabled={parseMutation.isPending}
              >
                {parseMutation.isPending
                  ? <><Loader2 className="w-3 h-3 animate-spin mr-1" />解析中</>
                  : <><RefreshCw className="w-3 h-3 mr-1" />解析 {pendingFiles.length} 个文件</>}
              </Button>
            )}
          </div>
        </CardHeader>
        <CardContent>
          {isLoading && (
            <div className="flex items-center justify-center py-8 text-slate-400">
              <Loader2 className="w-5 h-5 animate-spin mr-2" />加载中...
            </div>
          )}
          {isError && <p className="text-center py-8 text-red-500 text-sm">加载失败，请刷新重试</p>}
          {!isLoading && !isError && files.length === 0 && (
            <p className="text-center py-8 text-slate-400 text-sm">暂无文件，请上传学习资料</p>
          )}
          <div className="space-y-3">
            {files.map((file) => {
              const isDone = DONE_FILE_STATUSES.has(file.status) || file.markdown_ready;
              return (
                <div
                  key={file.id}
                  className={`flex items-center justify-between p-4 border border-slate-200 rounded-lg transition-colors ${
                    isDone ? "hover:bg-blue-50 cursor-pointer" : "hover:bg-slate-50"
                  }`}
                  onClick={() => isDone && handlePreview(file.id)}
                >
                  <div className="flex items-center gap-3">
                    <FileText className="w-5 h-5 text-slate-400" />
                    <div>
                      <p className="text-sm font-medium text-slate-900">
                        {file.filename}
                        {isDone && (
                          <Eye className="w-3.5 h-3.5 text-slate-400 inline ml-2" />
                        )}
                      </p>
                      <p className="text-xs text-slate-500">
                        {new Date(file.created_at).toLocaleDateString("zh-CN")}
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    <div className="flex items-center gap-1.5">
                      {STATUS_ICON[file.status] ?? <Clock className="w-4 h-4 text-slate-400" />}
                      <span className="text-xs text-slate-500">{STATUS_LABEL[file.status] ?? file.status}</span>
                    </div>
                    <button
                      onClick={(e) => { e.stopPropagation(); deleteMutation.mutate(file.id); }}
                      disabled={deleteMutation.isPending}
                      className="text-slate-300 hover:text-red-400 transition-colors text-xs"
                    >
                      删除
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        </CardContent>
      </Card>

      {previewLoading && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/20">
          <div className="bg-white rounded-xl p-6 shadow-xl flex items-center gap-3">
            <Loader2 className="w-5 h-5 animate-spin text-slate-500" />
            <span className="text-sm text-slate-600">加载解析结果...</span>
          </div>
        </div>
      )}

      <Modal
        open={!!previewFile}
        onClose={() => setPreviewFile(null)}
        title={previewFile?.filename ?? "解析结果"}
      >
        <article className="prose prose-slate prose-sm max-w-none">
          <MarkdownViewer content={previewFile?.markdown_content ?? ""} />
        </article>
      </Modal>
    </div>
  );
}
