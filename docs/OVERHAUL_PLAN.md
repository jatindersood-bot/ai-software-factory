# AI Software Factory — UI + Workflow Overhaul Plan

This document describes the planned changes for a complete UI and workflow overhaul while keeping the existing API, worker, database models, and RQ queue architecture intact.

---

## 1. Proposed DB Changes

### 1.1 Project model

- **Add column** `idea_json` (JSON/Text, nullable): stores the full "Project Brief" JSON from the PM chat. When present, downstream agents can use structured fields (problem_statement, target_users, core_features, etc.) in addition to or instead of the legacy `idea` text.
- **Backward compatibility**: Existing rows keep `idea`; new projects created from PM chat set both `idea` (e.g. a summary or first 2k chars of brief) and `idea_json`. All existing endpoints that read `project.idea` continue to work.

### 1.2 No new tables

- **Approvals** table already exists; use it to gate pipeline stages (approve run → unlock next stage).
- **Runs**, **Artifacts**, **Projects** unchanged in structure except `Project.idea_json`.

### 1.3 Migration

- Add nullable `idea_json` column via Alembic or one-off migration script. Default `NULL`. No data loss; no changes to existing columns.
- **Script**: From `apps/api`, run `python scripts/add_idea_json_column.py` (Postgres: `ALTER TABLE projects ADD COLUMN IF NOT EXISTS idea_json JSONB`).

---

## 2. API Routes

### 2.1 Existing (unchanged)

- `GET /projects` — list projects
- `GET /projects/{id}` — get project
- `POST /projects` — create project (body: `title`, `idea`; extend to accept optional `idea_json`)
- `GET /projects/{id}/runs`, `GET /projects/{id}/timeline`
- `POST /projects/{id}/runs` — create run (agent_key, optional parent_run_id via body or convention)
- `GET /runs/{id}`, `POST /runs/{id}/apply_workspace`, `POST /runs/{id}/open_pr`, `POST /runs/{id}/preview_start`, `POST /runs/{id}/preview_stop`, `POST /runs/{id}/approve`, `POST /runs/{id}/rerun`
- `GET /artifacts/{id}/content`, `GET /projects/{id}/artifacts`
- `GET /health`, `POST /submit`, `GET/POST /greet` (unchanged)

### 2.2 New / extended

- **POST /pm/chat**  
  Body: `{ project_id?: number, message: string, state?: object }`  
  Response: `{ assistant_message: string, state: object, brief_partial: object, done: boolean }`  
  - If `project_id` is null/absent: stateless PM conversation; when `done === true`, client can submit brief via `POST /projects` with `idea_json`.
  - If `project_id` is set: optional persistence of state keyed by project (e.g. in-memory or DB; minimal scope for v1).

- **POST /projects** (extended)  
  Body: `{ title: string, idea: string, idea_json?: object }`  
  - If `idea_json` is provided, store it in `Project.idea_json` and use for downstream agents.

- **GET /pipeline** (or **GET /projects/{id}/pipeline**)  
  Returns pipeline definition: ordered list of stages (agent_key, display_name, depends_on_approval_for_previous_agent_key). Used by frontend to render pipeline cards and gating.

---

## 3. Frontend Routes / Components

### 3.1 Routes

| Route | Purpose |
|-------|--------|
| `/` | Home: two CTAs "Start new" / "View projects"; recent projects list with search + filter |
| `/projects` | Projects index: list all projects (title, created date, last run status), search, filter |
| `/projects/new` | PM chat: collect Project Brief via Q&A; show final brief editor; Submit → create project → redirect to `/projects/:id` |
| `/projects/[id]` | Pipeline: pipeline stages as cards (BA, Architect, Developer, Tester, Preview, Ship); status, last run, artifacts, actions (Run / Re-run / View); Review panel (Approve/Reject) when run completes; no navigate-away on Run (poll and update in place) |
| `/runs/[id]` | Run detail (keep); "Back to Project" link; no dead ends |

### 3.2 Component system (minimal)

- **Cards**: pipeline stage cards, project cards, review panel.
- **Badges**: status (queued, running, completed, failed), approval (pending, approved, rejected).
- **Steps**: optional stepper for PM chat or pipeline progress.
- **Toasts**: success/error for actions (use existing ToastContext / ToastProviderWrapper).
- Fix any missing imports (e.g. ToastContext) so all pages compile.

### 3.3 UX

- Home: do **not** redirect `/` to `/projects`; show Home with CTAs and recent projects.
- Project pipeline: when user clicks Run / Apply / Open PR / etc., **do not** navigate away; show "Job queued", poll run status, update cards and artifacts in place.
- Every run/artifact view has "Back to Project" (or "Back to pipeline").

