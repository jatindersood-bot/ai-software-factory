"""Pydantic schemas for request/response."""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


# --- Project ---
class ProjectCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=512)
    idea: str = Field(..., min_length=1)


class ProjectResponse(BaseModel):
    id: int
    title: str
    idea: str
    github_owner: Optional[str] = None
    github_repo: Optional[str] = None
    github_repo_url: Optional[str] = None
    github_default_branch: str = "main"
    created_at: datetime

    class Config:
        from_attributes = True


# --- Run ---
class RunCreate(BaseModel):
    agent_key: str = Field(..., min_length=1, max_length=64)


class RunResponse(BaseModel):
    id: int
    project_id: int
    agent_key: str
    status: str
    parent_run_id: Optional[int] = None
    input_json: Optional[dict[str, Any]] = None
    output_json: Optional[dict[str, Any]] = None
    created_at: datetime
    artifacts: list["ArtifactResponse"] = Field(default_factory=list)

    class Config:
        from_attributes = True


# --- Approval ---
class ApprovalCreate(BaseModel):
    decision: str = Field(..., min_length=1, max_length=32)
    feedback: Optional[str] = None


class ApprovalResponse(BaseModel):
    id: int
    run_id: int
    decision: str
    feedback: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


# --- Artifact ---
class ArtifactResponse(BaseModel):
    id: int
    run_id: int
    project_id: int
    path: str
    created_at: datetime

    class Config:
        from_attributes = True


# Resolve forward refs
RunResponse.model_rebuild()
