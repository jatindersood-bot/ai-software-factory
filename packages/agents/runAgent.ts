// packages/agents/runAgent.ts
import { AgentResult, Artifact, gatePM, gateBA } from "./contracts";

export function safeJsonParse<T>(raw: string): { ok: true; value: T } | { ok: false; error: string } {
  try {
    const v = JSON.parse(raw);
    return { ok: true, value: v as T };
  } catch (e: unknown) {
    const err = e instanceof Error ? e.message : "Invalid JSON";
    return { ok: false, error: err };
  }
}

export function validateAgentResult(
  result: AgentResult
): { ok: boolean; reason?: string; artifacts?: Artifact[] } {
  if (!result || typeof result !== "object") return { ok: false, reason: "Agent returned empty result" };
  if (!Array.isArray(result.artifacts) || result.artifacts.length === 0) {
    return { ok: false, reason: "Agent returned no artifacts" };
  }
  return { ok: true, artifacts: result.artifacts };
}

export function applyGates(artifacts: Artifact[]): { ok: boolean; reason?: string } {
  const prd = artifacts.find((a) => a.type === "PRD");
  const brd = artifacts.find((a) => a.type === "BRD");

  if (prd) {
    const g = gatePM(prd);
    if (!g.ok) return g;
  }
  if (brd) {
    const g = gateBA(brd);
    if (!g.ok) return g;
  }

  return { ok: true };
}
