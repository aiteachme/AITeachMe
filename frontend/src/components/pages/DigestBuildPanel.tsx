import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle, FileText, Loader2, Play, XCircle, Zap } from "lucide-react";

import { apiClient, getApiErrorMessage } from "../../api/client";
import { Button } from "../ui/Button";
import { Card, CardContent } from "../ui/Card";
import { Modal } from "../ui/Modal";
import type { FileRecord, FilesData } from "../../types/files";

interface ApiResponse<T> {
  code: number;
  data: T;
}

interface DigestGraphJob {
  status: string;
  progress: number;
  current_step: string | null;
  nodes_added: number;
  nodes_updated: number;
  nodes_merged: number;
  edges_added: number;
  edges_updated: number;
  error_message: string | null;
}

interface DigestCurriculumJob {
  status: string;
  progress: number;
  current_step: string | null;
  units_added: number;
  units_updated: number;
  error_message: string | null;
}

interface DigestStatusData {
  graph_job: DigestGraphJob;
  curriculum_job: DigestCurriculumJob | null;
}

interface DigestBuildData {
  job_id: number;
}

const STEP_LABELS: Record<string, string> = {
  acquire_lock: "Acquire lock",
  prepare: "Prepare data",
  extract: "Extract knowledge",
  cluster: "Cluster candidates",
  resolve_nodes: "Resolve nodes",
  resolve_edges: "Resolve edges",
  analyze_impact: "Analyze impact",
  finalize_graph: "Finalize graph",
  derive_units: "Derive units",
  derive_theme_tree: "Build theme tree",
  derive_prereq_dag: "Build prerequisite DAG",
  finalize_curriculum: "Finalize curriculum",
};

interface DigestJobContextValue {
  activeJobId: number | null;
  setAndPersistJobId: (jobId: number | null) => void;
  subject: string;
}

const DigestJobContext = createContext<DigestJobContextValue | null>(null);

async function fetchSubjectFiles(subject: string): Promise<FilesData> {
  const response = await apiClient<ApiResponse<FilesData>>({
    method: "GET",
    url: `/api/v1/subjects/${subject}/files`,
  });
  return response.data;
}

async function buildDigest(subject: string, fileIds: number[]): Promise<DigestBuildData> {
  const response = await apiClient<ApiResponse<DigestBuildData>>({
    method: "POST",
    url: `/api/v1/subjects/${subject}/knowledge/digest/build`,
    data: { file_ids: fileIds },
  });
  return response.data;
}

async function fetchDigestStatus(subject: string, jobId: number): Promise<DigestStatusData> {
  const response = await apiClient<ApiResponse<DigestStatusData>>({
    method: "POST",
    url: `/api/v1/subjects/${subject}/knowledge/digest/status`,
    data: { job_id: jobId },
  });
  return response.data;
}

export function DigestBuildProvider({
  subject,
  children,
}: {
  subject: string;
  children: React.ReactNode;
}) {
  const storageKey = `digest-job-${subject}`;
  const [activeJobId, setActiveJobId] = useState<number | null>(() => {
    try {
      const saved = localStorage.getItem(storageKey);
      return saved ? Number(saved) : null;
    } catch {
      return null;
    }
  });

  const setAndPersistJobId = useCallback(
    (jobId: number | null) => {
      setActiveJobId(jobId);
      try {
        if (jobId === null) {
          localStorage.removeItem(storageKey);
        } else {
          localStorage.setItem(storageKey, String(jobId));
        }
      } catch {
        // ignore localStorage failures
      }
    },
    [storageKey],
  );

  return (
    <DigestJobContext.Provider value={{ activeJobId, setAndPersistJobId, subject }}>
      {children}
    </DigestJobContext.Provider>
  );
}

function useDigestJob() {
  const context = useContext(DigestJobContext);
  if (!context) {
    throw new Error("useDigestJob must be used inside DigestBuildProvider");
  }
  return context;
}

