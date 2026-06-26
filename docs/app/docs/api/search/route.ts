import { createFromSource } from "fumadocs-core/search/server";
import { source } from "@/lib/source";

const searchApi = createFromSource(source);

export const dynamic = "force-static";

export const GET = searchApi.staticGET;
