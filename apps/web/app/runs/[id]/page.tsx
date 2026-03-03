"use client";

import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

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
};

export default function RunInspectorPage() {
  const params = useParams();
  const router = useRouter();
  const id = params.id as string;
  const [run, setRun] = useState<Run | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [artifactContent, setArtifactContent] = useState<Record<number, string | null>>({});

  const fetchRun = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/runs/${id}`);
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.detail || res.statusText || "Failed to load run");
      }
      const data = await res.json();
      setRun(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load run");
      setRun(null);
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    fetchRun();
  }, [fetchRun]);

  const showActions =
    run?.agent_key === "ai_development" && run?.status === "completed";

  const handleApprove = async () => {
    setActionLoading("approve");
    try {
      const res = await fetch(`${API_BASE}/runs/${id}/approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision: "approved" }),
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.detail || res.statusText);
      }
      await fetchRun();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Approve failed");
    } finally {
      setActionLoading(null);
    }
  };

  const handleApplyWorkspace = async () => {
    setActionLoading("apply");
    try {
      const res = await fetch(`${API_BASE}/runs/${id}/apply_workspace`, {
        method: "POST",
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.detail || res.statusText);
      }
      const data = await res.json();
      router.push(`/runs/${data.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Apply to workspace failed");
    } finally {
      setActionLoading(null);
    }
  };

  const handleOpenPr = async () => {
    setActionLoading("open_pr");
    try {
      const res = await fetch(`${API_BASE}/runs/${id}/open_pr`, {
        method: "POST",
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.detail || res.statusText);
      }
      const data = await res.json();
      router.push(`/runs/${data.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Open PR failed");
    } finally {
      setActionLoading(null);
    }
  };

  async function fetchArtifactContent(artifactId: number) {
    if (artifactContent[artifactId] !== undefined) return;
    try {
      const res = await fetch(`${API_BASE}/artifacts/${artifactId}/content`);
      if (!res.ok) throw new Error("Failed to load");
      const data = await res.json();
      setArtifactContent((prev) => ({ ...prev, [artifactId]: data.content ?? "" }));
    } catch {
      setArtifactContent((prev) => ({ ...prev, [artifactId]: null }));
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
    <main className="p-6 max-w-3xl">
      <a href="/" className="text-blue-600 underline text-sm">
        Back
      </a>
      <h1 className="text-xl font-semibold mt-4">Run {run.id}</h1>

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
                    : "text-gray-700"
              }
            >
              {run.status}
            </span>
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

      {run.output_json != null && Object.keys(run.output_json).length > 0 && (
        <section className="mt-6">
          <h2 className="text-sm font-medium text-gray-500 mb-1">output_json</h2>
          <pre className="p-3 rounded bg-gray-100 text-sm overflow-x-auto max-h-64 overflow-y-auto">
            {JSON.stringify(run.output_json, null, 2)}
          </pre>
        </section>
      )}

      {run.artifacts?.length > 0 && (
        <section className="mt-6">
          <h2 className="text-sm font-medium text-gray-500 mb-2">Artifacts</h2>
          <ul className="space-y-2 text-sm">
            {run.artifacts.map((a) => (
              <li key={a.id} className="flex flex-wrap items-start gap-2">
                <span className="text-gray-700">{a.path}</span>
                <button
                  type="button"
                  onClick={() => fetchArtifactContent(a.id)}
                  className="text-blue-600 underline hover:no-underline"
                >
                  View content
                </button>
                {artifactContent[a.id] !== undefined && (
                  <div className="w-full mt-1">
                    {artifactContent[a.id] === null ? (
                      <span className="text-red-600 text-xs">Failed to load</span>
                    ) : (
                      <pre className="p-2 rounded bg-gray-100 text-xs overflow-x-auto max-h-48 overflow-y-auto whitespace-pre-wrap">
                        {artifactContent[a.id]}
                      </pre>
                    )}
                  </div>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      {showActions && (
        <div className="mt-6 flex flex-wrap gap-3">
          <button
            type="button"
            onClick={handleApprove}
            disabled={!!actionLoading}
            className="px-4 py-2 rounded bg-gray-200 hover:bg-gray-300 disabled:opacity-50 text-sm font-medium"
          >
            {actionLoading === "approve" ? "…" : "Approve"}
          </button>
          <button
            type="button"
            onClick={handleApplyWorkspace}
            disabled={!!actionLoading}
            className="px-4 py-2 rounded bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 text-sm font-medium"
          >
            {actionLoading === "apply" ? "…" : "Apply to Workspace"}
          </button>
          <button
            type="button"
            onClick={handleOpenPr}
            disabled={!!actionLoading}
            className="px-4 py-2 rounded bg-green-600 text-white hover:bg-green-700 disabled:opacity-50 text-sm font-medium"
          >
            {actionLoading === "open_pr" ? "…" : "Open PR"}
          </button>
        </div>
      )}
    </main>
  );
}