export function DigestBuildProgress() {
  const { activeJobId, setAndPersistJobId, subject } = useDigestJob();
  const queryClient = useQueryClient();

  const handleComplete = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ["theme-tree", subject] });
    queryClient.invalidateQueries({ queryKey: ["prereq-dag", subject] });
    queryClient.invalidateQueries({ queryKey: ["graph-nodes", subject] });
    setAndPersistJobId(null);
  }, [queryClient, setAndPersistJobId, subject]);

  if (!activeJobId) {
    return null;
  }

  return <BuildProgress subject={subject} jobId={activeJobId} onComplete={handleComplete} />;
}

function BuildProgress({
  subject,
  jobId,
  onComplete,
}: {
  subject: string;
  jobId: number;
  onComplete: () => void;
}) {
  const { data } = useQuery({
    queryKey: ["digest-status", subject, jobId],
    queryFn: () => fetchDigestStatus(subject, jobId),
    enabled: !!jobId,
    refetchInterval: (query) => {
      const status = query.state.data;
      if (!status) {
        return 3000;
      }

      const graphDone =
        status.graph_job.status === "completed" || status.graph_job.status === "failed";
      const curriculumDone =
        !status.curriculum_job ||
        status.curriculum_job.status === "completed" ||
        status.curriculum_job.status === "failed";

      return graphDone && curriculumDone ? false : 3000;
    },
  });

  useEffect(() => {
    if (!data) {
      return;
    }

    const graphDone = data.graph_job.status === "completed";
    const curriculumDone = !data.curriculum_job || data.curriculum_job.status === "completed";
    if (graphDone && curriculumDone) {
      onComplete();
    }
  }, [data, onComplete]);

  if (!data) {
    return (
      <div className="flex items-center gap-2 py-2 text-sm text-slate-400">
        <Loader2 className="h-4 w-4 animate-spin" />
        Loading digest progress...
      </div>
    );
  }

  const { graph_job: graphJob, curriculum_job: curriculumJob } = data;
  const isFailed = graphJob.status === "failed" || curriculumJob?.status === "failed";
  const totalProgress = Math.round(graphJob.progress * 0.5 + (curriculumJob?.progress ?? 0) * 0.5);
  const currentStep = curriculumJob?.current_step || graphJob.current_step;
  const stepLabel = currentStep ? STEP_LABELS[currentStep] ?? currentStep : "Preparing";
  const errorMessage = graphJob.error_message || curriculumJob?.error_message || null;

  return (
    <Card>
      <CardContent className="pb-4 pt-4">
        <div className="space-y-3">
          <div className="flex items-center gap-3">
            {isFailed ? (
              <XCircle className="h-5 w-5 shrink-0 text-red-500" />
            ) : totalProgress >= 100 ? (
              <CheckCircle className="h-5 w-5 shrink-0 text-green-500" />
            ) : (
              <Loader2 className="h-5 w-5 shrink-0 animate-spin text-blue-500" />
            )}
            <div className="flex-1">
              <div className="mb-1 flex items-center justify-between text-sm">
                <span className="text-slate-700">{stepLabel}</span>
                <div className="flex items-center gap-2">
                  <span
                    className={`rounded px-2 py-0.5 text-xs ${
                      graphJob.status === "completed"
                        ? "bg-green-50 text-green-600"
                        : graphJob.status === "failed"
                          ? "bg-red-50 text-red-600"
                          : "bg-blue-50 text-blue-600"
                    }`}
                  >
                    Graph: {graphJob.status}
                  </span>
                  {curriculumJob ? (
                    <span
                      className={`rounded px-2 py-0.5 text-xs ${
                        curriculumJob.status === "completed"
                          ? "bg-green-50 text-green-600"
                          : curriculumJob.status === "failed"
                            ? "bg-red-50 text-red-600"
                            : "bg-blue-50 text-blue-600"
                      }`}
                    >
                      Curriculum: {curriculumJob.status}
                    </span>
                  ) : null}
                  <span className="text-slate-400">{totalProgress}%</span>
                </div>
              </div>
              <div className="h-2 w-full rounded-full bg-slate-100">
                <div
                  className={`h-2 rounded-full transition-all duration-500 ${
                    isFailed ? "bg-red-400" : "bg-blue-500"
                  }`}
                  style={{ width: `${Math.min(totalProgress, 100)}%` }}
                />
              </div>
            </div>
          </div>

          <div className="flex flex-wrap gap-4 text-xs text-slate-500">
            <span>
              Nodes +{graphJob.nodes_added} / updated {graphJob.nodes_updated} / merged {graphJob.nodes_merged}
            </span>
            <span>
              Edges +{graphJob.edges_added} / updated {graphJob.edges_updated}
            </span>
            {curriculumJob ? (
              <span>
                Units +{curriculumJob.units_added} / updated {curriculumJob.units_updated}
              </span>
            ) : null}
          </div>

          {errorMessage ? (
            <div className="mt-2 rounded bg-red-50 p-2 text-xs text-red-500">{errorMessage}</div>
          ) : null}
        </div>
      </CardContent>
    </Card>
  );
}

