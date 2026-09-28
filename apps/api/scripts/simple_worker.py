import os
import sys

# Ensure app package is importable (worker may be run from repo root or apps/api)
_script_dir = os.path.dirname(os.path.abspath(__file__))
_api_root = os.path.dirname(_script_dir)
if _api_root not in sys.path:
    sys.path.insert(0, _api_root)

# Run from API root so .env and relative paths (e.g. ARTIFACTS_DIR) resolve correctly
os.chdir(_api_root)

from redis import Redis
from rq import Queue, SimpleWorker

# Import the job function so RQ can resolve it and so import errors fail at startup
from app.worker import process_run  # noqa: F401

redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
conn = Redis.from_url(redis_url)

q = Queue("default", connection=conn)
worker = SimpleWorker([q], connection=conn)
worker.work()
