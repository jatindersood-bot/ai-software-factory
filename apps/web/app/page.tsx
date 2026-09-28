"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Card } from "./components/Card";
import { Badge } from "./components/Badge";

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

export default function HomePage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("all");

  const fetchProjects = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/projects`);
      if (!res.ok) throw new Error("Failed to load projects");
      const data = await res.json();
      setProjects(data);
    } catch {
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

  const recent = filtered.slice(0, 10);

  return (
    <main className="min-h-screen bg-gray-50">
      <div className="mx-auto max-w-4xl px-4 py-10">
        <h1 className="text-3xl font-bold text-gray-900">
          AI Software Factory
        </h1>
        <p className="mt-2 text-gray-600">
          Define your product, run the pipeline, and ship to GitHub.
        </p>

        <div className="mt-8 flex flex-wrap gap-4">
          <Link
            href="/projects/new"
            className="inline-flex items-center rounded-lg bg-blue-600 px-6 py-3 text-base font-medium text-white shadow hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
          >
            Start new
          </Link>
          <Link
            href="/projects"
            className="inline-flex items-center rounded-lg border border-gray-300 bg-white px-6 py-3 text-base font-medium text-gray-700 shadow-sm hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-gray-500 focus:ring-offset-2"
          >
            View projects
          </Link>
        </div>

        <section className="mt-10">
          <h2 className="text-lg font-semibold text-gray-900">
            Recent projects
          </h2>
          <div className="mt-3 flex flex-wrap gap-3">
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

          {loading ? (
            <p className="mt-4 text-gray-500">Loading…</p>
          ) : recent.length === 0 ? (
            <p className="mt-4 text-gray-500">
              No projects yet. Click &quot;Start new&quot; to create one.
            </p>
          ) : (
            <ul className="mt-4 space-y-3">
              {recent.map((p) => (
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
                        <p className="mt-0.5 truncate text-sm text-gray-500">
                          {new Date(p.created_at).toLocaleDateString()}
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
        </section>
      </div>
    </main>
  );
}
