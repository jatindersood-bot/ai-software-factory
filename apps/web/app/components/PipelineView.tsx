"use client";

import Link from "next/link";
import { Card, CardBody, CardHeader } from "./Card";
import { Badge } from "./Badge";

export type Project = {
  id: number;
  title: string;
  idea: string;
  created_at: string;
};

export type Artifact = {
  id: number;
  run_id: number;
  project_id: number;
  path: string;
};

export type Run = {
  id: number;
  project_id: number;
  agent_key: string;
  status: string;
  parent_run_id: number | null;
  created_at: string;
  artifacts: Artifact[];
  approval_decision?: string | null;
  output_json?: Record<string, unknown> | null;
};

export type Stage = {
  agent_key: string;
  display_name: string;
  depends_on: string | null;
};

type PipelineViewProps = {
  project: Project;
  stages: Stage[];
  runs: Run[];
  getLatestRun: (agentKey: string) => Run | null;
  isStageUnlocked: (stage: Stage, index: number) => boolean;
  startRun: (agentKey: string, parentRunId?: number) => void;
  approveRun: (runId: number, decision: "approved" | "rejected", feedback?: string) => void;
  actionLoading: string | null;
  reviewRunId: number | null;
  setReviewRunId: (id: number | null) => void;
  rejectFeedback: string;
  setRejectFeedback: (s: string) => void;
  approveLoading: boolean;
  previewInstructionsContent?: string | null;
};

