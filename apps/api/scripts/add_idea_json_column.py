"""
One-off migration: add idea_json column to projects table if missing.
Run from apps/api: python scripts/add_idea_json_column.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text

from app.db import engine


def main():
    with engine.connect() as conn:
        conn.execute(
            text("ALTER TABLE projects ADD COLUMN IF NOT EXISTS idea_json JSONB")
        )
        conn.commit()
    print("Done: projects.idea_json column added (or already present).")


if __name__ == "__main__":
    main()
