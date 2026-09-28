# Smoke test (E2E)

Run these checks after starting the API, worker, and web app.

## Prerequisites

- API: `cd apps/api && uvicorn app.main:app --reload --port 8000`
- Worker: `cd apps/api && python scripts/simple_worker.py` (or RQ worker)
- Web: `cd apps/web && npm run dev`
- Redis and Postgres running; optional: run migration for `idea_json` (see OVERHAUL_PLAN.md)

## API

1. **Health**  
   `curl -s http://localhost:8000/health` → `{"status":"ok"}`

2. **List projects**  
   `curl -s http://localhost:8000/projects` → `[]` or list of projects

3. **Create project**  
   `curl -s -X POST http://localhost:8000/projects -H "Content-Type: application/json" -d '{"title":"Smoke","idea":"A test"}'`  
   → 201 with `{"id":..., "title":"Smoke", ...}`

4. **Pipeline**  
   `curl -s http://localhost:8000/pipeline` → `{"stages":[...]}`

5. **PM chat**  
   `curl -s -X POST http://localhost:8000/pm/chat -H "Content-Type: application/json" -d '{"message":""}'`  
   → `{"assistant_message":"...", "state":..., "brief_partial":..., "done":false}`

## Web

1. Open `http://localhost:3000` → Home with "Start new" and "View projects".
2. Click "View projects" → Projects list (search/filter).
3. Click "Start new" → PM chat; answer questions until done, then Submit → redirect to project pipeline.
4. On project pipeline: click "Run" on Business Analyst → status updates without leaving the page (polling).
5. From any run or artifact page, use "Back to Project" / "Back to projects" (no dead ends).

## Worker

1. Create a run (e.g. Business Analyst) from the UI or API.
2. Run the worker; run status becomes `completed` and artifacts appear under `artifacts/<project_id>/<run_id>/`.

## Migration (optional)

If you use Postgres and need the `idea_json` column:

```bash
cd apps/api && python scripts/add_idea_json_column.py
```
