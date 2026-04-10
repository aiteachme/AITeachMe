import type { FileRecord } from "../types/files";

export interface GraphDebugBuildIntent {
  kind: "graph-debug-build";
  requestKey: string;
  source: "files-page";
  fileUids: string[];
  fileNames: string[];
}

export interface GraphDebugBuildLocationState {
  graphDebugBuild?: GraphDebugBuildIntent;
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

export function createGraphDebugBuildLocationState(
  files: Array<Pick<FileRecord, "uid" | "filename">>,
): GraphDebugBuildLocationState {
  const normalizedFiles = files
    .map((file) => ({
      uid: String(file.uid || "").trim(),
      filename: String(file.filename || "").trim(),
    }))
    .filter((file) => file.uid.length > 0);

  return {
    graphDebugBuild: {
      kind: "graph-debug-build",
      requestKey: `graph-debug-${Date.now()}-${normalizedFiles.length}`,
      source: "files-page",
      fileUids: normalizedFiles.map((file) => file.uid),
      fileNames: normalizedFiles.map((file) => file.filename),
    },
  };
}

export function readGraphDebugBuildIntent(value: unknown): GraphDebugBuildIntent | null {
  if (typeof value !== "object" || value === null) {
    return null;
  }

  const record = value as Record<string, unknown>;
  const payload = record.graphDebugBuild;
  if (typeof payload !== "object" || payload === null) {
    return null;
  }

  const candidate = payload as Record<string, unknown>;
  if (
    candidate.kind !== "graph-debug-build" ||
    candidate.source !== "files-page" ||
    typeof candidate.requestKey !== "string" ||
    !isStringArray(candidate.fileUids) ||
    !isStringArray(candidate.fileNames)
  ) {
    return null;
  }

  return {
    kind: "graph-debug-build",
    requestKey: candidate.requestKey,
    source: "files-page",
    fileUids: candidate.fileUids.map((item) => item.trim()).filter(Boolean),
    fileNames: candidate.fileNames.map((item) => item.trim()).filter(Boolean),
  };
}
