"""FastAPI application: AI software factory API."""

import json
import os
import signal
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from github.GithubException import GithubException
from pydantic import BaseModel
from sqlalchemy import select

from app.db import get_db, init_db
from app.models import Project, Run, Artifact, Approval
from app.schemas import (
    ProjectCreate,
    ProjectResponse,
    RunCreate,
    RunResponse,
    ApprovalCreate,
    ApprovalResponse,
    ArtifactResponse,
)
from app.agents import AGENT_KEYS
from app.github_client import ensure_repo, create_branch_from_default, upsert_file, open_pr
from app.pm_chat import pm_chat_turn
from app.worker import process_run

ARTIFACTS_DIR = Path(os.getenv("ARTIFACTS_DIR", "./artifacts")).resolve()

ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3001",
    "http://localhost:3100",
    "http://127.0.0.1:3100",
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="AI Software Factory API", lifespan=lifespan)

# Preview dev server runs on port 3001 (or 3100 + project_id for legacy)
ALLOW_ORIGIN_REGEX = r"http://(localhost|127\.0\.0\.1):(3000|3001|31\d{2})"

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_origin_regex=ALLOW_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    """Health check for preview and load balancers."""
    return {"status": "ok"}


@app.get("/greet")
@app.post("/greet")
def greet(name: str | None = None):
    """Simple greeting for frontend demo. GET/POST; optional query or JSON body name."""
    if name:
        return {"message": f"Hello, {name}!"}
    return {"message": "Hello!"}


class PersonalInfo(BaseModel):
    name: str
    email: str
    phone: str


@app.post("/submit")
def submit(info: PersonalInfo):
    return {"ok": True, "received": info.model_dump()}


class PMChatRequest(BaseModel):
    project_id: Optional[int] = None
    message: str = ""
    state: Optional[dict] = None


class PMChatResponse(BaseModel):
    assistant_message: str
    state: dict
    brief_partial: dict
    done: bool


@app.post("/pm/chat", response_model=PMChatResponse)
def pm_chat(req: PMChatRequest):
    """Product Manager chat: one question at a time; returns next question and updated state until done."""
    msg, state, brief_partial, done = pm_chat_turn(req.message or "", req.state)
    return PMChatResponse(
        assistant_message=msg,
        state=state,
        brief_partial=brief_partial,
        done=done,
    )


PIPELINE_STAGES = [
    {"agent_key": "idea_clarifier", "display_name": "Idea Clarifier", "depends_on": None},
    {"agent_key": "prd", "display_name": "Product Manager (PRD)", "depends_on": "idea_clarifier"},
    {"agent_key": "business_analyst", "display_name": "Business Analyst", "depends_on": "prd"},
    {"agent_key": "architect", "display_name": "Architect", "depends_on": "business_analyst"},
    {"agent_key": "ai_development", "display_name": "Developer", "depends_on": "architect"},
    {"agent_key": "tester", "display_name": "Tester", "depends_on": "ai_development"},
    {"agent_key": "apply_workspace", "display_name": "Apply to workspace", "depends_on": "ai_development"},
    {"agent_key": "smoke_check", "display_name": "Smoke check", "depends_on": "apply_workspace"},
    {"agent_key": "preview_start", "display_name": "Preview", "depends_on": "tester"},
    {"agent_key": "open_pr", "display_name": "Open PR", "depends_on": "apply_workspace"},
    {"agent_key": "ship", "display_name": "Ship", "depends_on": "apply_workspace"},
]


@app.get("/pipeline")
def get_pipeline():
    """Return ordered pipeline stages for UI."""
    return {"stages": PIPELINE_STAGES}


def _run_response(run: Run, include_artifacts: bool = True) -> RunResponse:
    approval_decision = None
    if run.approvals:
        latest = max(run.approvals, key=lambda a: a.created_at)
        approval_decision = latest.decision
    return RunResponse(
        id=run.id,
        project_id=run.project_id,
        agent_key=run.agent_key,
        status=run.status,
        parent_run_id=run.parent_run_id,
        input_json=run.input_json,
        output_json=run.output_json,
        created_at=run.created_at,
        artifacts=[ArtifactResponse.model_validate(a) for a in run.artifacts] if include_artifacts else [],
        approval_decision=approval_decision,
    )


