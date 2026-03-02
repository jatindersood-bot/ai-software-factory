"""RQ worker: process runs by calling agent and writing artifacts."""

import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.models import Base, Project, Run, Artifact
from app.agents import run_agent

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg2://app:app@localhost:5432/factory")
ARTIFACTS_DIR = Path(os.getenv("ARTIFACTS_DIR", "./artifacts")).resolve()

AGENT_ARTIFACT_FILENAMES: dict[str, str] = {
    "idea_clarifier": "idea_clarification.md",
    "prd": "prd.md",
    "architecture": "architecture.md",
}

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def process_run(run_id: int) -> None:
    """Load run, call agent, write markdown to ARTIFACTS_DIR, create Artifact rows, update Run."""
    session = SessionLocal()
    try:
        run = session.get(Run, run_id)
        if not run:
            raise ValueError(f"Run {run_id} not found")
        if run.status != "queued":
            return

        run.status = "running"
        session.commit()

        project = session.get(Project, run.project_id)
        if not project:
            run.status = "failed"
            run.output_json = {"error": "Project not found"}
            session.commit()
            return

        try:
            input_json = dict(run.input_json or {})
            input_json.setdefault("project_id", run.project_id)
            markdown = run_agent(
                run.agent_key,
                project.title,
                project.idea,
                input_json,
            )
        except Exception as e:
            run.status = "failed"
            run.output_json = {"error": str(e)}
            session.commit()
            return

        # Write artifact file: ARTIFACTS_DIR / {project_id} / {run_id} / <descriptive>.md
        rel_dir = f"{run.project_id}/{run.id}"
        dir_path = ARTIFACTS_DIR / rel_dir
        dir_path.mkdir(parents=True, exist_ok=True)
        filename = AGENT_ARTIFACT_FILENAMES.get(run.agent_key, "output.md")
        file_path = dir_path / filename
        file_path.write_text(markdown, encoding="utf-8")

        rel_path = f"{rel_dir}/{filename}"

        artifact = Artifact(run_id=run.id, project_id=run.project_id, path=rel_path)
        session.add(artifact)
        session.flush()
        run.status = "completed"
        run.output_json = {"artifact_id": artifact.id, "path": rel_path}
        session.commit()
    finally:
        session.close()
