import Link from "next/link";

export default function NotFound() {
  return (
    <main className="mx-auto flex min-h-[52vh] max-w-2xl flex-col justify-center px-6 py-16">
      <p className="mb-3 text-sm font-medium text-fd-muted-foreground">404</p>
      <h1 className="text-3xl font-semibold tracking-tight text-fd-foreground">
        没有找到这篇文档
      </h1>
      <p className="mt-4 text-base leading-7 text-fd-muted-foreground">
        这个页面可能已经移动或删除。可以回到文档首页，从快速开始、用户教程或开发者文档继续查找。
      </p>
      <div className="mt-8">
        <Link
          href="/docs"
          className="inline-flex h-10 items-center rounded-lg bg-fd-primary px-4 text-sm font-medium text-fd-primary-foreground transition hover:opacity-90"
        >
          回到文档首页
        </Link>
      </div>
    </main>
  );
}
