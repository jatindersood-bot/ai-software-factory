"""FastAPI application: AI software factory API."""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware

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


@app.get("/projects/{project_id}/timeline")
def get_project_timeline(project_id: int):
    with get_db() as db:
        project = db.get(Project, project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        runs = db.query(Run).filter(Run.project_id == project_id).order_by(Run.created_at.desc()).all()
        return [_run_response(r, include_artifacts=False) for r in runs]


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