export function PipelineView(props: PipelineViewProps) {
  const {
    project,
    stages,
    runs,
    getLatestRun,
    isStageUnlocked,
    startRun,
    approveRun,
    actionLoading,
    reviewRunId,
    setReviewRunId,
    rejectFeedback,
    setRejectFeedback,
    approveLoading,
    previewInstructionsContent = null,
  } = props;

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="mx-auto max-w-4xl px-4 py-6">
        <Link href="/projects" className="text-sm font-medium text-blue-600 hover:underline">
          ← Back to projects
        </Link>
        <h1 className="mt-4 text-2xl font-semibold text-gray-900">{project.title}</h1>
        <p className="mt-1 text-gray-600 line-clamp-2">{project.idea}</p>

        <div className="mt-8 space-y-4">
          {stages.map((stage, index) => {
            const run = getLatestRun(stage.agent_key);
            const unlocked = isStageUnlocked(stage, index);
const needsReview =
  run?.status === "completed" &&
  run.approval_decision == null;
            const showReviewPanel = reviewRunId === run?.id;

            return (
              <Card key={stage.agent_key}>
                <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-2">
                  <span className="font-medium text-gray-900">{stage.display_name}</span>
                  <div className="flex flex-wrap items-center gap-2">
                    {run ? (
                      <>
                        <Badge
                          variant={
                            run.status === "completed"
                              ? "success"
                              : run.status === "failed"
                                ? "error"
                                : "info"
                          }
                        >
                          {run.status}
                        </Badge>
                        {run.approval_decision != null && (
                          <Badge variant={run.approval_decision === "approved" ? "success" : "error"}>
                            {run.approval_decision}
                          </Badge>
                        )}
                      </>
                    ) : (
                      <span className="text-xs text-gray-400">No run yet</span>
                    )}
                  </div>
                </CardHeader>
                <CardBody>
                  {run && (
                    <p className="text-xs text-gray-500">
                      Last run: {new Date(run.created_at).toLocaleString()}
                    </p>
                  )}
                  {run?.artifacts?.length ? (
                    <ul className="mt-2 flex flex-wrap gap-2">
                      {run.artifacts.slice(0, 5).map((a) => (
                        <li key={a.id}>
                          <Link
                            href={`/artifacts/${a.id}`}
                            className="text-sm text-blue-600 hover:underline"
                          >
                            {a.path}
                          </Link>
                        </li>
                      ))}
                      {run.artifacts.length > 5 && (
                        <li>
                          <Link
                            href={`/runs/${run.id}`}
                            className="text-sm text-gray-500 hover:underline"
                          >
                            +{run.artifacts.length - 5} more
                          </Link>
                        </li>
                      )}
                    </ul>
                  ) : null}

                  <div className="mt-3 flex flex-wrap gap-2">
                    {run && (
                      <Link
                        href={`/runs/${run.id}`}
                        className="rounded border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
                      >
                        View output
                      </Link>
                    )}
                    {stage.agent_key === "preview_start" && (
                      <>
                        {(run?.output_json?.preview_url ?? run?.output_json?.ui_url ?? run?.artifacts?.some((a) => a.path.endsWith("PREVIEW_URL.txt"))) ? (
                          <a
                            href={String(run?.output_json?.preview_url ?? run?.output_json?.ui_url ?? "http://localhost:3001")}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="rounded bg-green-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-green-700"
                          >
                            Open Preview
                          </a>
                        ) : (
                          <>
                            {previewInstructionsContent != null && previewInstructionsContent !== "" && (
                              <div className="mt-2 w-full rounded border border-gray-200 bg-gray-50 p-3 text-left">
                                <h4 className="text-xs font-medium text-gray-500 mb-2">Run locally</h4>
                                <pre className="whitespace-pre-wrap text-sm text-gray-800 font-mono overflow-x-auto">
                                  {previewInstructionsContent}
                                </pre>
                              </div>
                            )}
                            <button
                              type="button"
                              onClick={() => {
                                const smokeRun = getLatestRun("smoke_check");
                                startRun("preview_start", smokeRun?.status === "completed" ? smokeRun.id : undefined);
                              }}
                              disabled={!unlocked || actionLoading === "preview_start"}
                              className="rounded bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
                            >
                              {actionLoading === "preview_start" ? "…" : "Start Preview"}
                            </button>
                          </>
                        )}
                      </>
                    )}
                    {stage.agent_key !== "preview_start" && (
                      <>
                        <button
                          type="button"
                          onClick={() => {
                            const parentRunId =
                              stage.depends_on != null
                                ? (() => {
                                    const depRun = getLatestRun(stage.depends_on!);
                                    return depRun?.status === "completed" &&
                                      depRun?.approval_decision === "approved"
                                      ? depRun.id
                                      : undefined;
                                  })()
                                : undefined;
                            startRun(stage.agent_key, parentRunId);
                          }}
                          disabled={!unlocked || actionLoading != null}
                          className="rounded bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
                        >
                          {actionLoading === stage.agent_key
                            ? "…"
                            : stage.agent_key === "apply_workspace"
                              ? run
                                ? "Re-apply to workspace"
                                : "Apply to workspace"
                              : stage.agent_key === "open_pr"
                                ? run
                                  ? "Re-open PR"
                                  : "Open PR"
                                : run
                                  ? "Re-run"
                                  : "Run"}
                        </button>
                        {needsReview && (
                          <button
                            type="button"
                            onClick={() => setReviewRunId(run!.id)}
                            className="rounded bg-amber-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-amber-700"
                          >
                            Review
                          </button>
                        )}
                      </>
                    )}
                  </div>

                  {showReviewPanel && run && (
                    <div className="mt-4 rounded border border-amber-200 bg-amber-50 p-4">
                      <h4 className="font-medium text-amber-900">Review</h4>
                      {run.output_json?.summary != null && (
                        <p className="mt-1 text-sm text-amber-800">
                          {String(run.output_json.summary)}
                        </p>
                      )}
                      <div className="mt-3 flex flex-wrap gap-2">
                        <button
                          type="button"
                          onClick={() => approveRun(run.id, "approved")}
                          disabled={approveLoading}
                          className="rounded bg-green-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-50"
                        >
                          Approve
                        </button>
                        <button
                          type="button"
                          onClick={() => approveRun(run.id, "rejected", rejectFeedback)}
                          disabled={approveLoading}
                          className="rounded bg-red-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50"
                        >
                          Reject
                        </button>
                        <input
                          type="text"
                          placeholder="Feedback (optional)"
                          value={rejectFeedback}
                          onChange={(e) => setRejectFeedback(e.target.value)}
                          className="rounded border border-amber-300 px-2 py-1 text-sm"
                        />
                        <button
                          type="button"
                          onClick={() => setReviewRunId(null)}
                          className="text-sm text-gray-600 hover:underline"
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  )}
                </CardBody>
              </Card>
            );
          })}
        </div>

        {stages.length === 0 && (
          <p className="mt-6 text-gray-500">Pipeline not configured. Add stages in API.</p>
        )}
      </div>
    </div>
  );
}
