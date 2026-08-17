import { notFound } from "next/navigation";
import type { Metadata } from "next";
import { DocsBody, DocsDescription, DocsPage, DocsTitle } from "fumadocs-ui/page";
import { source } from "@/lib/source";
import { getMDXComponents } from "@/mdx-components";

const guideContexts = {
  "first-course": ["快速开始", "ingest"],
  "course-vs-chat": ["快速开始", "ingest"],
  "upload-materials": ["准备课程", "ingest"],
  "build-course": ["构建课程", "digest"],
  "import-demo-courses": ["准备课程", "ingest"],
  "knowledge-docs": ["学习课程", "digest"],
  "knowledge-graph": ["学习课程", "digest"],
  chat: ["学习课程", "interact"],
  "exam-modes": ["训练与复盘", "examine"],
  "review-profile": ["训练与复盘", "profile"],
  "settings-models": ["使用设置", "ingest"],
} as const;

export default async function Page(props: {
  params: Promise<{ slug?: string[] }>;
}) {
  const params = await props.params;
  const page = source.getPage(params.slug);

  if (!page) {
    notFound();
  }

  const MDX = page.data.body;
  const isDocsHome = !params.slug || params.slug.length === 0;
  const pageSlug = params.slug?.[params.slug.length - 1] ?? "";
  const [guideLabel, guideTrack] = guideContexts[pageSlug as keyof typeof guideContexts] ?? [
    "用户教程",
    "ingest",
  ];

  return (
    <DocsPage
      role="main"
      tabIndex={-1}
      toc={isDocsHome ? [] : page.data.toc}
      full={isDocsHome || page.data.full}
      footer={{ enabled: false }}
      tableOfContent={{ enabled: !isDocsHome }}
      tableOfContentPopover={{ enabled: !isDocsHome }}
      className={isDocsHome ? "atm-docs-home-page" : "atm-docs-guide-page"}
    >
      {isDocsHome ? null : (
        <header className={`atm-docs-guide-header atm-docs-track-${guideTrack}`}>
          <p className="atm-docs-guide-kicker">{guideLabel}</p>
          <DocsTitle>{page.data.title}</DocsTitle>
          <DocsDescription>{page.data.description}</DocsDescription>
        </header>
      )}
      <DocsBody className={isDocsHome ? "atm-docs-home-body" : "atm-docs-guide-body"}>
        <MDX components={getMDXComponents()} />
      </DocsBody>
    </DocsPage>
  );
}

export async function generateStaticParams() {
  return source.generateParams();
}

export async function generateMetadata(props: {
  params: Promise<{ slug?: string[] }>;
}): Promise<Metadata> {
  const params = await props.params;
  const page = source.getPage(params.slug);

  if (!page) {
    notFound();
  }

  return {
    title: page.data.title,
    description: page.data.description,
  };
}
