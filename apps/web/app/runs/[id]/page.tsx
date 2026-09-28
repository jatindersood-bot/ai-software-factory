"use client";

import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import RunActions, { type ChildRunSummary } from "./RunActions";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || process.env.NEXT_PUBLIC_API_URL || "/api";

type Run = {
  id: number;
  project_id: number;
  agent_key: string;
  status: string;
  parent_run_id: number | null;
  input_json: Record<string, unknown> | null;
  output_json: Record<string, unknown> | null;
  created_at: string;
  artifacts: Array<{ id: number; path: string }>;
  approval_decision?: string | null;
};

export default function RunInspectorPage() {
  const params = useParams();
  const router = useRouter();
  const id = params.id as string;
  const [run, setRun] = useState<Run | null>(null);
  const [rerunLoading, setRerunLoading] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [childRuns, setChildRuns] = useState<ChildRunSummary[]>([]);
  const [showJobStartedBanner, setShowJobStartedBanner] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [refreshLoading, setRefreshLoading] = useState(false);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const errorShownForRunIds = useRef<Set<number>>(new Set());
  const applySucceededShownForRunIds = useRef<Set<number>>(new Set());
  const finishedChildRunIds = useRef<Set<number>>(new Set());
  const completedRefetchRunId = useRef<number | null>(null);

  const fetchRun = useCallback(async (skipLoading = false) => {
    if (!skipLoading) setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/runs/${id}`);
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.detail || res.statusText || "Failed to load run");
      }
      const data = await res.json();
      setRun(data);
      setLastUpdated(new Date());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load run");
      setRun(null);
    } finally {
      if (!skipLoading) setLoading(false);
    }
  }, [id]);

  const fetchChildRuns = useCallback(
    async (projectId: number, parentRunId: number) => {
      try {
        const res = await fetch(`${API_BASE}/projects/${projectId}/timeline`);
        if (!res.ok) return;
        const timeline: Run[] = await res.json();
        setChildRuns(timeline.filter((r) => r.parent_run_id === parentRunId));
      } catch {
        // keep existing childRuns
      }
    },
    []
  );

  useEffect(() => {
    fetchRun();
  }, [fetchRun]);

  useEffect(() => {
    if (run?.status === "failed" && run.output_json?.error != null) {
      const err = typeof run.output_json.error === "string" ? run.output_json.error : String(run.output_json.error);
      if (!errorShownForRunIds.current.has(run.id)) {
        errorShownForRunIds.current.add(run.id);
        setError(err);
      }
    }
    for (const c of childRuns) {
      if (c.status === "failed" && c.output_json?.error != null) {
        const err = typeof c.output_json.error === "string" ? c.output_json.error : String(c.output_json.error);
        if (!errorShownForRunIds.current.has(c.id)) {
          errorShownForRunIds.current.add(c.id);
          setError(err);
        }
      }
      if (c.agent_key === "apply_workspace" && c.status === "completed") {
        if (!applySucceededShownForRunIds.current.has(c.id)) {
          applySucceededShownForRunIds.current.add(c.id);
          setMessage("Apply succeeded");
        }
      }
    }
  }, [run, childRuns]);

  useEffect(() => {
    if (run) fetchChildRuns(run.project_id, run.id);
  }, [run?.id, run?.project_id, fetchChildRuns]);

  // When run status becomes completed, refetch once to refresh artifacts
  useEffect(() => {
    if (!run || run.status !== "completed") return;
    if (completedRefetchRunId.current === run.id) return;
    completedRefetchRunId.current = run.id;
    fetchRun(true);
  }, [run?.id, run?.status, fetchRun]);

  // When a child run finishes, refresh run and child runs so artifact list and statuses are up to date
  useEffect(() => {
    if (!run) return;
    let didRefresh = false;
    for (const c of childRuns) {
      if ((c.status === "completed" || c.status === "failed") && !finishedChildRunIds.current.has(c.id)) {
        finishedChildRunIds.current.add(c.id);
        didRefresh = true;
      }
    }
    if (didRefresh) {
      fetchRun(true);
      fetchChildRuns(run.project_id, run.id);
    }
  }, [run, childRuns, fetchRun, fetchChildRuns]);

  const childStatusKey = childRuns.map((c) => c.status).join(",");
  const mainRunPending = run?.status === "queued" || run?.status === "running";
  const anyChildPending = childRuns.some(
    (c) => c.status !== "completed" && c.status !== "failed"
  );
  useEffect(() => {
    if (!run) return;
    if (!mainRunPending && !anyChildPending) return;

    const poll = async () => {
      try {
        const res = await fetch(`${API_BASE}/runs/${id}`);
        if (res.ok) {
          const data: Run = await res.json();
          setRun(data);
          const tRes = await fetch(`${API_BASE}/projects/${data.project_id}/runs`);
          if (tRes.ok) {
            const list: Run[] = await tRes.json();
            setChildRuns(list.filter((r) => r.parent_run_id === data.id));
          }
          setLastUpdated(new Date());
        }
      } catch {
        // keep existing state
      }
    };

    const intervalId = setInterval(poll, 1000);
    return () => clearInterval(intervalId);
  }, [id, mainRunPending, anyChildPending]);

  const handleChildRunCreated = useCallback((child: ChildRunSummary) => {
    setChildRuns((prev) => (prev.some((r) => r.id === child.id) ? prev : [...prev, child]));
    setShowJobStartedBanner(true);
    setTimeout(() => setShowJobStartedBanner(false), 5000);
  }, []);

  const showToast = useCallback((message: string) => {
    setToast(message);
    setTimeout(() => setToast(null), 3000);
  }, []);

  const handleRefresh = useCallback(async () => {
    if (!run) return;
    setRefreshLoading(true);
    try {
      await fetchRun(true);
      await fetchChildRuns(run.project_id, run.id);
    } finally {
      setRefreshLoading(false);
    }
  }, [run, fetchRun, fetchChildRuns]);

  const buildType = run?.output_json && typeof run.output_json.build_type === "object"
    ? (run.output_json.build_type as { has_frontend?: boolean; has_backend?: boolean })
    : null;
  const hasFrontend = buildType?.has_frontend === true;
  const hasBackend = buildType?.has_backend === true;
  const previewStartChild = childRuns
    .filter((c) => c.agent_key === "preview_start")
    .sort((a, b) => b.id - a.id)[0] ?? null;
  const previewRunning = previewStartChild?.status === "queued" || previewStartChild?.status === "running";
  const previewCompleted = previewStartChild?.status === "completed";
  const previewFailed = previewStartChild?.status === "failed";

  async function handleStartPreview() {
    if (!run) return;
    setPreviewLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/runs/${run.id}/preview_start`, { method: "POST" });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.detail || res.statusText || "Failed to start preview");
      }
      const data = await res.json();
      handleChildRunCreated(data);
      showToast("Preview starting…");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to start preview");
    } finally {
      setPreviewLoading(false);
    }
  }

  async function handleRerunAiDevelopment() {
    if (!run || run.agent_key !== "ai_development") return;
    setRerunLoading(true);
    try {
      const res = await fetch(`${API_BASE}/runs/${run.id}/rerun`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ agent_key: "ai_development" }),
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.detail || res.statusText || "Rerun failed");
      }
      const data = await res.json();
      router.push(`/runs/${data.id}`);
    } catch (e) {
      setMessage(null);
      setError(e instanceof Error ? e.message : "Rerun failed");
    } finally {
      setRerunLoading(false);
    }
  }

  if (loading) {
    return (
      <main className="p-6">
        <p className="text-gray-600">Loading run…</p>
      </main>
    );
  }

  if (error || !run) {
    return (
      <main className="p-6">
        <p className="text-red-600">{error || "Run not found"}</p>
        <a href="/" className="mt-2 inline-block text-blue-600 underline">
          Back
        </a>
      </main>
    );
  }

  return (
    <>
      {toast && (
        <div className="fixed bottom-4 right-4 z-20 rounded-lg bg-gray-900 px-4 py-2 text-sm font-medium text-white shadow-lg">
          {toast}
        </div>
      )}
      <header className="sticky top-0 z-10 bg-white border-b border-gray-200 px-6 py-3 flex flex-wrap items-center gap-3">
        <a
          href={`/projects/${run.project_id}`}
          className="text-blue-600 underline hover:no-underline text-sm font-medium"
        >
          Back to Project
        </a>
        <a
          href={`/projects/${run.project_id}#runs`}
          className="text-gray-600 hover:text-gray-900 text-sm"
        >
          Back to Runs
        </a>
      </header>
      <main className="p-6 max-w-3xl">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-xl font-semibold">Run {run.id}</h1>
          <span
            className={
              run.status === "completed"
                ? "rounded-full bg-green-100 px-3 py-1 text-sm font-medium text-green-800"
                : run.status === "failed"
                  ? "rounded-full bg-red-100 px-3 py-1 text-sm font-medium text-red-800"
                  : run.status === "running"
                    ? "rounded-full bg-blue-100 px-3 py-1 text-sm font-medium text-blue-800"
                    : "rounded-full bg-gray-200 px-3 py-1 text-sm font-medium text-gray-800"
            }
          >
            {run.status}
          </span>
          <button
            type="button"
            onClick={handleRefresh}
            disabled={refreshLoading}
            className="rounded border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
          >
            {refreshLoading ? "Refreshing…" : "Refresh"}
          </button>
        </div>
      {message && (
        <div className="mt-2 px-3 py-2 rounded bg-green-100 text-green-800 text-sm font-medium">
          {message}
        </div>
      )}
      {error && (
        <div className="mt-2 px-3 py-2 rounded bg-red-100 text-red-800 text-sm font-medium">
          {error}
        </div>
      )}
      {lastUpdated != null && (
        <p className="text-gray-500 text-sm mt-1">
          Last updated: {lastUpdated.toLocaleTimeString()}
        </p>
      )}

      <section className="mt-4">
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
          <dt className="text-gray-500">Status</dt>
          <dd>
            <span
              className={
                run.status === "completed"
                  ? "text-green-600"
                  : run.status === "failed"
                    ? "text-red-600"
                    : run.status === "running"
                      ? "text-blue-600"
                      : "text-gray-700"
              }
            >
              {run.status}
            </span>
          </dd>
          <dt className="text-gray-500">Approval</dt>
          <dd>
            {run.approval_decision === "approved" ? (
              <span className="text-green-600">Approved</span>
            ) : run.approval_decision === "rejected" ? (
              <span className="text-amber-600">Rejected</span>
            ) : (
              <span className="text-gray-500">Pending</span>
            )}
          </dd>
          <dt className="text-gray-500">Agent</dt>
          <dd>{run.agent_key}</dd>
          {run.parent_run_id != null && (
            <>
              <dt className="text-gray-500">Parent run</dt>
              <dd>
                <a href={`/runs/${run.parent_run_id}`} className="text-blue-600 underline">
                  {run.parent_run_id}
                </a>
              </dd>
            </>
          )}
        </dl>
      </section>

      {run.agent_key === "ai_development" && run.output_json != null && (run.output_json.llm_meta != null || run.output_json.file_count != null) && (
        <section className="mt-4">
          <h2 className="text-sm font-medium text-gray-500 mb-2">LLM</h2>
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
            {run.output_json.llm_meta != null && typeof run.output_json.llm_meta === "object" && (
              <>
                {"model" in run.output_json.llm_meta && (
                  <>
                    <dt className="text-gray-500">Model</dt>
                    <dd className="text-gray-900">{String((run.output_json.llm_meta as Record<string, unknown>).model)}</dd>
                  </>
                )}
                {"latency_ms" in run.output_json.llm_meta && (
                  <>
                    <dt className="text-gray-500">Latency</dt>
                    <dd className="text-gray-900">{String((run.output_json.llm_meta as Record<string, unknown>).latency_ms)} ms</dd>
                  </>
                )}
                {"retries" in run.output_json.llm_meta && (
                  <>
                    <dt className="text-gray-500">Retries</dt>
                    <dd className="text-gray-900">{String((run.output_json.llm_meta as Record<string, unknown>).retries)}</dd>
                  </>
                )}
              </>
            )}
            {run.output_json.file_count != null && (
              <>
                <dt className="text-gray-500">Files</dt>
                <dd className="text-gray-900">{String(run.output_json.file_count)}</dd>
              </>
            )}
          </dl>
        </section>
      )}

      {run.agent_key === "ai_development" && (
        <div className="mt-4">
          <button
            type="button"
            onClick={handleRerunAiDevelopment}
            disabled={rerunLoading}
            className="rounded bg-amber-600 px-4 py-2 text-sm font-medium text-white hover:bg-amber-700 disabled:opacity-50"
          >
            {rerunLoading ? "Starting…" : "Rerun ai_development"}
          </button>
        </div>
      )}

      {showJobStartedBanner && (
        <div className="mt-4 px-3 py-2 rounded bg-green-100 text-green-800 text-sm font-medium">
          Job started. It appears in Child Runs below.
        </div>
      )}

      {(hasFrontend || hasBackend) && run.status === "completed" && (
        <section className="mt-6">
          <h2 className="text-sm font-medium text-gray-500 mb-2">Preview</h2>
          {previewRunning && (
            <p className="text-sm text-gray-600 mb-2">Starting preview…</p>
          )}
          {previewFailed && previewStartChild?.output_json && typeof previewStartChild.output_json.error === "string" && (
            <p className="text-sm text-red-600 mb-2">{previewStartChild.output_json.error}</p>
          )}
          {!previewCompleted && (
            <div className="flex flex-wrap gap-2">
              {hasFrontend && (
                <button
                  type="button"
                  onClick={handleStartPreview}
                  disabled={previewLoading || previewRunning}
                  className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
                >
                  {previewLoading ? "Starting…" : "Start UI Preview"}
                </button>
              )}
              {hasBackend && (
                <button
                  type="button"
                  onClick={handleStartPreview}
                  disabled={previewLoading || previewRunning}
                  className="rounded bg-green-600 px-4 py-2 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-50"
                >
                  {previewLoading ? "Starting…" : "Start API Preview"}
                </button>
              )}
            </div>
          )}
          {previewCompleted && previewStartChild?.output_json && (
            <div className="space-y-2 text-sm">
              {((previewStartChild.output_json as Record<string, unknown>).preview_url ?? (previewStartChild.output_json as Record<string, unknown>).ui_url) != null && (
                <p className="flex items-center gap-2">
                  <span className="text-gray-600">Preview:</span>
                  <a
                    href={String((previewStartChild.output_json as Record<string, unknown>).preview_url ?? (previewStartChild.output_json as Record<string, unknown>).ui_url)}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-blue-600 underline hover:no-underline"
                  >
                    Open Preview
                  </a>
                  <span className="text-gray-500 font-mono text-xs">
                    {(previewStartChild.output_json as Record<string, unknown>).preview_url ?? (previewStartChild.output_json as Record<string, unknown>).ui_url as string}
                  </span>
                </p>
              )}
              {(previewStartChild.output_json as Record<string, unknown>).api_url != null && (
                <p className="flex items-center gap-2">
                  <span className="text-gray-600">API:</span>
                  <a
                    href={String((previewStartChild.output_json as Record<string, unknown>).api_url)}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-blue-600 underline hover:no-underline"
                  >
                    Open
                  </a>
                  <span className="text-gray-500 font-mono text-xs">
                    {(previewStartChild.output_json as Record<string, unknown>).api_url as string}
                  </span>
                </p>
              )}
              {(previewStartChild.output_json as Record<string, unknown>).docs_url != null && (
                <p className="flex items-center gap-2">
                  <span className="text-gray-600">Docs:</span>
                  <a
                    href={String((previewStartChild.output_json as Record<string, unknown>).docs_url)}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-blue-600 underline hover:no-underline"
                  >
                    Open
                  </a>
                  <span className="text-gray-500 font-mono text-xs">
                    {(previewStartChild.output_json as Record<string, unknown>).docs_url as string}
                  </span>
                </p>
              )}
            </div>
          )}
        </section>
      )}

      {childRuns.length > 0 && (
        <section className="mt-6">
          <h2 className="text-sm font-medium text-gray-500 mb-2">Child Runs</h2>
          <ul className="space-y-2 text-sm">
            {childRuns.map((c) => (
              <li key={c.id} className="flex flex-wrap items-center gap-2">
                <Link
                  href={`/runs/${c.id}`}
                  className="text-blue-600 underline hover:no-underline font-medium"
                >
                  Run {c.id}
                </Link>
                <span className="text-gray-500">{c.agent_key}</span>
                <span
                  className={
                    c.status === "completed"
                      ? "rounded-full bg-green-100 px-2.5 py-0.5 text-xs font-medium text-green-800"
                      : c.status === "failed"
                        ? "rounded-full bg-red-100 px-2.5 py-0.5 text-xs font-medium text-red-800"
                        : c.status === "running"
                          ? "rounded-full bg-blue-100 px-2.5 py-0.5 text-xs font-medium text-blue-800"
                          : "rounded-full bg-gray-200 px-2.5 py-0.5 text-xs font-medium text-gray-800"
                  }
                >
                  {c.status}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {run.output_json != null && Object.keys(run.output_json).length > 0 && (
        <section className="mt-6">
          <h2 className="text-sm font-medium text-gray-500 mb-1">output_json</h2>
          <pre className="p-3 rounded bg-gray-100 text-sm overflow-x-auto max-h-96 overflow-y-auto">
            {JSON.stringify(run.output_json, null, 2)}
          </pre>
        </section>
      )}

      {run.input_json != null && Object.keys(run.input_json).length > 0 && (
        <section className="mt-6">
          <h2 className="text-sm font-medium text-gray-500 mb-1">input_json</h2>
          <pre className="p-3 rounded bg-gray-100 text-sm overflow-x-auto max-h-64 overflow-y-auto">
            {JSON.stringify(run.input_json, null, 2)}
          </pre>
        </section>
      )}

      {run.artifacts?.length > 0 && (
        <section className="mt-6">
          <h2 className="text-sm font-medium text-gray-500 mb-2">Artifacts</h2>
          <ul className="space-y-2 text-sm">
            {run.artifacts.map((a) => (
              <li key={a.id} className="flex flex-wrap items-center gap-2">
                <span className="text-gray-700">{a.path}</span>
                <Link
                  href={`/artifacts/${a.id}`}
                  className="text-blue-600 underline hover:no-underline"
                >
                  View
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}

      <RunActions run={run} onSuccess={fetchRun} onChildRunCreated={handleChildRunCreated} onShowToast={showToast} />
    </main>
    </>
  );
}
