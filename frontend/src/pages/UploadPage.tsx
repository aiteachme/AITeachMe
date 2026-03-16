import { Upload as UploadIcon, FileText } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/Card";
import { Button } from "../components/ui/Button";

export function UploadPage() {
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
          <div className="border-2 border-dashed border-slate-300 rounded-lg p-12 text-center hover:border-slate-400 transition-colors cursor-pointer">
            <UploadIcon className="w-12 h-12 mx-auto text-slate-400 mb-4" />
            <p className="text-sm text-slate-600 mb-2">点击或拖拽文件到此处上传</p>
            <p className="text-xs text-slate-400">支持 PDF, DOCX, PNG, JPG 格式</p>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>已上传文件</CardTitle>
          <CardDescription>管理您的学习资料</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            {[1, 2, 3].map((i) => (
              <div
                key={i}
                className="flex items-center justify-between p-4 border border-slate-200 rounded-lg hover:bg-slate-50 transition-colors"
              >
                <div className="flex items-center gap-3">
                  <FileText className="w-5 h-5 text-slate-400" />
                  <div>
                    <p className="text-sm font-medium text-slate-900">
                      第{i}章 - 课程笔记.pdf
                    </p>
                    <p className="text-xs text-slate-500">2.3 MB · 2 天前</p>
                  </div>
                </div>
                <Button variant="ghost" size="sm">
                  查看
                </Button>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
