import { BookOpen, MessageSquare, TrendingUp } from "lucide-react";
import { Link } from "react-router-dom";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/Card";
import { Button } from "../components/ui/Button";

export function HomePage() {
  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-4xl font-bold text-slate-900">欢迎使用 AI TEACHE ME</h1>
        <p className="text-lg text-slate-500 mt-3">
          智能学习助手，让学习更高效
        </p>
      </div>

      <div className="grid gap-6 md:grid-cols-3">
        <Card className="hover:shadow-lg transition-shadow">
          <CardHeader>
            <BookOpen className="w-10 h-10 text-slate-700 mb-3" />
            <CardTitle>知识总结</CardTitle>
            <CardDescription>AI 自动生成知识点总结</CardDescription>
          </CardHeader>
          <CardContent>
            <Link to="/subject/1/summary">
              <Button variant="outline" className="w-full">
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
            <Link to="/subject/1/chat">
              <Button variant="outline" className="w-full">
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
            <Link to="/subject/1/analysis">
              <Button variant="outline" className="w-full">
                查看分析
              </Button>
            </Link>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>最近学习</CardTitle>
          <CardDescription>继续您的学习进度</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            {[
              { subject: "高数", module: "导数与微分", progress: 75, time: "2 小时前" },
              { subject: "高数", module: "积分", progress: 40, time: "昨天" },
              { subject: "高数", module: "函数与极限", progress: 100, time: "3 天前" },
            ].map((item, i) => (
              <div
                key={i}
                className="flex items-center justify-between p-4 border border-slate-200 rounded-lg hover:bg-slate-50 transition-colors cursor-pointer"
              >
                <div className="flex-1">
                  <p className="text-sm font-medium text-slate-900">
                    {item.subject} - {item.module}
                  </p>
                  <p className="text-xs text-slate-500 mt-1">{item.time}</p>
                </div>
                <div className="flex items-center gap-4">
                  <div className="text-right">
                    <p className="text-sm font-medium text-slate-700">{item.progress}%</p>
                    <div className="w-24 bg-slate-100 rounded-full h-1.5 mt-1">
                      <div
                        className="bg-slate-900 h-1.5 rounded-full"
                        style={{ width: `${item.progress}%` }}
                      />
                    </div>
                  </div>
                  <Button variant="ghost" size="sm">
                    继续
                  </Button>
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
