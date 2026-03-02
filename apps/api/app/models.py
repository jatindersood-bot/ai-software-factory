"""SQLAlchemy models for AI software factory."""

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import DateTime, ForeignKey, String, Text, JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all models."""

    pass


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    idea: Mapped[str] = mapped_column(Text, nullable=False)
    github_owner: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    github_repo: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    github_repo_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    github_default_branch: Mapped[str] = mapped_column(String(64), nullable=False, default="main")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    runs: Mapped[list["Run"]] = relationship("Run", back_populates="project")
    artifacts: Mapped[list["Artifact"]] = relationship("Artifact", back_populates="project")


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)
    agent_key: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    parent_run_id: Mapped[Optional[int]] = mapped_column(ForeignKey("runs.id"), nullable=True)
    input_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    output_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    project: Mapped["Project"] = relationship("Project", back_populates="runs")
    parent_run: Mapped[Optional["Run"]] = relationship("Run", remote_side=[id])
    artifacts: Mapped[list["Artifact"]] = relationship("Artifact", back_populates="run")
    approvals: Mapped[list["Approval"]] = relationship("Approval", back_populates="run")


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), nullable=False)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)
    path: Mapped[str] = mapped_column(String(512), nullable=False)  # relative under ARTIFACTS_DIR
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    run: Mapped["Run"] = relationship("Run", back_populates="artifacts")
    project: Mapped["Project"] = relationship("Project", back_populates="artifacts")


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), nullable=False)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)  # e.g. "approved", "rejected"
    feedback: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    run: Mapped["Run"] = relationship("Run", back_populates="approvals")
