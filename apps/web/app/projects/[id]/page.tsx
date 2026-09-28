"use client";

import { useParams } from "next/navigation";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useToast } from "../../components/ToastContext";
import { PipelineView, type Project, type Run, type Stage } from "../../components/PipelineView";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ||
  process.env.NEXT_PUBLIC_API_URL ||
  "/api";

export default function ProjectPipelinePage() {
  const params = useParams();
  const id = params.id as string;
  const { addToast } = useToast();
  const [project, setProject] = useState<Project | null>(null);
  const [runs, setRuns] = useState<Run[]>([]);
  const [stages, setStages] = useState<Stage[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [reviewRunId, setReviewRunId] = useState<number | null>(null);
  const [rejectFeedback, setRejectFeedback] = useState("");
  const [approveLoading, setApproveLoading] = useState(false);
  const [previewInstructionsContent, setPreviewInstructionsContent] = useState<string | null>(null);
  const runsStatusKey = runs.map((r) => `${r.id}:${r.status}`).join(",");

  const fetchProject = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/projects/${id}`);
      if (!res.ok) throw new Error("Failed to load project");
      const data = await res.json();
      setProject(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load project");
      setProject(null);
    }
  }, [id]);

  const fetchRuns = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/projects/${id}/runs?include_artifacts=true`);
      if (!res.ok) return;
      const data = await res.json();
      setRuns(data);
    } catch {
      // keep state
    }
  }, [id]);

  const fetchPipeline = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/pipeline`);
      if (!res.ok) return;
      const data = await res.json();
      setStages(data.stages || []);
    } catch {
      setStages([]);
    }
  }, []);

  useEffect(() => {
    setLoading(true);
    setError(null);
    Promise.all([fetchProject(), fetchPipeline()]).finally(() => setLoading(false));
  }, [fetchProject, fetchPipeline]);

  useEffect(() => {
    if (project) fetchRuns();
  }, [project?.id, fetchRuns]);

  function getLatestRun(agentKey: string): Run | null {
    const agentRuns = runs.filter((r) => r.agent_key === agentKey);
    if (agentRuns.length === 0) return null;
    return agentRuns.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())[0];
  }

  const latestSmokeCheck = getLatestRun("smoke_check");
  const previewInstructionsArtifactId = latestSmokeCheck?.artifacts?.find((x) =>
    x.path.endsWith("PREVIEW_INSTRUCTIONS.md")
  )?.id;

  useEffect(() => {
    if (!previewInstructionsArtifactId) {
      setPreviewInstructionsContent(null);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`${API_BASE}/artifacts/${previewInstructionsArtifactId}/content`);
        if (!res.ok || cancelled) return;
        const data = await res.json();
        setPreviewInstructionsContent(data.content ?? null);
      } catch {
        if (!cancelled) setPreviewInstructionsContent(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [previewInstructionsArtifactId]);

  useEffect(() => {
    if (!project) return;
    const anyPending = runs.some(
      (r) => r.status !== "completed" && r.status !== "failed"
    );
    if (!anyPending) return;
    const t = setInterval(fetchRuns, 2000);
    return () => clearInterval(t);
  }, [project?.id, runsStatusKey, fetchRuns]);

  function isStageUnlocked(stage: Stage, index: number): boolean {
    if (stage.agent_key === "preview_start") {
      const smokeRun = getLatestRun("smoke_check");
      return smokeRun != null && smokeRun.status === "completed";
    }
    if (stage.depends_on == null) return true;
    const depRun = getLatestRun(stage.depends_on);
    return (
      depRun != null &&
      depRun.status === "completed" &&
      depRun.approval_decision === "approved"
    );
  }

  async function startRun(agentKey: string, parentRunId?: number) {
    setActionLoading(agentKey);
    setError(null);
    try {
      const body: { agent_key: string; parent_run_id?: number } = { agent_key: agentKey };
      if (parentRunId != null) body.parent_run_id = parentRunId;
      const res = await fetch(`${API_BASE}/projects/${id}/runs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.detail || res.statusText || "Failed to start run");
      }
      await fetchRuns();
      addToast("success", "Run queued");
    } catch (e) {
      addToast("error", e instanceof Error ? e.message : "Failed to start run");
    } finally {
      setActionLoading(null);
    }
  }

  async function approveRun(runId: number, decision: "approved" | "rejected", feedback?: string) {
    setApproveLoading(true);
    try {
      const res = await fetch(`${API_BASE}/runs/${runId}/approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision, feedback: feedback || null }),
      });
      if (!res.ok) throw new Error("Approval failed");
      await fetchRuns();
      setReviewRunId(null);
      setRejectFeedback("");
      addToast("success", decision === "approved" ? "Approved" : "Rejected");
    } catch (e) {
      addToast("error", e instanceof Error ? e.message : "Approval failed");
    } finally {
      setApproveLoading(false);
    }
  }

  if (loading) {
    return (
      <main className="p-6">
        <p className="text-gray-600">Loading project…</p>
      </main>
    );
  }

  if (error || !project) {
    return (
      <main className="p-6">
        <p className="text-red-600">{error || "Project not found"}</p>
        <Link href="/projects" className="mt-2 inline-block text-blue-600 underline text-sm">
          Back to projects
        </Link>
      </main>
    );
  }

  return (
    <PipelineView
      project={project}
      stages={stages}
      runs={runs}
      getLatestRun={getLatestRun}
      isStageUnlocked={isStageUnlocked}
      startRun={startRun}
      approveRun={approveRun}
      actionLoading={actionLoading}
      reviewRunId={reviewRunId}
      setReviewRunId={setReviewRunId}
      rejectFeedback={rejectFeedback}
      setRejectFeedback={setRejectFeedback}
      approveLoading={approveLoading}
      previewInstructionsContent={previewInstructionsContent}
    />
  );
}