export function DigestBuildButton() {
  const { setAndPersistJobId, subject } = useDigestJob();
  const [showFileSelect, setShowFileSelect] = useState(false);
  const [selectedFileIds, setSelectedFileIds] = useState<Set<number>>(new Set());

  const { data: filesData, isLoading: filesLoading } = useQuery({
    queryKey: ["digest-files", subject],
    queryFn: () => fetchSubjectFiles(subject),
    enabled: showFileSelect && !!subject,
  });

  const readyFiles = useMemo<FileRecord[]>(
    () => (filesData?.items ?? []).filter((file) => file.markdown_ready),
    [filesData],
  );

  const buildMutation = useMutation({
    mutationFn: () => buildDigest(subject, Array.from(selectedFileIds)),
    onSuccess: (data) => {
      setAndPersistJobId(data.job_id);
      setShowFileSelect(false);
      setSelectedFileIds(new Set());
    },
  });

  const toggleFile = useCallback((fileId: number) => {
    setSelectedFileIds((previous) => {
      const next = new Set(previous);
      if (next.has(fileId)) {
        next.delete(fileId);
      } else {
        next.add(fileId);
      }
      return next;
    });
  }, []);

  return (
    <>
      <Button onClick={() => setShowFileSelect(true)} variant="outline" size="sm">
        <Zap className="mr-1 h-4 w-4" />
        Build digest
      </Button>

      <Modal
        open={showFileSelect}
        onClose={() => setShowFileSelect(false)}
        title="Choose files for digest build"
      >
        <div className="space-y-4">
          <p className="text-sm text-slate-500">
            This panel now reads from the unified `GET /files` response and filters ready files
            locally. The legacy list request path is no longer used.
          </p>

          {filesLoading ? (
            <div className="flex items-center py-4 text-sm text-slate-400">
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              Loading ready files...
            </div>
          ) : null}

          {!filesLoading && readyFiles.length === 0 ? (
            <p className="py-4 text-sm text-slate-400">No ready files are available yet.</p>
          ) : null}

          <div className="max-h-60 space-y-2 overflow-y-auto">
            {readyFiles.map((file) => (
              <label
                key={file.id}
                className={`flex cursor-pointer items-center gap-3 rounded-lg border p-3 transition-colors ${
                  selectedFileIds.has(file.id)
                    ? "border-slate-400 bg-slate-50"
                    : "border-slate-200 hover:bg-slate-50"
                }`}
              >
                <input
                  type="checkbox"
                  checked={selectedFileIds.has(file.id)}
                  onChange={() => toggleFile(file.id)}
                  className="rounded border-slate-300"
                />
                <FileText className="h-4 w-4 text-slate-400" />
                <span className="flex-1 text-sm text-slate-700">{file.filename}</span>
                <CheckCircle className="h-4 w-4 text-green-500" />
              </label>
            ))}
          </div>

          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={() => setShowFileSelect(false)}>
              Cancel
            </Button>
            <Button
              onClick={() => buildMutation.mutate()}
              disabled={selectedFileIds.size === 0 || buildMutation.isPending}
            >
              {buildMutation.isPending ? (
                <>
                  <Loader2 className="mr-1 h-4 w-4 animate-spin" />
                  Building...
                </>
              ) : (
                <>
                  <Play className="mr-1 h-4 w-4" />
                  Start build
                </>
              )}
            </Button>
          </div>

          {buildMutation.isError ? (
            <p className="text-xs text-red-500">
              {getApiErrorMessage(buildMutation.error, "Digest build failed")}
            </p>
          ) : null}
        </div>
      </Modal>
    </>
  );
}
