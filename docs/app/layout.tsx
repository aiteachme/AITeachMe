import type { Metadata } from "next";
import { RootProvider } from "fumadocs-ui/provider/next";
import "fumadocs-ui/style.css";
import "./global.css";

export const metadata: Metadata = {
  title: {
    default: "AITeachMe Docs",
    template: "%s | AITeachMe Docs",
  },
  description: "AITeachMe 用户教程和开发者文档。",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <body>
        <RootProvider>{children}</RootProvider>
      </body>
    </html>
  );
}
