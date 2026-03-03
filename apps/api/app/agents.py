"""Agent implementations. Each returns markdown content or structured output."""

import os
from pathlib import Path
from typing import Any, Dict

AGENT_KEYS = [
    "idea_clarifier",
    "prd",
    "architecture",
    "ai_development",
]

AI_DEVELOPMENT_CONFIG = {
    "summary": "...",
    "artifacts": [
        {"path": "IMPLEMENTATION_PLAN.md", "type": "markdown"},
        {"path": "CODEBASE_TREE.md", "type": "markdown"},
        {"path": "generated_code/README.md", "type": "text"},
    ],
    "proposed_actions": {
        "write_workspace": True,
        "open_github_pr": False,
    },
}

def _get_artifacts_dir() -> Path:
    # Compute at call-time so dotenv-loaded env vars are respected.
    return Path(os.getenv("ARTIFACTS_DIR", "./artifacts")).resolve()


def _extract_md_section(markdown: str, heading: str) -> str | None:
    lines = markdown.splitlines()
    try:
        start_idx = next(i for i, line in enumerate(lines) if line.strip() == heading)
    except StopIteration:
        return None

    body: list[str] = []
    for line in lines[start_idx + 1 :]:
        if line.startswith("## "):
            break
        body.append(line)
    content = "\n".join(body).strip()
    return content or None


def _try_load_latest_idea_clarification(project_id: int) -> tuple[int, str] | None:
    project_dir = _get_artifacts_dir() / str(project_id)
    if not project_dir.is_dir():
        return None

    run_dirs: list[tuple[int, Path]] = []
    for p in project_dir.iterdir():
        if not p.is_dir():
            continue
        try:
            run_id = int(p.name)
        except ValueError:
            continue
        run_dirs.append((run_id, p))

    for run_id, run_dir in sorted(run_dirs, key=lambda x: x[0], reverse=True):
        # Prefer the new descriptive filename, but fall back to the legacy one.
        for candidate in ("idea_clarification.md", "output.md"):
            md_path = run_dir / candidate
            if not md_path.is_file():
                continue
            try:
                content = md_path.read_text(encoding="utf-8")
            except Exception:
                continue
            if content.lstrip().startswith("# Idea clarification:"):
                return run_id, content

    return None


def idea_clarifier(project_title: str, project_idea: str, input_json: dict | None) -> str:
    """Clarify the project idea."""
    return f"""# Idea clarification: {project_title}

## Raw idea
{project_idea}

## Clarified scope (MVP)
- **Goal**: Refined one-sentence goal based on the idea.
- **Out of scope**: Items deferred for later.
- **Success criteria**: How we know the MVP is done.
"""


def prd(project_title: str, project_idea: str, input_json: dict | None) -> str:
    """Produce a PRD from the idea/clarification."""
    source_markdown = project_idea
    clarification_run_id: int | None = None

    project_id: int | None = None
    if input_json:
        raw_project_id = input_json.get("project_id")
        if isinstance(raw_project_id, int):
            project_id = raw_project_id
        elif isinstance(raw_project_id, str):
            try:
                project_id = int(raw_project_id)
            except ValueError:
                project_id = None

    if project_id is not None:
        clarification = _try_load_latest_idea_clarification(project_id)
        if clarification is not None:
            clarification_run_id, clarification_md = clarification
            clarified_scope = _extract_md_section(clarification_md, "## Clarified scope (MVP)")
            raw_idea = _extract_md_section(clarification_md, "## Raw idea")
            source_markdown = clarified_scope or raw_idea or clarification_md or project_idea

    return f"""# Product Requirements Document: {project_title}

## Overview
{source_markdown}

## Source
{"- Latest `idea_clarifier` artifact from the same project (run_id: " + str(clarification_run_id) + ")." if clarification_run_id is not None else "- No clarification found; using `project.idea`."}

## User stories
1. As a user, I want to ...
2. As a user, I want to ...

## Requirements
- Functional: ...
- Non-functional: ...

## Acceptance criteria
- [ ] Criterion 1
- [ ] Criterion 2
"""


def architecture(project_title: str, project_idea: str, input_json: dict | None) -> str:
    """Produce an architecture document."""
    return f"""# Architecture: {project_title}

## Context
{project_idea}

## High-level design
- **Components**: API, worker, storage.
- **Data flow**: Request → API → Queue → Worker → Artifacts.

## Technology choices
- Backend: FastAPI, Postgres, Redis RQ.
- Artifacts: File system under ARTIFACTS_DIR.
"""


def ai_development(project_title: str, project_idea: str, input_json: Dict[str, Any] | None = None) -> Dict[str, Any]:
    implementation_plan = f"""# Implementation Plan

## Project
- Title: {project_title}

## Backend
- FastAPI service
- Postgres models: Project, Run, Artifact, Approval
- Endpoints for Projects, Runs, Artifacts

## Frontend
- Next.js pages: project create, timeline, run inspector, artifacts browser

## Next steps
- Add workspace apply
- Add DIFF generation
- Add GitHub PR automation
"""

    codebase_tree = """# Codebase Tree (proposed)

generated_code/
  backend/
    app/
      main.py
  frontend/
    app/
      page.tsx
  README.md
"""

    # Minimal scaffold files (safe starter)
    files = {
        "README.md": f"# {project_title}\n\n{project_idea}\n",
        "backend/app/main.py": "from fastapi import FastAPI\n\napp = FastAPI()\n\n@app.get('/health')\ndef health():\n    return {'ok': True}\n",
        "frontend/app/page.tsx": "export default function Home(){return <main style={{padding:20}}>Hello AI Factory</main>}\n",
    }

    return {
        "summary": "Generated implementation plan + proposed scaffold files.",
        "artifacts": {
            "IMPLEMENTATION_PLAN.md": implementation_plan,
            "CODEBASE_TREE.md": codebase_tree,
        },
        "generated_files": files,
    }


def run_agent(agent_key: str, project_title: str, project_idea: str, input_json: dict | None) -> str | Dict[str, Any]:
    """Dispatch to the correct agent and return markdown."""
    if agent_key == "idea_clarifier":
        return idea_clarifier(project_title, project_idea, input_json)
    if agent_key == "prd":
        return prd(project_title, project_idea, input_json)
    if agent_key == "architecture":
        return architecture(project_title, project_idea, input_json)
    if agent_key == "ai_development":
        return ai_development(project_title, project_idea, input_json)
    raise ValueError(f"Unknown agent_key: {agent_key}")
