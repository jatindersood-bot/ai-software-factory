"""Initialize the database schema (create all tables). Run from apps/api: python3 scripts/init_db.py"""

import sys
from pathlib import Path

# Allow running as: python3 scripts/init_db.py from apps/api
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.models import Base
from app.db import engine

Base.metadata.create_all(bind=engine)
print("DB initialized")
