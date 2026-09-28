"use client";

import { useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || process.env.NEXT_PUBLIC_API_URL || "/api";

type RunActionsRun = {
  id: number;
  agent_key: string;
  status: string;
  approval_decision?: string | null;
};

export type ChildRunSummary = {
  id: number;
  agent_key: string;
  status: string;
  parent_run_id: number | null;
  created_at?: string;
  output_json?: Record<string, unknown> | null;
};

type RunActionsProps = {
  run: RunActionsRun;
  onSuccess?: () => void | Promise<void>;
  onChildRunCreated?: (child: ChildRunSummary) => void;
  onShowToast?: (message: string) => void;
};

export default function RunActions({ run, onSuccess, onChildRunCreated, onShowToast }: RunActionsProps) {
  const [error, setError] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [approveSuccess, setApproveSuccess] = useState(false);

  const showActions = run.agent_key === "ai_development" && run.status === "completed";
  const runId = run.id;

  function getErrorMessage(res: Response, data: { detail?: unknown }): string {
    const d = data?.detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d)) return d.map((x) => (typeof x === "object" && x && "msg" in x ? (x as { msg: string }).msg : String(x))).join(" ");
    return res.statusText || "Request failed";
  }

  const handleApprove = async () => {
    setActionLoading("approve");
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/runs/${runId}/approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision: "approved" }),
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(getErrorMessage(res, d as { detail?: unknown }));
      }
      setApproveSuccess(true);
      onShowToast?.("Approved");
      await onSuccess?.();
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Approve failed";
      setError(msg);
    } finally {
      setActionLoading(null);
    }
  };

  const handleApplyWorkspace = async () => {
    setActionLoading("apply");
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/runs/${runId}/apply_workspace`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(getErrorMessage(res, d as { detail?: unknown }));
      }
      const data = await res.json();
      onShowToast?.("Queued");
      onChildRunCreated?.(data);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Apply to workspace failed";
      setError(msg);
    } finally {
      setActionLoading(null);
    }
  };

  const handleOpenPr = async () => {
    setActionLoading("open_pr");
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/runs/${runId}/open_pr`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(getErrorMessage(res, d as { detail?: unknown }));
      }
      const data = await res.json();
      onShowToast?.("Queued");
      onChildRunCreated?.(data);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Open PR failed";
      setError(msg);
    } finally {
      setActionLoading(null);
    }
  };

  if (!showActions) return null;

  return (
    <div className="mt-6 space-y-2">
      {error && <p className="text-sm text-red-600">{error}</p>}
      {(run.approval_decision === "approved" || approveSuccess) && (
        <p className="text-sm text-green-600 font-medium">✅ Approved</p>
      )}
      <div className="flex flex-wrap gap-3">
        <button
          type="button"
          onClick={handleApprove}
          disabled={!!actionLoading || run.approval_decision === "approved" || approveSuccess}
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
    </div>
  );
}
