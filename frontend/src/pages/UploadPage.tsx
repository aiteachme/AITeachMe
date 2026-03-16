import { useRef, useCallback } from "react";
import { Upload as UploadIcon, FileText, Loader2, CheckCircle, XCircle, Clock } from "lucide-react";
import { useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/Card";
import { uploadFileApiV1UploadPost, listFilesApiV1FilesSubjectPost } from "../api/generated/upload";
import type { FileItem } from "../api/generated/model";

const STATUS_ICON: Record<string, React.ReactNode> = {
  parsed: <CheckCircle className="w-4 h-4 text-green-500" />,
  pending: <Clock className="w-4 h-4 text-yellow-500" />,
  parsing: <Loader2 className="w-4 h-4 text-blue-500 animate-spin" />,
  parse_failed: <XCircle className="w-4 h-4 text-red-500" />,
};

const STATUS_LABEL: Record<string, string> = {
  parsed: "已解析",
  pending: "等待中",
  parsing: "解析中",
  parse_failed: "解析失败",
};

export function UploadPage() {
  const { subjectId = "" } = useParams();
  const queryClient = useQueryClient();
  const inputRef = useRef<HTMLInputElement>(null);

  const { data, isLoading, isError } = useQuery({
    queryKey: ["files", subjectId],
    queryFn: () => listFilesApiV1FilesSubjectPost(subjectId, { limit: 50, offset: 0 }),
    enabled: !!subjectId,
  });

  const handleUpload = useCallback(async (file: File) => {
    await uploadFileApiV1UploadPost({ file, subject: subjectId });
    queryClient.invalidateQueries({ queryKey: ["files", subjectId] });
  }, [subjectId, queryClient]);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    const file = e.dataTransfer.files[0];
    if (file) handleUpload(file);
  }, [handleUpload]);

  const handleFileChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) handleUpload(file);
  }, [handleUpload]);

  const files: FileItem[] = data?.items ?? [];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-slate-900">上传资料</h1>
        <p className="text-slate-500 mt-2">上传课程资料、笔记和教材</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>上传文件</CardTitle>
          <CardDescription>支持 PDF、Word、图片等格式</CardDescription>
        </CardHeader>
        <CardContent>
          <div
            className="border-2 border-dashed border-slate-300 rounded-lg p-12 text-center hover:border-slate-400 transition-colors cursor-pointer"
            onDrop={handleDrop}
            onDragOver={(e) => e.preventDefault()}
            onClick={() => inputRef.current?.click()}
          >
            <UploadIcon className="w-12 h-12 mx-auto text-slate-400 mb-4" />
            <p className="text-sm text-slate-600 mb-2">点击或拖拽文件到此处上传</p>
            <p className="text-xs text-slate-400">支持 PDF, DOCX, PNG, JPG 格式</p>
            <input
              ref={inputRef}
              type="file"
              className="hidden"
              accept=".pdf,.docx,.doc,.png,.jpg,.jpeg"
              onChange={handleFileChange}
            />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>已上传文件</CardTitle>
          <CardDescription>管理您的学习资料</CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading && (
            <div className="flex items-center justify-center py-8 text-slate-400">
              <Loader2 className="w-5 h-5 animate-spin mr-2" />
              加载中...
            </div>
          )}
          {isError && (
            <p className="text-center py-8 text-red-500 text-sm">加载失败，请刷新重试</p>
          )}
          {!isLoading && !isError && files.length === 0 && (
            <p className="text-center py-8 text-slate-400 text-sm">暂无文件，请上传学习资料</p>
          )}
          <div className="space-y-3">
            {files.map((file) => (
              <div
                key={file.id}
                className="flex items-center justify-between p-4 border border-slate-200 rounded-lg hover:bg-slate-50 transition-colors"
              >
                <div className="flex items-center gap-3">
                  <FileText className="w-5 h-5 text-slate-400" />
                  <div>
                    <p className="text-sm font-medium text-slate-900">{file.filename}</p>
                    <p className="text-xs text-slate-500">
                      {new Date(file.created_at).toLocaleDateString("zh-CN")}
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  {STATUS_ICON[file.parse_status]}
                  <span className="text-xs text-slate-500">{STATUS_LABEL[file.parse_status]}</span>
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
