"""Database engine, session, and initialization."""

import os
from contextlib import contextmanager
from typing import Generator

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.models import Base, Agent

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg2://app:app@localhost:5432/factory")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db() -> None:
    """Create all tables if they do not exist. Seed agents if empty."""
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as session:
        if session.query(Agent).count() == 0:
            for key, name in [
                ("idea_clarifier", "Idea Clarifier"),
                ("prd", "PRD Writer"),
                ("architecture", "Architecture"),
            ]:
                session.add(Agent(key=key, name=name))
            session.commit()


@contextmanager
def get_db() -> Generator[Session, None, None]:
    """Provide a transactional scope for the session."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