---

## 4. Agent Pipeline Definition

### 4.1 Server-side pipeline (ordered stages)

| Order | agent_key | Display name | Depends on approval of |
|-------|-----------|--------------|-------------------------|
| 1 | business_analyst | Business Analyst | — |
| 2 | architect | Architect | business_analyst |
| 3 | ai_development | Developer | architect |
| 4 | tester | Tester | ai_development |
| 5 | apply_workspace | Apply to workspace | (ai_development approved) |
| 6 | smoke_check | Smoke check | apply_workspace |
| 7 | preview_start | Preview | (optional; no gate) |
| 8 | open_pr | Open PR | apply_workspace |
| 9 | ship | Ship | apply_workspace (and optionally smoke_check) |

- **Gating**: A stage is "unlocked" only when the previous stage (by order) has a run with status `completed` and an approval with `decision === 'approved'`. Rejected runs can trigger a re-run with feedback.

### 4.2 Artifacts (per agent)

- **business_analyst**: REQUIREMENTS.md, USER_STORIES.md, ACCEPTANCE_CRITERIA.md  
- **architect**: ARCHITECTURE.md, API_CONTRACT.md, DB_SCHEMA.md  
- **ai_development**: (existing) generated_code/, IMPLEMENTATION_PLAN.md, etc.; keep dependency normalization, "use client", CORS patching.  
- **tester**: TEST_PLAN.md, optional Postman collection or minimal test files.  
- **apply_workspace**, **smoke_check**, **preview_start**, **open_pr**: (existing behavior).  
- **ship**: creates GitHub repo from workspace, pushes main; returns repo URL; artifact: SHIP_REPO.json or similar.

### 4.3 New agent keys

- **pm_chat**: used only in API (POST /pm/chat); no RQ run for PM chat (conversation is synchronous).  
- **business_analyst**, **architect**, **tester**, **ship**: new RQ agents; worker must handle them and write the above artifacts.

---

## 5. Migration Plan (No Data Loss)

1. **DB**: Add `idea_json` nullable column to `projects`; backfill not required.  
2. **API**: Add new routes (/pm/chat, /pipeline or /projects/:id/pipeline); extend POST /projects. Do not remove or change existing route contracts.  
3. **Worker**: Add agent_key handlers for business_analyst, architect, tester, ship; ensure all output_json passed to DB are JSON-serializable (use _json_safe; convert any usage objects to dict).  
4. **Frontend**:  
   - Replace home redirect with real Home page; add Projects index enhancements (search, filter).  
   - Add /projects/new PM chat flow; keep /projects/new as route.  
   - Add pipeline view at /projects/[id] with polling and review/approve; keep /runs/[id] with Back to Project.  
5. **CORS / Preview**: Keep allow_origin_regex; keep Next/React normalization and globals.css/linked-routes fixers.

---

## 6. E2E Smoke Test Instructions

- **API**: `GET /health` → 200; `GET /projects` → 200; `POST /projects` with title+idea → 201.  
- **Worker**: Enqueue a run (e.g. idea_clarifier), run worker, check run status completed and artifact exists.  
- **Web**: Open `/` → see Home with CTAs; click "View projects" → projects list; click "Start new" → PM chat (or new project form); create project → pipeline page; trigger Run on first stage → status updates without leaving page.  
- **Preview**: Start preview from pipeline → UI opens; no build error (globals.css, /submit route).

---

## 7. Implementation Order (Small Commits)

1. **Commit 1 — Home + Projects index**: Home page with CTAs and recent projects; Projects list with search + filter; no redirect from `/` to `/projects`.  
2. **Commit 2 — PM chat**: POST /pm/chat endpoint; Project.idea_json + schema; /projects/new chat UI with one-question-at-a-time, state, and Submit creating project with idea_json.  
3. **Commit 3 — Pipeline page**: Pipeline definition API; /projects/[id] pipeline UI with cards, polling, Run/Re-run, Review panel with Approve/Reject; "Back to Project" on run/artifact.  
4. **Commit 4 — BA/Architect/Tester/Ship stubs**: Worker handlers; artifact filenames; stub implementations writing the required .md (and optional) artifacts.  
5. **Commit 5 — Ship implementation**: Ship agent creates repo (ensure_repo or create from workspace), pushes workspace content to main; return repo URL; document GITHUB_* in .env.example.  
6. **Commit 6 — output_json + docs**: Ensure every output_json path uses _json_safe; add this doc and smoke test steps to README or /docs.
