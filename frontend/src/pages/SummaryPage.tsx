import { BookOpen, ChevronRight } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/Card";

export function SummaryPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-slate-900">知识总结</h1>
        <p className="text-slate-500 mt-2">AI 生成的知识点总结和思维导图</p>
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        {[
          { title: "第一章：函数与极限", topics: 8, progress: 100 },
          { title: "第二章：导数与微分", topics: 12, progress: 75 },
          { title: "第三章：积分", topics: 10, progress: 40 },
          { title: "第四章：微分方程", topics: 6, progress: 0 },
        ].map((chapter, i) => (
          <Card key={i} className="hover:shadow-md transition-shadow cursor-pointer">
            <CardHeader>
              <div className="flex items-start justify-between">
                <BookOpen className="w-8 h-8 text-slate-400" />
                <span className="text-xs font-medium text-slate-500">
                  {chapter.progress}% 完成
                </span>
              </div>
              <CardTitle className="text-lg mt-4">{chapter.title}</CardTitle>
              <CardDescription>{chapter.topics} 个知识点</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="w-full bg-slate-100 rounded-full h-2">
                <div
                  className="bg-slate-900 h-2 rounded-full transition-all"
                  style={{ width: `${chapter.progress}%` }}
                />
              </div>
              <div className="flex items-center justify-between mt-4">
                <span className="text-sm text-slate-600">查看详情</span>
                <ChevronRight className="w-4 h-4 text-slate-400" />
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
