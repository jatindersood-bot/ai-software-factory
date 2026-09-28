"use client";

import { useCallback, useEffect, useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || process.env.NEXT_PUBLIC_API_URL || "/api";

const PREVIEW_EXT = [".md", ".patch", ".json", ".txt", ".py", ".ts", ".tsx", ".js", ".jsx", ".jsonl"];

function canPreview(path: string): boolean {
  const lower = path.toLowerCase();
  return PREVIEW_EXT.some((ext) => lower.endsWith(ext));
}

type ArtifactModalProps = {
  artifactId: number | null;
  path: string;
  onClose: () => void;
};

export default function ArtifactModal({ artifactId, path, onClose }: ArtifactModalProps) {
  const [content, setContent] = useState<string | null | "loading">("loading");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (artifactId == null) return;
    setContent("loading");
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/artifacts/${artifactId}/content`);
      if (!res.ok) throw new Error("Failed to load");
      const data = await res.json();
      setContent(data.content ?? "");
    } catch {
      setError("Failed to load content");
      setContent(null);
    }
  }, [artifactId]);

  useEffect(() => {
    if (artifactId != null) load();
  }, [artifactId, load]);

  if (artifactId == null) return null;

  const showPreview = canPreview(path);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-labelledby="artifact-modal-title"
    >
      <div
        className="bg-white rounded-lg shadow-xl max-w-4xl w-full max-h-[85vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200">
          <h2 id="artifact-modal-title" className="text-sm font-medium text-gray-900 truncate">
            {path}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="ml-2 px-3 py-1 rounded text-sm bg-gray-100 hover:bg-gray-200"
          >
            Close
          </button>
        </div>
        <div className="flex-1 overflow-auto p-4 min-h-0">
          {!showPreview && (
            <p className="text-gray-500 text-sm mb-2">
              Preview not available for this file type. Content may still load as text.
            </p>
          )}
          {content === "loading" && (
            <p className="text-gray-500">Loading…</p>
          )}
          {error && (
            <p className="text-red-600 text-sm">{error}</p>
          )}
          {content !== "loading" && content != null && !error && (
            <pre className="p-3 rounded bg-gray-100 text-sm overflow-x-auto overflow-y-auto max-h-[70vh] whitespace-pre-wrap font-mono">
              {content}
            </pre>
          )}
        </div>
      </div>
    </div>
  );
}
