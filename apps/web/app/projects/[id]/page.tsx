"use client";

import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type Project = {
  id: number;
  title: string;
  idea: string;
  github_owner?: string;
  github_repo?: string;
  github_repo_url?: string;
  github_default_branch: string;
  created_at: string;
};

export default function ProjectPage() {
  const params = useParams();
  const router = useRouter();
  const id = params.id as string;
  const [project, setProject] = useState<Project | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [runLoading, setRunLoading] = useState(false);

  const fetchProject = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/projects/${id}`);
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.detail || res.statusText || "Failed to load project");
      }
      const data = await res.json();
      setProject(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load project");
      setProject(null);
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    fetchProject();
  }, [fetchProject]);

  async function handleRunAiDevelopment() {
    setRunLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/projects/${id}/runs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ agent_key: "ai_development" }),
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.detail || res.statusText || "Failed to start run");
      }
      const data = await res.json();
      router.push(`/runs/${data.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to start run");
    } finally {
      setRunLoading(false);
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
        <a href="/projects/new" className="mt-2 inline-block text-blue-600 underline text-sm">
          New project
        </a>
      </main>
    );
  }

  return (
    <main className="p-6 max-w-2xl">
      <a href="/projects/new" className="text-blue-600 underline text-sm">
        Back
      </a>
      <h1 className="text-xl font-semibold mt-4">{project.title}</h1>
      <dl className="mt-4 space-y-2 text-sm">
        <div>
          <dt className="text-gray-500">Idea</dt>
          <dd className="mt-1 text-gray-900 whitespace-pre-wrap">{project.idea}</dd>
        </div>
        {project.github_repo_url && (
          <div>
            <dt className="text-gray-500">Repo</dt>
            <dd>
              <a href={project.github_repo_url} target="_blank" rel="noopener noreferrer" className="text-blue-600 underline">
                {project.github_repo_url}
              </a>
            </dd>
          </div>
        )}
      </dl>
      <div className="mt-6">
        <button
          type="button"
          onClick={handleRunAiDevelopment}
          disabled={runLoading}
          className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {runLoading ? "Starting…" : "Run AI Development"}
        </button>
      </div>
    </main>
  );
}
