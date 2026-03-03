"""RQ worker: process runs by calling agent and writing artifacts."""

import json
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


def _write_text(path: str, content: str) -> None:
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def process_run(run_id: int) -> None:
    """Load run, call agent, write artifacts (including generated code), create Artifact rows, update Run."""
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
            agent_result = run_agent(
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

        result = agent_result
        artifact_dir = os.path.join(str(ARTIFACTS_DIR), str(run.project_id), str(run.id))
        os.makedirs(artifact_dir, exist_ok=True)

        # 1) Write normal artifacts (markdown)
        if isinstance(result, dict) and "artifacts" in result:
            for name, content in result["artifacts"].items():
                if isinstance(content, str):
                    _write_text(os.path.join(artifact_dir, name), content)

        # 2) Write generated code files under generated_code/
        if isinstance(result, dict) and "generated_files" in result:
            gen_root = os.path.join(artifact_dir, "generated_code")
            for rel_path, content in result["generated_files"].items():
                if isinstance(content, str):
                    full_path = os.path.join(gen_root, rel_path)
                    _write_text(full_path, content)

        # Base directory for the rest of processing (Path)
        rel_dir = f"{run.project_id}/{run.id}"
        dir_path = Path(artifact_dir)

        # Normalized markdown content for the primary artifact (for legacy agents).
        markdown = ""
        additional_artifacts: list[Artifact] = []
        generated_files_index: list[str] = []

        if isinstance(agent_result, str):
            markdown = agent_result
        elif isinstance(agent_result, dict):
            # Prefer explicit markdown/content fields; fall back to IMPLEMENTATION_PLAN.md from artifacts.
            md_value = agent_result.get("markdown") or agent_result.get("content") or agent_result.get("text")
            artifacts = agent_result.get("artifacts")
            if isinstance(artifacts, dict) and not md_value:
                md_value = artifacts.get("IMPLEMENTATION_PLAN.md")
            if isinstance(md_value, str):
                markdown = md_value

            # Handle high-level artifacts (e.g. IMPLEMENTATION_PLAN.md, CODEBASE_TREE.md, etc.).
            # Files already written via _write_text above; only create Artifact rows.
            artifacts_payload = agent_result.get("artifacts") or []
            if isinstance(artifacts_payload, dict):
                for path, content in artifacts_payload.items():
                    if isinstance(path, str) and isinstance(content, str):
                        rel_artifact_path = f"{rel_dir}/{path}"
                        artifact_obj = Artifact(run_id=run.id, project_id=run.project_id, path=rel_artifact_path)
                        session.add(artifact_obj)
                        additional_artifacts.append(artifact_obj)
            elif isinstance(artifacts_payload, list):
                for item in artifacts_payload:
                    if not isinstance(item, dict):
                        continue
                    path = item.get("path")
                    content = item.get("content")
                    if not isinstance(path, str) or not isinstance(content, str):
                        continue
                    artifact_file = dir_path / path
                    artifact_file.parent.mkdir(parents=True, exist_ok=True)
                    artifact_file.write_text(content, encoding="utf-8")
                    rel_artifact_path = f"{rel_dir}/{path}"
                    artifact_obj = Artifact(run_id=run.id, project_id=run.project_id, path=rel_artifact_path)
                    session.add(artifact_obj)
                    additional_artifacts.append(artifact_obj)

            # Handle generated code files under generated_code/ (from "files" or "generated_files").
            files_payload = agent_result.get("files") or agent_result.get("generated_files") or []
            file_items: list[tuple[str, str]] = []
            if isinstance(files_payload, dict):
                for path, content in files_payload.items():
                    if isinstance(path, str) and isinstance(content, str):
                        file_items.append((path, content))
            elif isinstance(files_payload, list):
                for entry in files_payload:
                    if not isinstance(entry, dict):
                        continue
                    path = entry.get("path")
                    content = entry.get("content")
                    if isinstance(path, str) and isinstance(content, str):
                        file_items.append((path, content))

            if file_items:
                generated_root = dir_path / "generated_code"
                # Files may already be written via _write_text above; ensure index and avoid double-write.
                already_wrote = isinstance(result, dict) and "generated_files" in result
                for rel_file_path, file_content in file_items:
                    normalized_rel = rel_file_path.lstrip("/\\")
                    if not already_wrote:
                        dest_path = generated_root / normalized_rel
                        dest_path.parent.mkdir(parents=True, exist_ok=True)
                        dest_path.write_text(file_content, encoding="utf-8")
                    generated_rel = f"{rel_dir}/generated_code/{normalized_rel}"
                    generated_files_index.append(generated_rel)
        else:
            # Fallback for unexpected result types.
            markdown = str(agent_result)

        # Always write a primary markdown artifact for backward compatibility.
        filename = AGENT_ARTIFACT_FILENAMES.get(run.agent_key, "output.md")
        file_path = dir_path / filename
        file_path.write_text(markdown, encoding="utf-8")

        rel_path = f"{rel_dir}/{filename}"
        primary_artifact = Artifact(run_id=run.id, project_id=run.project_id, path=rel_path)
        session.add(primary_artifact)

        # Optionally create GENERATED_FILES_INDEX.json listing all generated files.
        index_artifact = None
        if generated_files_index:
            index_path = dir_path / "GENERATED_FILES_INDEX.json"
            if not index_path.exists():
                index_payload = {"files": sorted(generated_files_index)}
                index_path.write_text(json.dumps(index_payload, indent=2), encoding="utf-8")
            rel_index_path = f"{rel_dir}/GENERATED_FILES_INDEX.json"
            index_artifact = Artifact(run_id=run.id, project_id=run.project_id, path=rel_index_path)
            session.add(index_artifact)
            additional_artifacts.append(index_artifact)

        session.flush()

        run.status = "completed"
        # 3) Keep output_json useful
        run.output_json = {
            "summary": result.get("summary", "") if isinstance(result, dict) else str(result),
            "artifact_dir": artifact_dir,
            "generated_code_dir": os.path.join(artifact_dir, "generated_code"),
        }
        session.commit()
    finally:
        session.close()
