import type { Metadata } from "next";
import type { ReactNode } from "react";
import { RootProvider } from "fumadocs-ui/provider/next";
import "fumadocs-ui/style.css";
import "./global.css";

export const metadata: Metadata = {
  title: {
    default: "AITeachMe Docs",
    template: "%s | AITeachMe Docs",
  },
  description: "AITeachMe 用户教程：从资料准备到课程画像，按真实使用顺序完成学习闭环。",
};

const zhCnTranslations = {
  "On this page": "本页目录",
  "On this page(table of contents)": "本页目录",
  "No Headings": "暂无目录",
  "No Headings(table of contents)": "暂无目录",
  "Table of Contents": "目录",
  "Table of Contents(inline table of contents)": "目录",
  Search: "搜索",
  "Search(search trigger)": "搜索",
  "Search(search dialog)": "搜索",
  "Open Search": "打开搜索",
  "Open Search(search trigger)(aria-label)": "打开搜索",
  "Close Search": "关闭搜索",
  "Close Search(search dialog)(aria-label)": "关闭搜索",
  "Open Sidebar": "切换目录",
  "Open Sidebar(sidebar)(aria-label)": "切换目录",
  "Collapse Sidebar": "收起目录",
  "Collapse Sidebar(sidebar)(aria-label)": "收起目录",
  "Copy Anchor Link": "复制标题链接",
  "Copy Anchor Link(heading anchor)(aria-label)": "复制标题链接",
} as const;

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <body suppressHydrationWarning>
        <a className="atm-docs-skip-link" href="#nd-page">
          跳到正文
        </a>
        <RootProvider
          i18n={{ locale: "zh-CN", translations: zhCnTranslations }}
          search={{
            options: {
              api: "/docs/api/search",
              type: "static",
            },
          }}
        >
          {children}
        </RootProvider>
      </body>
    </html>
  );
}
