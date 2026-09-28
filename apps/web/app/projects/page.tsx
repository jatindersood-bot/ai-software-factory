"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Card } from "../components/Card";
import { Badge } from "../components/Badge";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ||
  process.env.NEXT_PUBLIC_API_URL ||
  "/api";

type Project = {
  id: number;
  title: string;
  idea: string;
  created_at: string;
  last_run_status: string | null;
};

export default function ProjectsIndexPage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("all");

  const fetchProjects = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/projects`);
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.detail || res.statusText || "Failed to load projects");
      }
      const data = await res.json();
      setProjects(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load projects");
      setProjects([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchProjects();
  }, [fetchProjects]);

  const filtered = projects.filter((p) => {
    const matchSearch =
      !search.trim() ||
      p.title.toLowerCase().includes(search.toLowerCase()) ||
      p.idea.toLowerCase().includes(search.toLowerCase());
    const matchStatus =
      statusFilter === "all" ||
      (statusFilter === "completed" && p.last_run_status === "completed") ||
      (statusFilter === "failed" && p.last_run_status === "failed") ||
      (statusFilter === "pending" &&
        p.last_run_status !== "completed" &&
        p.last_run_status !== "failed" &&
        p.last_run_status != null);
    return matchSearch && matchStatus;
  });

  if (loading) {
    return (
      <main className="p-6">
        <p className="text-gray-600">Loading projects…</p>
      </main>
    );
  }

  if (error) {
    return (
      <main className="p-6">
        <p className="text-red-600">{error}</p>
        <Link
          href="/projects/new"
          className="mt-2 inline-block text-blue-600 underline text-sm"
        >
          New Project
        </Link>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-gray-50">
      <div className="mx-auto max-w-4xl px-4 py-8">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <h1 className="text-2xl font-semibold text-gray-900">Projects</h1>
          <Link
            href="/projects/new"
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
          >
            New Project
          </Link>
        </div>

        <div className="mt-6 flex flex-wrap gap-3">
          <input
            type="text"
            placeholder="Search by title or idea..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="rounded border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="rounded border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          >
            <option value="all">All statuses</option>
            <option value="completed">Completed</option>
            <option value="failed">Failed</option>
            <option value="pending">Pending / Running</option>
          </select>
        </div>

        {filtered.length === 0 ? (
          <p className="mt-6 text-gray-500">No projects match.</p>
        ) : (
          <ul className="mt-6 space-y-3">
            {filtered.map((p) => (
              <li key={p.id}>
                <Card>
                  <div className="flex flex-wrap items-center justify-between gap-3 p-4">
                    <div className="min-w-0 flex-1">
                      <Link
                        href={`/projects/${p.id}`}
                        className="font-medium text-gray-900 hover:underline"
                      >
                        {p.title}
                      </Link>
                      <p className="mt-0.5 text-sm text-gray-500 line-clamp-2">
                        {p.idea}
                      </p>
                      <p className="mt-1 text-xs text-gray-400">
                        {new Date(p.created_at).toLocaleString()}
                      </p>
                    </div>
                    <div className="flex items-center gap-2">
                      {p.last_run_status != null ? (
                        <Badge
                          variant={
                            p.last_run_status === "completed"
                              ? "success"
                              : p.last_run_status === "failed"
                                ? "error"
                                : "info"
                          }
                        >
                          {p.last_run_status}
                        </Badge>
                      ) : (
                        <span className="text-xs text-gray-400">—</span>
                      )}
                      <Link
                        href={`/projects/${p.id}`}
                        className="text-sm font-medium text-blue-600 hover:underline"
                      >
                        Open
                      </Link>
                    </div>
                  </div>
                </Card>
              </li>
            ))}
          </ul>
        )}
      </div>
    </main>
  );
}
