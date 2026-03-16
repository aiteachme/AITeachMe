import { FileQuestion, Clock } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/Card";
import { Button } from "../components/ui/Button";

export function ExamPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-slate-900">考题预测</h1>
        <p className="text-slate-500 mt-2">基于学习内容生成的模拟试题</p>
      </div>

      <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
        {[
          { title: "函数与极限", questions: 20, time: 45, difficulty: "中等" },
          { title: "导数应用", questions: 15, time: 30, difficulty: "困难" },
          { title: "积分计算", questions: 25, time: 60, difficulty: "简单" },
        ].map((exam, i) => (
          <Card key={i}>
            <CardHeader>
              <FileQuestion className="w-8 h-8 text-slate-400 mb-2" />
              <CardTitle className="text-lg">{exam.title}</CardTitle>
              <CardDescription>
                {exam.questions} 道题 · {exam.difficulty}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex items-center text-sm text-slate-600">
                <Clock className="w-4 h-4 mr-2" />
                预计用时 {exam.time} 分钟
              </div>
              <Button className="w-full">开始练习</Button>
            </CardContent>
          </Card>
        ))}
      </div>

      <Card>
        <CardHeader>
          <CardTitle>历史记录</CardTitle>
          <CardDescription>查看您的练习历史</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            {[
              { title: "函数与极限", score: 85, date: "2 天前" },
              { title: "导数应用", score: 92, date: "5 天前" },
              { title: "积分计算", score: 78, date: "1 周前" },
            ].map((record, i) => (
              <div
                key={i}
                className="flex items-center justify-between p-4 border border-slate-200 rounded-lg"
              >
                <div>
                  <p className="text-sm font-medium text-slate-900">{record.title}</p>
                  <p className="text-xs text-slate-500">{record.date}</p>
                </div>
                <div className="text-right">
                  <p className="text-lg font-bold text-slate-900">{record.score}</p>
                  <p className="text-xs text-slate-500">分</p>
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
