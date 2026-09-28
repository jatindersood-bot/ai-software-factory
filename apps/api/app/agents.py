"""Agent implementations. Each returns markdown content or structured output."""

import json
import os
from pathlib import Path
from typing import Any, Dict

from pydantic import ValidationError

from app.llm import llm_json
from app.schemas_codegen import CodegenResponse

AGENT_KEYS = [
    "idea_clarifier",
    "prd",
    "architecture",
    "business_analyst",
    "architect",
    "ai_development",
    "tester",
    "apply_workspace",
    "smoke_check",
    "open_pr",
    "preview_start",
    "ship",
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


def _get_idea_clarifier_system_prompt() -> str:
    """Load system prompt for idea_clarifier from template file if present."""
    return load_prompt_template("idea_clarification.md")


def idea_clarifier(project_title: str, project_idea: str, input_json: dict | None) -> dict:
    """Clarify the project idea using LLM JSON and render markdown without placeholders."""
    context_md = ""
    if input_json:
        ctx = input_json.get("context_markdown")
        if isinstance(ctx, str) and ctx.strip():
            context_md = ctx.strip()

    system = _get_idea_clarifier_system_prompt()
    user_parts = [f"Project Title: {project_title}", "", "Raw idea:", project_idea or ""]
    if context_md:
        user_parts += ["", "Upstream context (for reference):", context_md]
    user = "\n".join(user_parts).strip()

    data, meta = llm_json(system, user)

    title = (data.get("title") or project_title or "").strip()
    goal = (data.get("goal") or "").strip()
    out_of_scope = data.get("out_of_scope") or []
    if not isinstance(out_of_scope, list):
        out_of_scope = [str(out_of_scope)]
    success_criteria = data.get("success_criteria") or []
    if not isinstance(success_criteria, list):
        success_criteria = [str(success_criteria)]
    assumptions = data.get("assumptions") or []
    if not isinstance(assumptions, list):
        assumptions = [str(assumptions)]
    open_questions = data.get("open_questions") or []
    if not isinstance(open_questions, list):
        open_questions = [str(open_questions)]

    def _bullets(items: list[str]) -> str:
        return "\n".join(f"- {str(it).strip()}" for it in items if str(it).strip()) or "- (none)"

    md_lines = [
        f"# Idea clarification: {title or project_title}",
        "",
        "## Raw idea",
        project_idea or "",
        "",
        "## Clarified one-sentence goal",
        goal or "(goal not provided)",
        "",
        "## Users & context",
        "- Primary user: (to be detailed in BA stage)",
        "- User goal: (to be detailed in BA stage)",
        "- Where used (web/mobile/internal): (to be detailed in BA stage)",
        "- Frequency: (to be detailed in BA stage)",
        "",
        "## MVP scope (what we WILL build)",
        _bullets(data.get("mvp_scope") or []),
        "",
        "## Out of scope (NOT in MVP)",
        _bullets(out_of_scope),
        "",
        "## Data & integrations",
        "- Data stored: (to be detailed in architecture/BA stages)",
        "- External APIs: (to be detailed in architecture/BA stages)",
        "- Auth needed (yes/no): (to be detailed in architecture/BA stages)",
        "",
        "## UX notes",
        "- Pages/screens: (to be detailed in downstream stages)",
        "- Key UI components: (to be detailed in downstream stages)",
        "- Error states: (to be detailed in downstream stages)",
        "",
        "## Success criteria (definition of done)",
        _bullets(success_criteria),
        "",
        "## Assumptions",
        _bullets(assumptions),
    ]
    if open_questions:
        md_lines += [
            "",
            "## Open questions",
            _bullets(open_questions),
        ]

    if context_md:
        md_lines += [
            "",
            "## Context",
            context_md,
        ]

    markdown = "\n".join(md_lines).rstrip() + "\n"

    idea_json = {
        "title": title,
        "raw_idea": project_idea or "",
        "goal": goal,
        "out_of_scope": out_of_scope,
        "success_criteria": success_criteria,
        "assumptions": assumptions,
        "open_questions": open_questions,
    }

    return {
        "summary": goal or f"Clarified idea for {project_title}",
        "markdown": markdown,
        "output_json": idea_json,
        "artifacts": {
            "idea_clarification.md": markdown,
            "IDEA.json": json.dumps(idea_json, indent=2),
            "LLM_META.json": json.dumps(meta or {}, indent=2, default=str),
        },
    }


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

    context_md = ""
    if input_json:
        ctx = input_json.get("context_markdown")
        if isinstance(ctx, str) and ctx.strip():
            context_md = ctx.strip()
    context_block = f"\n\n## Context\n{context_md}\n" if context_md else ""

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
{context_block}
"""


def architecture(project_title: str, project_idea: str, input_json: dict | None) -> str:
    """Produce an architecture document."""
    context_md = ""
    if input_json:
        ctx = input_json.get("context_markdown")
        if isinstance(ctx, str) and ctx.strip():
            context_md = ctx.strip()
    context_block = f"\n\n## Upstream context\n{context_md}\n" if context_md else ""

    return f"""# Architecture: {project_title}

## Context
{project_idea}

## High-level design
- **Components**: API, worker, storage.
- **Data flow**: Request → API → Queue → Worker → Artifacts.

## Technology choices
- Backend: FastAPI, Postgres, Redis RQ.
- Artifacts: File system under ARTIFACTS_DIR.
{context_block}
"""


def business_analyst(project_title: str, project_idea: str, input_json: dict | None) -> dict:
    """Produce requirements, user stories, and acceptance criteria (stub)."""
    context_md = ""
    if input_json:
        ctx = input_json.get("context_markdown")
        if isinstance(ctx, str) and ctx.strip():
            context_md = ctx.strip()
    context_block = f"\n\n## Context\n{context_md}\n" if context_md else ""

    req = (
        f"# Requirements: {project_title}\n\n"
        f"## Overview\n{project_idea}\n"
        f"{context_block}\n"
        "## Functional\n- (To be expanded by BA agent)\n\n"
        "## Non-functional\n- (To be expanded)\n"
    )
    return {
        "summary": f"Business analysis for {project_title}",
        "markdown": req,
        "artifacts": {
            "REQUIREMENTS.md": req,
            "USER_STORIES.md": f"# User Stories: {project_title}\n\n## Stories\n1. As a user, I want to ... so that ...\n2. (To be expanded)\n",
            "ACCEPTANCE_CRITERIA.md": f"# Acceptance Criteria: {project_title}\n\n- [ ] Criterion 1\n- [ ] Criterion 2\n",
        },
    }


def architect(project_title: str, project_idea: str, input_json: dict | None) -> dict:
    """Produce architecture, API contract, and DB schema (stub)."""
    context_md = ""
    if input_json:
        ctx = input_json.get("context_markdown")
        if isinstance(ctx, str) and ctx.strip():
            context_md = ctx.strip()
    context_block = f"\n\n## Upstream context\n{context_md}\n" if context_md else ""

    arch = (
        f"# Architecture: {project_title}\n\n"
        f"## Context\n{project_idea}\n"
        f"{context_block}\n"
        "## Components\n- API, worker, storage.\n"
    )
    return {
        "summary": f"Architecture for {project_title}",
        "markdown": arch,
        "artifacts": {
            "ARCHITECTURE.md": arch,
            "API_CONTRACT.md": f"# API Contract: {project_title}\n\n## Endpoints\n- GET /health\n- (To be expanded)\n",
            "DB_SCHEMA.md": f"# DB Schema: {project_title}\n\n## Tables\n- (To be expanded)\n",
        },
    }


def tester(project_title: str, project_idea: str, input_json: dict | None) -> dict:
    """Produce test plan (stub)."""
    context_md = ""
    if input_json:
        ctx = input_json.get("context_markdown")
        if isinstance(ctx, str) and ctx.strip():
            context_md = ctx.strip()
    context_block = f"\n\n## Upstream context\n{context_md}\n" if context_md else ""

    plan = (
        f"# Test Plan: {project_title}\n\n"
        f"## Scope\n{project_idea}\n"
        f"{context_block}\n"
        "## Test cases\n1. (To be expanded)\n2. (To be expanded)\n"
    )
    return {
        "summary": f"Test plan for {project_title}",
        "markdown": plan,
        "artifacts": {
            "TEST_PLAN.md": plan,
        },
    }


CODEGEN_SCHEMA_VERSION = "v1"

SCHEMA_HINT = """{
  "summary": "string",
  "implementation_plan_md": "markdown string",
  "tree_md": "markdown string",
  "files": [{"path": "relative/path.ext", "content": "full file content"}]
}"""


def load_prompt_template(name: str) -> str:
    """Load prompt template from app/prompts/{name}. Returns fallback text if file missing."""
    try:
        prompt_path = Path(__file__).resolve().parent / "prompts" / name
        if prompt_path.is_file():
            return prompt_path.read_text(encoding="utf-8").strip()
    except Exception:
        pass
    return "You are a software architect and developer. Produce STRICT JSON only with: summary, implementation_plan_md, tree_md, and files (list of {path, content}). Paths relative. Keep implementation minimal and runnable."


def _get_ai_development_system_prompt() -> str:
    """Load system prompt from template file if present."""
    return load_prompt_template("ai_development.md")


def ai_development(
    project_title: str,
    project_idea: str,
    input_json: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """
    1. Build prompts.
    2. Call llm_json(system, user) to get dict + meta.
    3. Validate with CodegenResponse.model_validate(data); on failure attach last_raw and re-raise.
    4. Store llm_meta, file_count, schema_version in output_json; return artifacts + files.
    """
    # 1) Build prompts
    system = _get_ai_development_system_prompt()
    system = f"{system}\n\nSchema hint (prefer this shape):\n{SCHEMA_HINT}"

    tech_prefs_line = ""
    if input_json:
        prefs = input_json.get("tech_prefs") or input_json.get("technology_preferences")
        if isinstance(prefs, str):
            tech_prefs_line = f"\nTechnology preferences:\n{prefs}\n"
        elif isinstance(prefs, dict):
            tech_prefs_line = f"\nTechnology preferences:\n{json.dumps(prefs, indent=2)}\n"
        elif isinstance(prefs, list):
            tech_prefs_line = "\nTechnology preferences:\n" + "\n".join(str(p) for p in prefs) + "\n"

    user = f"""
Project Title: {project_title}

Project Idea:
{project_idea}
{tech_prefs_line}If any tech preference is provided in input_json, follow it.
Keep the implementation minimal and runnable.
""".strip()

    data, meta = llm_json(system, user)

    try:
        parsed = CodegenResponse.model_validate(data)
    except ValidationError as e:
        e.last_raw = json.dumps(data, indent=2)
        raise

    # Build output_json; return artifacts including LLM_META.json
    paths_only = [f.path for f in parsed.files]
    files_payload = [{"path": f.path, "content": f.content} for f in parsed.files]

    return {
        "output_json": {
            "summary": parsed.summary,
            "implementation_plan_md": parsed.implementation_plan_md,
            "tree_md": parsed.tree_md,
            "llm_meta": meta,
            "file_count": len(parsed.files),
            "schema_version": CODEGEN_SCHEMA_VERSION,
        },
        "artifacts": {
            "IMPLEMENTATION_PLAN.md": parsed.implementation_plan_md,
            "TREE.md": parsed.tree_md,
            "FILES_INDEX.json": json.dumps({"paths": paths_only}, indent=2),
            "LLM_META.json": json.dumps(meta or {}, indent=2, default=str),
        },
        "files": files_payload,
    }


def run_agent(agent_key: str, project_title: str, project_idea: str, input_json: dict | None) -> str | Dict[str, Any]:
    """Dispatch to the correct agent and return markdown or dict."""
    if agent_key == "idea_clarifier":
        return idea_clarifier(project_title, project_idea, input_json)
    if agent_key == "prd":
        return prd(project_title, project_idea, input_json)
    if agent_key == "architecture":
        return architecture(project_title, project_idea, input_json)
    if agent_key == "business_analyst":
        return business_analyst(project_title, project_idea, input_json)
    if agent_key == "architect":
        return architect(project_title, project_idea, input_json)
    if agent_key == "tester":
        return tester(project_title, project_idea, input_json)
    if agent_key == "ai_development":
        return ai_development(project_title, project_idea, input_json)
    raise ValueError(f"Unknown agent_key: {agent_key}")
