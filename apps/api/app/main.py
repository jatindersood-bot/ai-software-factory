"""FastAPI application: AI software factory API."""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from github.GithubException import GithubException
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

ARTIFACTS_DIR = Path(os.getenv("ARTIFACTS_DIR", "./artifacts")).resolve()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="AI Software Factory API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _run_response(run: Run, include_artifacts: bool = True) -> RunResponse:
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
    )


# --- Projects ---
@app.post("/projects", response_model=ProjectResponse)
def create_project(data: ProjectCreate):
    with get_db() as db:
        project = Project(title=data.title, idea=data.idea)
        db.add(project)
        db.flush()
        db.refresh(project)
        return ProjectResponse.model_validate(project)


@app.get("/projects/{project_id}", response_model=ProjectResponse)
def get_project(project_id: int):
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
def get_project_timeline(project_id: int):
    with get_db() as db:
        project = db.get(Project, project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        runs = db.query(Run).filter(Run.project_id == project_id).order_by(Run.created_at.desc()).all()
        return [_run_response(r, include_artifacts=False) for r in runs]


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
        run = Run(project_id=project_id, agent_key=data.agent_key, status="queued", input_json={})
        db.add(run)
        db.flush()
        db.refresh(run)
        run_id = run.id
    # Enqueue outside of transaction
    from redis import Redis
    from rq import Queue

    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    queue = Queue(connection=Redis.from_url(redis_url))
    queue.enqueue("app.worker.process_run", run_id)
    with get_db() as db:
        run = db.get(Run, run_id)
        return _run_response(run)


@app.get("/runs/{run_id}", response_model=RunResponse)
def get_run(run_id: int):
    with get_db() as db:
        run = db.get(Run, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        return _run_response(run)


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
    queue.enqueue("app.worker.process_run", new_run_id)
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
        return {"content": full_path.read_text(encoding="utf-8")}
