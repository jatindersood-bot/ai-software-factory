// packages/agents/contracts.ts

export type ArtifactType =
  | "PRD"
  | "BRD"
  | "ADR"
  | "ARCH_DIAGRAM_MERMAID"
  | "DEV_PLAN"
  | "TEST_PLAN"
  | "TEST_CASES"
  | "TEST_REPORT";

export type Artifact = {
  type: ArtifactType;
  title: string;
  version: string; // e.g. "v1"
  requirementIds?: string[]; // e.g. ["REQ-001", "REQ-002"]
  contentMarkdown: string; // the actual artifact text
};

export type AgentResult = {
  ok: boolean;
  reason?: string; // for gating failures
  artifacts: Artifact[];
  assumptions?: string[];
  openQuestions?: string[];
};

/**
 * Hard gate checks to stop generic "chatty" output.
 * Fail fast so the UI can require approval or re-run with feedback.
 */
export function gatePM(prd: Artifact): { ok: boolean; reason?: string } {
  const txt = prd.contentMarkdown;

  const hasUserStories = /User stories/i.test(txt);
  const storyCount = (txt.match(/As a\b/gi) || []).length;

  const hasAcceptance = /Acceptance criteria/i.test(txt) || /AC-/i.test(txt);

  const frCount = (txt.match(/\bFR-\d{3}\b/g) || []).length;
  const nfrCount = (txt.match(/\bNFR-\d{3}\b/g) || []).length;

  if (!hasUserStories || storyCount < 8) {
    return { ok: false, reason: `PRD rejected: needs >= 8 user stories (found ${storyCount}).` };
  }
  if (!hasAcceptance) {
    return { ok: false, reason: `PRD rejected: missing acceptance criteria.` };
  }
  if (frCount + nfrCount < 10) {
    return { ok: false, reason: `PRD rejected: needs >= 10 FR/NFR total (found ${frCount + nfrCount}).` };
  }
  return { ok: true };
}

export function gateBA(brd: Artifact): { ok: boolean; reason?: string } {
  const txt = brd.contentMarkdown;

  const reqIds = txt.match(/\bREQ-\d{3}\b/g) || [];
  const uniqueReqIds = Array.from(new Set(reqIds));

  const hasTraceability = /Traceability/i.test(txt) && /REQ-\d{3}/.test(txt);

  if (uniqueReqIds.length < 12) {
    return { ok: false, reason: `BRD rejected: needs >= 12 requirement IDs REQ-xxx (found ${uniqueReqIds.length}).` };
  }
  if (!hasTraceability) {
    return { ok: false, reason: `BRD rejected: missing Traceability Matrix mapping stories → requirements.` };
  }
  return { ok: true };
}
