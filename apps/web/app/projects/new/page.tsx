"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { Card } from "../../components/Card";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ||
  process.env.NEXT_PUBLIC_API_URL ||
  "/api";

type BriefPartial = Record<string, string>;

export default function NewProjectPage() {
  const router = useRouter();
  const [title, setTitle] = useState("");
  const [messages, setMessages] = useState<{ role: "user" | "assistant"; text: string }[]>([]);
  const [state, setState] = useState<{ step: number; brief_partial: BriefPartial } | null>(null);
  const [briefPartial, setBriefPartial] = useState<BriefPartial>({});
  const [done, setDone] = useState(false);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [submitLoading, setSubmitLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const sendMessage = useCallback(
    async (userMessage: string) => {
      setLoading(true);
      setError(null);
      try {
        const res = await fetch(`${API_BASE}/pm/chat`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            message: userMessage,
            state: state ?? undefined,
          }),
        });
        if (!res.ok) {
          const d = await res.json().catch(() => ({}));
          throw new Error(d.detail || res.statusText || "Chat request failed");
        }
        const data = await res.json();
        setState(data.state);
        setBriefPartial(data.brief_partial || {});
        setDone(data.done === true);
        setMessages((prev) => {
          const next = [...prev];
          if (userMessage) next.push({ role: "user", text: userMessage });
          next.push({ role: "assistant", text: data.assistant_message });
          return next;
        });
      } catch (e) {
        setError(e instanceof Error ? e.message : "Chat failed");
      } finally {
        setLoading(false);
      }
    },
    [state]
  );

  useEffect(() => {
    if (messages.length === 0 && !loading) {
      sendMessage("");
    }
  }, []);

  const handleSend = (e: React.FormEvent) => {
    e.preventDefault();
    const text = input.trim();
    if (!text || loading) return;
    setMessages((prev) => [...prev, { role: "user", text }]);
    setInput("");
    sendMessage(text);
  };

  const handleSubmitBrief = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim()) {
      setError("Enter a project title.");
      return;
    }
    setSubmitLoading(true);
    setError(null);
    try {
      const ideaSummary =
        briefPartial.problem_statement ||
        Object.values(briefPartial).slice(0, 2).join(" ") ||
        "Project from PM chat.";
      const res = await fetch(`${API_BASE}/projects`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: title.trim(),
          idea: ideaSummary.slice(0, 2000),
          idea_json: briefPartial,
        }),
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        const msg = Array.isArray(d.detail) ? d.detail.map((x: { msg?: string }) => x.msg).join(", ") : (d.detail || res.statusText);
        throw new Error(msg || "Failed to create project");
      }
      const data = await res.json();
      router.push(`/projects/${data.id}`);
    } catch (e) {
      const message = e instanceof Error ? e.message : "Failed to create project";
      if (message === "Failed to fetch" || (e instanceof TypeError && message.includes("fetch"))) {
        setError("Could not reach the API. Make sure the API is running (e.g. uvicorn on port 8000) and try again.");
      } else {
        setError(message);
      }
    } finally {
      setSubmitLoading(false);
    }
  };

  const fieldLabels: Record<string, string> = {
    problem_statement: "Problem statement",
    target_users: "Target users",
    core_features: "Core features",
    non_goals: "Non-goals",
    success_metrics: "Success metrics",
    constraints: "Constraints",
    integration_needs: "Integration needs",
    data_privacy: "Data / privacy",
    ui_expectations: "UI expectations",
    milestones: "Milestones",
    acceptance_criteria: "Acceptance criteria",
  };

  return (
    <main className="min-h-screen bg-gray-50">
      <div className="mx-auto max-w-2xl px-4 py-8">
        <h1 className="text-2xl font-semibold text-gray-900">New project</h1>
        <p className="mt-1 text-gray-600">
          The Product Manager will ask a few questions to build your project brief.
        </p>

        <div className="mt-6">
          <label className="block text-sm font-medium text-gray-700">
            Project title
          </label>
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="e.g. Customer dashboard"
            className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
        </div>

        <Card className="mt-6">
          <div className="max-h-96 space-y-3 overflow-y-auto p-4">
            {messages.map((m, i) => (
              <div
                key={i}
                className={
                  m.role === "user"
                    ? "ml-8 text-right"
                    : "mr-8 rounded-lg bg-gray-100 px-3 py-2 text-left text-gray-800"
                }
              >
                {m.text}
              </div>
            ))}
            {loading && (
              <div className="mr-8 rounded-lg bg-gray-100 px-3 py-2 text-gray-600">
                …
              </div>
            )}
          </div>
          {!done && (
            <form onSubmit={handleSend} className="flex gap-2 border-t border-gray-100 p-4">
              <input
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="Your answer..."
                disabled={loading}
                className="flex-1 rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:opacity-50"
              />
              <button
                type="submit"
                disabled={loading || !input.trim()}
                className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
              >
                Send
              </button>
            </form>
          )}
        </Card>

        {done && Object.keys(briefPartial).length > 0 && (
          <Card className="mt-6">
            <div className="border-b border-gray-100 px-4 py-3 font-medium text-gray-900">
              Review your brief
            </div>
            <div className="space-y-3 p-4">
              {Object.entries(briefPartial).map(([key, value]) => (
                <div key={key}>
                  <label className="block text-xs font-medium text-gray-500">
                    {fieldLabels[key] || key}
                  </label>
                  <textarea
                    value={value}
                    onChange={(e) =>
                      setBriefPartial((prev) => ({ ...prev, [key]: e.target.value }))
                    }
                    rows={2}
                    className="mt-0.5 w-full rounded border border-gray-200 px-2 py-1.5 text-sm"
                  />
                </div>
              ))}
            </div>
            <form onSubmit={handleSubmitBrief} className="border-t border-gray-100 p-4">
              {error && (
                <p className="mb-2 text-sm text-red-600">{error}</p>
              )}
              <button
                type="submit"
                disabled={submitLoading || !title.trim()}
                className="rounded bg-green-600 px-4 py-2 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-50"
              >
                {submitLoading ? "Creating…" : "Submit"}
              </button>
            </form>
          </Card>
        )}
      </div>
    </main>
  );
}