# --- Projects ---
@app.get("/projects", response_model=list[ProjectResponse])
def list_projects():
    """List all projects. Returns id, title, created_at, last_run_status."""
    with get_db() as db:
        projects = db.query(Project).order_by(Project.created_at.desc()).all()
        result = []
        for project in projects:
            latest_run = (
                db.query(Run)
                .filter(Run.project_id == project.id)
                .order_by(Run.created_at.desc())
                .limit(1)
            ).first()
            data = ProjectResponse.model_validate(project).model_copy(
                update={"last_run_status": latest_run.status if latest_run else None}
            )
            result.append(data)
        return result


@app.post("/projects", response_model=ProjectResponse)
def create_project(data: ProjectCreate):
    with get_db() as db:
        project = Project(title=data.title, idea=data.idea, idea_json=data.idea_json)
        db.add(project)
        db.flush()
        db.refresh(project)
        return ProjectResponse.model_validate(project)


@app.get("/projects/{project_id}", response_model=ProjectResponse)
def get_project(project_id: int):
    """Project details. Returns id, title, created_at and other fields."""
    with get_db() as db:
        project = db.get(Project, project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        return ProjectResponse.model_validate(project)


@app.post("/projects/{project_id}/github/init", response_model=ProjectResponse)
def init_project_github(project_id: int):
    with get_db() as db:
        project = db.get(Project, project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        repo_name = f"factory-project-{project_id}"
        repo = ensure_repo(repo_name)

        project.github_owner = repo.owner.login
        project.github_repo = repo.name
        project.github_repo_url = repo.html_url
        project.github_default_branch = repo.default_branch

        db.flush()
        db.refresh(project)
        return ProjectResponse.model_validate(project)


@app.get("/projects/{project_id}/timeline")
def get_project_timeline(project_id: int, include_artifacts: bool = False):
    with get_db() as db:
        project = db.get(Project, project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        runs = db.query(Run).filter(Run.project_id == project_id).order_by(Run.created_at.desc()).all()
        return [_run_response(r, include_artifacts=include_artifacts) for r in runs]


@app.get("/projects/{project_id}/runs", response_model=list[RunResponse])
def get_project_runs(project_id: int, include_artifacts: bool = True):
    """List runs for a project (newest first). Returns id, status, created_at, artifacts."""
    with get_db() as db:
        project = db.get(Project, project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        runs = db.query(Run).filter(Run.project_id == project_id).order_by(Run.created_at.desc()).all()
        return [_run_response(r, include_artifacts=include_artifacts) for r in runs]


@app.post("/projects/{project_id}/github/pr/docs")
def create_docs_pr(project_id: int):
    with get_db() as db:
        project = db.get(Project, project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        repo_name = project.github_repo or f"factory-project-{project_id}"
        repo = ensure_repo(repo_name)

        default_branch = project.github_default_branch or repo.default_branch
        docs_branch = "docs/init"

        try:
            create_branch_from_default(repo, default_branch, docs_branch)
        except GithubException as e:
            # Ignore error if branch already exists
            if e.status != 422:
                raise

        # For each agent key, pick latest artifact by created_at (plain rows to avoid detached instances)
        agent_keys = ["idea_clarifier", "prd", "architecture"]
        artifacts_by_agent = {}
        for agent_key in agent_keys:
            row = db.execute(
                select(Artifact.id, Artifact.path)
                .join(Run, Artifact.run_id == Run.id)
                .where(Run.project_id == project_id, Run.agent_key == agent_key)
                .order_by(Artifact.created_at.desc())
                .limit(1)
            ).first()
            if row:
                artifacts_by_agent[agent_key] = {"id": row.id, "path": row.path}

    # Read artifact files and upsert into docs/*.md
    agent_to_path = {
        "idea_clarifier": "docs/idea_clarifier.md",
        "prd": "docs/prd.md",
        "architecture": "docs/architecture.md",
    }

    for agent_key, a in artifacts_by_agent.items():
        full_path = ARTIFACTS_DIR / a["path"]
        if not full_path.is_file():
            continue
        content = full_path.read_text(encoding="utf-8")
        target_path = agent_to_path[agent_key]
        message = f"Update {target_path} from {agent_key} artifact for project {project_id}"
        upsert_file(repo, docs_branch, target_path, content, message)

    pr_title = f"Add docs for project {project_id}"
    pr_body = f"Automatically generated documentation for project {project_id}."
    pr_url = open_pr(repo, pr_title, pr_body, head_branch=docs_branch, base_branch=default_branch)

    return {"pr_url": pr_url}


@app.post("/projects/{project_id}/runs", response_model=RunResponse)
def create_run(project_id: int, data: RunCreate):
    if data.agent_key not in AGENT_KEYS:
        raise HTTPException(status_code=400, detail=f"agent_key must be one of {list(AGENT_KEYS)}")
    with get_db() as db:
        project = db.get(Project, project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        run = Run(
            project_id=project_id,
            agent_key=data.agent_key,
            status="queued",
            input_json={},
            parent_run_id=data.parent_run_id,
        )
        db.add(run)
        db.flush()
        db.refresh(run)
        run_id = run.id
    # Enqueue outside of transaction
    from redis import Redis
    from rq import Queue

    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    queue = Queue(connection=Redis.from_url(redis_url))
    queue.enqueue(process_run, run_id)
    with get_db() as db:
        run = db.get(Run, run_id)
        return _run_response(run)


@app.get("/runs/{run_id}", response_model=RunResponse)
def get_run(run_id: int):
    """Run details. Returns id, status, created_at, artifacts and other fields."""
    with get_db() as db:
        run = db.get(Run, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        return _run_response(run)


@app.get("/runs/{run_id}/artifacts")
def get_run_artifacts(run_id: int):
    """List artifacts for a run. Also included in GET /runs/{run_id} by default."""
    with get_db() as db:
        run = db.get(Run, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        artifacts = db.query(Artifact).filter(Artifact.run_id == run_id).order_by(Artifact.created_at).all()
        return [ArtifactResponse.model_validate(a) for a in artifacts]


@app.post("/runs/{run_id}/apply_workspace", response_model=RunResponse)
def apply_workspace(run_id: int):
    """Create a new run that applies this run's generated code to the workspace. Enqueued for processing."""
    with get_db() as db:
        parent = db.get(Run, run_id)
        if not parent:
            raise HTTPException(status_code=404, detail="Run not found")
        run = Run(
            project_id=parent.project_id,
            agent_key="apply_workspace",
            status="queued",
            parent_run_id=run_id,
            input_json=parent.input_json,
        )
        db.add(run)
        db.flush()
        db.refresh(run)
        new_run_id = run.id
    from redis import Redis
    from rq import Queue

    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    queue = Queue(connection=Redis.from_url(redis_url))
    queue.enqueue(process_run, new_run_id)
    with get_db() as db:
        run = db.get(Run, new_run_id)
        return _run_response(run)


@app.post("/runs/{run_id}/open_pr", response_model=RunResponse)
def open_pr_run(run_id: int):
    """Create a new run that opens a PR from this run's workspace. Enqueued for processing."""
    with get_db() as db:
        parent = db.get(Run, run_id)
        if not parent:
            raise HTTPException(status_code=404, detail="Run not found")
        run = Run(
            project_id=parent.project_id,
            agent_key="open_pr",
            status="queued",
            parent_run_id=run_id,
            input_json=parent.input_json,
        )
        db.add(run)
        db.flush()
        db.refresh(run)
        new_run_id = run.id
    from redis import Redis
    from rq import Queue

    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    queue = Queue(connection=Redis.from_url(redis_url))
    queue.enqueue(process_run, new_run_id)
    with get_db() as db:
        run = db.get(Run, new_run_id)
        return _run_response(run)


@app.post("/runs/{run_id}/preview_start", response_model=RunResponse)
def preview_start(run_id: int):
    """Create a child run with agent_key preview_start and enqueue for processing. Returns the created run."""
    with get_db() as db:
        parent = db.get(Run, run_id)
        if not parent:
            raise HTTPException(status_code=404, detail="Run not found")
        run = Run(
            project_id=parent.project_id,
            agent_key="preview_start",
            status="queued",
            parent_run_id=run_id,
            input_json=parent.input_json,
        )
        db.add(run)
        db.flush()
        db.refresh(run)
        new_run_id = run.id
    from redis import Redis
    from rq import Queue

    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    queue = Queue(connection=Redis.from_url(redis_url))
    queue.enqueue(process_run, new_run_id)
    with get_db() as db:
        run = db.get(Run, new_run_id)
        return _run_response(run)


@app.post("/runs/{run_id}/preview_stop")
def preview_stop(run_id: int):
    """Read latest PREVIEW.json for this run or its child preview run, kill the saved PID, return status stopped."""
    with get_db() as db:
        run = db.get(Run, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        project_id = run.project_id
        if run.agent_key == "preview_start":
            preview_run_id = run.id
        else:
            child = (
                db.query(Run)
                .filter(Run.parent_run_id == run_id, Run.agent_key == "preview_start")
                .order_by(Run.id.desc())
                .limit(1)
            ).first()
            if not child:
                raise HTTPException(status_code=404, detail="No preview run found for this run")
            preview_run_id = child.id

    preview_path = ARTIFACTS_DIR / str(project_id) / str(preview_run_id) / "PREVIEW.json"
    if not preview_path.is_file():
        raise HTTPException(status_code=404, detail="PREVIEW.json not found")

    data = json.loads(preview_path.read_text(encoding="utf-8"))
    pid = data.get("pid") if isinstance(data, dict) else None
    if pid is not None:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except OSError:
            pass

    return {"status": "stopped"}


@app.post("/runs/{run_id}/approve", response_model=ApprovalResponse)
def approve_run(run_id: int, data: ApprovalCreate):
    with get_db() as db:
        run = db.get(Run, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        approval = Approval(run_id=run_id, decision=data.decision, feedback=data.feedback)
        db.add(approval)
        db.flush()
        db.refresh(approval)
        return ApprovalResponse.model_validate(approval)


@app.post("/runs/{run_id}/rerun", response_model=RunResponse)
def rerun(run_id: int, data: RunCreate):
    if data.agent_key not in AGENT_KEYS:
        raise HTTPException(status_code=400, detail=f"agent_key must be one of {list(AGENT_KEYS)}")
    with get_db() as db:
        parent = db.get(Run, run_id)
        if not parent:
            raise HTTPException(status_code=404, detail="Run not found")
        run = Run(
            project_id=parent.project_id,
            agent_key=data.agent_key,
            status="queued",
            parent_run_id=run_id,
            input_json=parent.input_json,
        )
        db.add(run)
        db.flush()
        db.refresh(run)
        new_run_id = run.id
    from redis import Redis
    from rq import Queue

    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    queue = Queue(connection=Redis.from_url(redis_url))
    queue.enqueue(process_run, new_run_id)
    with get_db() as db:
        run = db.get(Run, new_run_id)
        return _run_response(run)


@app.get("/projects/{project_id}/artifacts")
def get_project_artifacts(project_id: int):
    with get_db() as db:
        project = db.get(Project, project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        artifacts = db.query(Artifact).filter(Artifact.project_id == project_id).order_by(Artifact.created_at.desc()).all()
        return [ArtifactResponse.model_validate(a) for a in artifacts]


@app.get("/artifacts/{artifact_id}/content")
def get_artifact_content(artifact_id: int):
    with get_db() as db:
        artifact = db.get(Artifact, artifact_id)
        if not artifact:
            raise HTTPException(status_code=404, detail="Artifact not found")
        full_path = ARTIFACTS_DIR / artifact.path
        if not full_path.is_file():
            raise HTTPException(status_code=404, detail="Artifact file not found")
        return {"content": full_path.read_text(encoding="utf-8"), "path": artifact.path}
