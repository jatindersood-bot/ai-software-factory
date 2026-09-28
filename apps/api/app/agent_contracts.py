"""
Shared artifact contract: validate AgentResult and apply PM/BA gates.
Mirrors packages/agents/contracts.ts and runAgent.ts for use in Python worker.
"""

import re
from typing import Any


def gate_pm(prd: dict) -> tuple[bool, str | None]:
    """Hard gate on PRD: >= 8 user stories, acceptance criteria, >= 10 FR/NFR total."""
    content = (prd.get("contentMarkdown") or "") if isinstance(prd, dict) else ""
    txt = content if isinstance(content, str) else ""

    has_user_stories = bool(re.search(r"User stories", txt, re.I))
    story_count = len(re.findall(r"As a\b", txt, re.I))

    has_acceptance = bool(re.search(r"Acceptance criteria", txt, re.I)) or bool(re.search(r"AC-", txt, re.I))

    fr_count = len(re.findall(r"\bFR-\d{3}\b", txt))
    nfr_count = len(re.findall(r"\bNFR-\d{3}\b", txt))

    if not has_user_stories or story_count < 8:
        return False, f"PRD rejected: needs >= 8 user stories (found {story_count})."
    if not has_acceptance:
        return False, "PRD rejected: missing acceptance criteria."
    if fr_count + nfr_count < 10:
        return False, f"PRD rejected: needs >= 10 FR/NFR total (found {fr_count + nfr_count})."
    return True, None


def gate_ba(brd: dict) -> tuple[bool, str | None]:
    """Hard gate on BRD: >= 12 REQ-xxx, Traceability Matrix."""
    content = (brd.get("contentMarkdown") or "") if isinstance(brd, dict) else ""
    txt = content if isinstance(content, str) else ""

    req_ids = re.findall(r"\bREQ-\d{3}\b", txt)
    unique_req_ids = list(dict.fromkeys(req_ids))

    has_traceability = bool(re.search(r"Traceability", txt, re.I)) and bool(re.search(r"REQ-\d{3}", txt))

    if len(unique_req_ids) < 12:
        return False, f"BRD rejected: needs >= 12 requirement IDs REQ-xxx (found {len(unique_req_ids)})."
    if not has_traceability:
        return False, "BRD rejected: missing Traceability Matrix mapping stories → requirements."
    return True, None


def validate_agent_result(result: Any) -> tuple[bool, str | None, list[dict] | None]:
    """
    Validate AgentResult shape. Returns (ok, reason, artifacts).
    If ok is True, artifacts is the list of artifact dicts; else reason is set.
    """
    if result is None or not isinstance(result, dict):
        return False, "Agent returned empty result", None
    artifacts = result.get("artifacts")
    if not isinstance(artifacts, list) or len(artifacts) == 0:
        return False, "Agent returned no artifacts", None
    return True, None, artifacts


def apply_gates(artifacts: list[dict]) -> tuple[bool, str | None]:
    """
    Apply PM gate to PRD artifact and BA gate to BRD artifact.
    Returns (ok, reason). If ok is False, reason is the gate failure message.
    """
    prd = next((a for a in artifacts if isinstance(a, dict) and a.get("type") == "PRD"), None)
    brd = next((a for a in artifacts if isinstance(a, dict) and a.get("type") == "BRD"), None)

    if prd is not None:
        ok, reason = gate_pm(prd)
        if not ok:
            return False, reason
    if brd is not None:
        ok, reason = gate_ba(brd)
        if not ok:
            return False, reason
    return True, None
