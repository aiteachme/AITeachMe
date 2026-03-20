import { BookOpen, Loader2, MessageSquare, TrendingUp } from "lucide-react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/Card";
import { Button } from "../components/ui/Button";
import { apiClient } from "../api/client";

interface SubjectItem {
  id: number;
  subject_id: string;
  name: string;
}

interface ApiResponse<T> {
  code: number;
  data: T;
}

interface PaginatedData<T> {
  items: T[];
  total: number;
}

async function fetchSubjects(): Promise<SubjectItem[]> {
  const res = await apiClient<ApiResponse<PaginatedData<SubjectItem>>>({
    method: "POST",
    url: "/api/v1/subjects/list",
    data: { page: 1, size: 100 },
  });
  return res.data.items;
}

export function HomePage() {
  const { data: subjects = [], isLoading } = useQuery({
    queryKey: ["subjects"],
    queryFn: fetchSubjects,
  });

  const firstSubject = subjects[0]?.subject_id ?? "";

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-4xl font-bold text-slate-900">欢迎使用 AI TEACH ME</h1>
        <p className="text-lg text-slate-500 mt-3">智能学习助手，让学习更高效</p>
      </div>

      <div className="grid gap-6 md:grid-cols-3">
        <Card className="hover:shadow-lg transition-shadow">
          <CardHeader>
            <BookOpen className="w-10 h-10 text-slate-700 mb-3" />
            <CardTitle>知识总结</CardTitle>
            <CardDescription>AI 自动生成知识点总结</CardDescription>
          </CardHeader>
          <CardContent>
            <Link to={firstSubject ? `/subject/${firstSubject}/summary` : "#"}>
              <Button variant="outline" className="w-full" disabled={!firstSubject}>
                开始学习
              </Button>
            </Link>
          </CardContent>
        </Card>

        <Card className="hover:shadow-lg transition-shadow">
          <CardHeader>
            <MessageSquare className="w-10 h-10 text-slate-700 mb-3" />
            <CardTitle>AI 对话</CardTitle>
            <CardDescription>随时提问，即时解答</CardDescription>
          </CardHeader>
          <CardContent>
            <Link to={firstSubject ? `/subject/${firstSubject}/chat` : "#"}>
              <Button variant="outline" className="w-full" disabled={!firstSubject}>
                开始对话
              </Button>
            </Link>
          </CardContent>
        </Card>

        <Card className="hover:shadow-lg transition-shadow">
          <CardHeader>
            <TrendingUp className="w-10 h-10 text-slate-700 mb-3" />
            <CardTitle>学习分析</CardTitle>
            <CardDescription>追踪学习进度和表现</CardDescription>
          </CardHeader>
          <CardContent>
            <Link to={firstSubject ? `/subject/${firstSubject}/analysis` : "#"}>
              <Button variant="outline" className="w-full" disabled={!firstSubject}>
                查看分析
              </Button>
            </Link>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>我的学科</CardTitle>
          <CardDescription>选择一个学科开始学习</CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading && (
            <div className="flex items-center justify-center py-8 text-slate-400">
              <Loader2 className="w-5 h-5 animate-spin mr-2" />
              加载中...
            </div>
          )}
          {!isLoading && subjects.length === 0 && (
            <p className="text-center py-8 text-slate-400 text-sm">
              还没有学科，在左侧点击「新建学科」开始吧
            </p>
          )}
          <div className="space-y-3">
            {subjects.map((subject) => (
              <div
                key={subject.subject_id}
                className="flex items-center justify-between p-4 border border-slate-200 rounded-lg hover:bg-slate-50 transition-colors"
              >
                <div>
                  <p className="text-sm font-medium text-slate-900">{subject.name}</p>
                  <p className="text-xs text-slate-400 mt-0.5">{subject.subject_id}</p>
                </div>
                <div className="flex gap-2">
                  <Link to={`/subject/${subject.subject_id}/chat`}>
                    <Button variant="ghost" size="sm">对话</Button>
                  </Link>
                  <Link to={`/subject/${subject.subject_id}/upload`}>
                    <Button variant="outline" size="sm">上传资料</Button>
                  </Link>
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
