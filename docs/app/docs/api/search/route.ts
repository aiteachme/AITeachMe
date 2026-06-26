import { createFromSource } from "fumadocs-core/search/server";
import { source } from "@/lib/source";

type SearchResult = {
  id: string;
  type: "page" | "heading" | "text";
  content: string;
  url: string;
  breadcrumbs?: string[];
};

type StructuredData = {
  headings?: Array<{ id?: string; content?: string }>;
  contents?: Array<{ heading?: string; content?: string }>;
};

type SourcePage = ReturnType<typeof source.getPages>[number];

const searchApi = createFromSource(source);
const cjkPattern = /[\u3400-\u9fff]/u;

export async function GET(request: Request) {
  const response = await searchApi.GET(request);
  const results = (await response.json()) as SearchResult[];
  const query = new URL(request.url).searchParams.get("query")?.trim() ?? "";

  if (results.length > 0 || !cjkPattern.test(query)) {
    return Response.json(results);
  }

  return Response.json(await fallbackChineseSearch(query));
}

async function fallbackChineseSearch(query: string): Promise<SearchResult[]> {
  const normalizedQuery = normalizeSearchText(query);
  if (!normalizedQuery) {
    return [];
  }

  const results: SearchResult[] = [];
  for (const page of source.getPages()) {
    const pageData = page.data as SourcePage["data"] & {
      load?: () => Promise<{ structuredData?: StructuredData }>;
      structuredData?: StructuredData | (() => Promise<StructuredData> | StructuredData);
    };
    const title = String(pageData.title ?? "").trim();
    const description = String(pageData.description ?? "").trim();

    if (matchesChineseQuery(title, normalizedQuery)) {
      results.push({
        id: page.url,
        type: "page",
        content: highlightQuery(title, query),
        breadcrumbs: ["AITeachMe"],
        url: page.url,
      });
    }

    if (description && matchesChineseQuery(description, normalizedQuery)) {
      results.push({
        id: `${page.url}-description`,
        type: "text",
        content: highlightQuery(description, query),
        url: page.url,
      });
    }

    const structuredData = await resolveStructuredData(pageData);
    for (const heading of structuredData?.headings ?? []) {
      const content = String(heading.content ?? "").trim();
      if (!content || !matchesChineseQuery(content, normalizedQuery)) {
        continue;
      }
      results.push({
        id: `${page.url}-heading-${results.length}`,
        type: "heading",
        content: highlightQuery(content, query),
        url: heading.id ? `${page.url}#${heading.id}` : page.url,
      });
    }

    for (const item of structuredData?.contents ?? []) {
      const content = String(item.content ?? "").replace(/\s+/g, " ").trim();
      if (!content || !matchesChineseQuery(content, normalizedQuery)) {
        continue;
      }
      results.push({
        id: `${page.url}-text-${results.length}`,
        type: "text",
        content: highlightQuery(truncateSearchContent(content), query),
        url: item.heading ? `${page.url}#${item.heading}` : page.url,
      });
    }

    if (results.length >= 12) {
      break;
    }
  }

  return results.slice(0, 12);
}

async function resolveStructuredData(
  pageData: {
    load?: () => Promise<{ structuredData?: StructuredData }>;
    structuredData?: StructuredData | (() => Promise<StructuredData> | StructuredData);
  },
): Promise<StructuredData | undefined> {
  if (typeof pageData.structuredData === "function") {
    return pageData.structuredData();
  }
  if (pageData.structuredData) {
    return pageData.structuredData;
  }
  return (await pageData.load?.())?.structuredData;
}

function matchesChineseQuery(value: string, normalizedQuery: string): boolean {
  return normalizeSearchText(value).includes(normalizedQuery);
}

function normalizeSearchText(value: string): string {
  return value.replace(/\s+/g, "").toLocaleLowerCase("zh-CN");
}

function truncateSearchContent(value: string): string {
  return value.length <= 120 ? value : `${value.slice(0, 118)}...`;
}

function highlightQuery(value: string, query: string): string {
  const trimmedQuery = query.trim();
  if (!trimmedQuery) {
    return value;
  }
  return value.replaceAll(trimmedQuery, `<mark>${trimmedQuery}</mark>`);
}
