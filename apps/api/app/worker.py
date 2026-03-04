"""RQ worker: process runs by calling agent and writing artifacts."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.models import Base, Project, Run, Artifact
from app.agents import run_agent
from app.github_client import ensure_repo, upsert_file

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg2://app:app@localhost:5432/factory")
ARTIFACTS_DIR = Path(os.getenv("ARTIFACTS_DIR", "./artifacts")).resolve()
WORKSPACES_DIR = Path(os.getenv("WORKSPACES_DIR", "./workspaces")).resolve()

AGENT_ARTIFACT_FILENAMES: dict[str, str] = {
    "idea_clarifier": "idea_clarification.md",
    "prd": "prd.md",
    "architecture": "architecture.md",
    "architect": "ARCHITECTURE.md",
    "business_analyst": "REQUIREMENTS.md",
    "tester": "TEST_PLAN.md",
}

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _json_safe(obj):
    try:
        json.dumps(obj)
        return obj
    except TypeError:
        if hasattr(obj, "model_dump"):
            return _json_safe(obj.model_dump())
        if hasattr(obj, "dict"):
            return _json_safe(obj.dict())
        if isinstance(obj, (list, tuple)):
            return [_json_safe(x) for x in obj]
        if isinstance(obj, dict):
            return {str(k): _json_safe(v) for k, v in obj.items()}
        return str(obj)


def _write_text(path: str, content: str) -> None:
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def _run_cmd(cwd: Path, *args: str) -> str:
    """Run a command and return stdout; raise on non-zero exit."""
    import subprocess
    r = subprocess.run(
        args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(args)}\n{r.stderr or r.stdout}")
    return r.stdout or ""


def _run_cmd_capture(
    cwd: Path,
    *args: str,
    timeout: int | None = 120,
) -> tuple[int, str, str]:
    """Run a command; return (returncode, stdout, stderr). Does not raise."""
    import subprocess
    r = subprocess.run(
        args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return (r.returncode, r.stdout or "", r.stderr or "")


def _is_safe_relative_path(path: str) -> bool:
    """Refuse leading /, .., or path escape from a base dir."""
    p = path.strip().replace("\\", "/").lstrip("/")
    if not p or p.startswith("/") or ".." in p:
        return False
    return True


def _detect_build_type(generated_code_dir: Path) -> dict:
    """
    Inspect artifacts/<project>/<run>/generated_code and return booleans for frontend/backend.
    has_frontend: package.json or Next.js config (next.config.js, next.config.mjs, etc.).
    has_backend: requirements.txt and (main.py or any .py file containing FastAPI app).
    """
    if not generated_code_dir.is_dir():
        return {"has_frontend": False, "has_backend": False}

    has_frontend = False
    has_backend_requirements = False
    has_backend_app = False

    next_config_names = {"next.config.js", "next.config.mjs", "next.config.ts", "next.config.cjs"}

    def check_dir(d: Path) -> None:
        nonlocal has_frontend, has_backend_requirements, has_backend_app
        for f in d.iterdir():
            if f.is_file():
                name = f.name
                name_lower = name.lower()
                if name_lower == "package.json" or name_lower in next_config_names:
                    has_frontend = True
                if name_lower == "requirements.txt":
                    has_backend_requirements = True
                if name_lower == "main.py":
                    has_backend_app = True
                if name_lower.endswith(".py") and not has_backend_app:
                    try:
                        text = f.read_text(encoding="utf-8", errors="replace")
                        if "FastAPI" in text or "from fastapi" in text.lower():
                            has_backend_app = True
                    except Exception:
                        pass
            elif f.is_dir() and not f.name.startswith("."):
                check_dir(f)

    check_dir(generated_code_dir)
    return {
        "has_frontend": has_frontend,
        "has_backend": has_backend_requirements and has_backend_app,
    }


def _write_generated_code(
    artifact_dir: Path,
    files: list[dict],
    rel_dir: str,
    session: Session,
    run_id: int,
    project_id: int,
) -> list[str]:
    """
    Write CodegenResponse.files into artifact_dir/generated_code/, overwriting existing.
    Create dirs as needed. Refuse unsafe paths. Write WRITE_SUMMARY.md. Return written paths.
    """
    generated_root = artifact_dir / "generated_code"
    if generated_root.exists():
        shutil.rmtree(generated_root)
    generated_root.mkdir(parents=True)
    generated_root_resolved = generated_root.resolve()
    written_paths: list[str] = []

    for entry in files:
        if not isinstance(entry, dict):
            continue
        path = entry.get("path")
        content = entry.get("content")
        if not isinstance(path, str) or not isinstance(content, str):
            continue
        norm = path.strip().replace("\\", "/").lstrip("/")
        if not _is_safe_relative_path(path):
            raise ValueError(f"Unsafe path refused: {path!r}")
        full = (generated_root / norm).resolve()
        try:
            full.relative_to(generated_root_resolved)
        except ValueError:
            raise ValueError(f"Path escapes generated_code: {path!r}") from None
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content, encoding="utf-8")
        written_paths.append(norm)

    summary_lines = [
        "# Write summary",
        "",
        f"**Files written:** {len(written_paths)}",
        "",
        "## Paths",
        "",
    ]
    for p in sorted(written_paths):
        summary_lines.append(f"- `{p}`")
    write_summary_path = artifact_dir / "WRITE_SUMMARY.md"
    write_summary_path.write_text("\n".join(summary_lines), encoding="utf-8")

    for norm in written_paths:
        rel_artifact_path = f"{rel_dir}/generated_code/{norm}"
        session.add(Artifact(run_id=run_id, project_id=project_id, path=rel_artifact_path))
    session.add(
        Artifact(run_id=run_id, project_id=project_id, path=f"{rel_dir}/WRITE_SUMMARY.md")
    )
    return written_paths


# React hooks that require "use client" in Next.js App Router
_NEXTJS_HOOK_PATTERNS = (
    "useState(",
    "useEffect(",
    "useRef(",
    "useMemo(",
    "useCallback(",
    "useReducer(",
    "useContext(",
)


def _apply_nextjs_client_directive_fix(
    generated_root: Path, write_summary_path: Path | None = None
) -> list[str]:
    """
    Walk generated_code/frontend/app/** and frontend/src/app/** (*.ts, *.tsx);
    add "use client"; at top if file uses hooks and missing.
    If write_summary_path is set and a file, append patched file list to it.
    """
    patched: list[str] = []
    for path_parts in (("frontend", "app"), ("frontend", "src", "app"), ("src", "app")):
        frontend_app = generated_root.joinpath(*path_parts)
        if not frontend_app.is_dir():
            continue
        for p in frontend_app.rglob("*"):
            if not p.is_file() or p.suffix not in (".ts", ".tsx"):
                continue
            try:
                content = p.read_text(encoding="utf-8")
            except Exception:
                continue
            if not any(hook in content for hook in _NEXTJS_HOOK_PATTERNS):
                continue
            lines = content.splitlines()
            first_non_empty = None
            for line in lines:
                s = line.strip()
                if s:
                    first_non_empty = s
                    break
            if first_non_empty is not None and (
                first_non_empty == '"use client";' or first_non_empty == '"use client"'
            ):
                continue
            new_content = '"use client";\n' + content
            p.write_text(new_content, encoding="utf-8")
            try:
                rel = p.relative_to(generated_root)
                patched.append(str(rel).replace("\\", "/"))
            except ValueError:
                patched.append(p.name)

    if patched and write_summary_path is not None and write_summary_path.is_file():
        existing = write_summary_path.read_text(encoding="utf-8")
        suffix = "\n\n## Next.js client directive fix\n\nPatched (added \"use client\";):\n\n"
        for path in sorted(set(patched)):
            suffix += f"- `{path}`\n"
        write_summary_path.write_text(existing.rstrip() + suffix, encoding="utf-8")

    return patched


def _ensure_app_globals_css(frontend_dir: Path) -> None:
    """
    Ensure a minimal globals.css exists for Next.js App Router builds.

    Some generated templates import `./globals.css` from `app/layout.tsx` (or `src/app/layout.tsx`)
    but forget to generate the corresponding `globals.css`, causing Next.js to fail compilation.
    """
    for app_dir in (frontend_dir / "app", frontend_dir / "src" / "app"):
        if not app_dir.is_dir():
            continue

        globals_path = app_dir / "globals.css"
        if globals_path.is_file():
            continue

        # Only create if a layout file exists (signals App Router structure).
        has_layout = any((app_dir / name).is_file() for name in ("layout.tsx", "layout.ts", "layout.jsx", "layout.js"))
        if not has_layout:
            continue

        try:
            globals_path.write_text("/* Global styles - generated fallback */\n", encoding="utf-8")
        except Exception:
            # Best-effort: don't fail the run because we couldn't create a style file.
            pass


def _ensure_nextjs_linked_routes(frontend_dir: Path) -> list[str]:
    """
    Next.js App Router requires routes like /submit to be located at app/submit/page.tsx (or src/app/...).
    Some generated code incorrectly creates app/submit.tsx and links to /submit, which 404s.
    This helper scans for simple internal links and moves matching flat files into the proper route folder.
    """
    import re

    app_dir: Path | None = None
    for candidate in (frontend_dir / "app", frontend_dir / "src" / "app"):
        if candidate.is_dir():
            app_dir = candidate
            break
    if app_dir is None:
        return []

    # Collect top-level internal routes referenced in code (e.g. href="/submit", router.push("/verify")).
    segments: set[str] = set()
    patterns = (
        re.compile(r"""href\s*=\s*["']/([^"'?#]+)"""),
        re.compile(r"""href\s*=\s*\{\s*["']/([^"'?#]+)"""),
        re.compile(r"""router\.push\(\s*["']/([^"'?#]+)"""),
    )
    for p in app_dir.rglob("*"):
        if not p.is_file() or p.suffix not in (".ts", ".tsx", ".js", ".jsx"):
            continue
        try:
            content = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for pat in patterns:
            for m in pat.finditer(content):
                raw = m.group(1).strip()
                if not raw or raw.startswith("http"):
                    continue
                raw = raw.lstrip("/")
                if not raw or raw.startswith("("):
                    continue
                seg = raw.split("/")[0]
                if seg:
                    segments.add(seg)

    if not segments:
        return []

    changed: list[str] = []
    for seg in sorted(segments):
        seg_dir = app_dir / seg
        if seg_dir.is_dir():
            continue

        # If there is an incorrectly-flat file like app/submit.tsx, move it to app/submit/page.tsx.
        src_file: Path | None = None
        for ext in (".tsx", ".ts", ".jsx", ".js"):
            candidate = app_dir / f"{seg}{ext}"
            if candidate.is_file():
                src_file = candidate
                break
        if src_file is None:
            continue

        try:
            src = src_file.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        # App Router: prefer next/navigation over next/router.
        src = src.replace("from 'next/router'", "from 'next/navigation'").replace('from "next/router"', 'from "next/navigation"')

        seg_dir.mkdir(parents=True, exist_ok=True)
        page_name = f"page{src_file.suffix}"
        page_path = seg_dir / page_name
        page_path.write_text(src, encoding="utf-8")
        try:
            src_file.unlink()
        except Exception:
            pass
        changed.append(str(page_path.relative_to(frontend_dir)).replace("\\", "/"))

    return changed


def _execute_apply_workspace(session: Session, run: Run, project: Project) -> None:
    """Copy parent run's generated_code to workspace, git init if needed, write DIFF.patch, commit."""
    parent_id = run.parent_run_id
    if not parent_id:
        run.status = "failed"
        run.output_json = _json_safe({"error": "apply_workspace requires parent_run_id"})
        session.commit()
        return

    parent = session.get(Run, parent_id)
    if not parent:
        run.status = "failed"
        run.output_json = _json_safe({"error": f"Parent run {parent_id} not found"})
        session.commit()
        return

    project_id = run.project_id
    parent_artifact_dir = ARTIFACTS_DIR / str(project_id) / str(parent_id)
    generated_code_src = parent_artifact_dir / "generated_code"
    if not generated_code_src.is_dir():
        run.status = "failed"
        run.output_json = _json_safe({"error": f"Parent run has no generated_code at {generated_code_src}"})
        session.commit()
        return

    workspace_repo = WORKSPACES_DIR / str(project_id) / "repo"
    target_dir = workspace_repo / "generated_projects" / str(project_id)
    workspace_repo.mkdir(parents=True, exist_ok=True)
    target_dir.mkdir(parents=True, exist_ok=True)

    import shutil
    for p in generated_code_src.iterdir():
        dest = target_dir / p.name
        if p.is_dir():
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(p, dest)
        else:
            shutil.copy2(p, dest)

    git_dir = workspace_repo / ".git"
    if not git_dir.exists():
        _run_cmd(workspace_repo, "git", "init")

    artifact_dir = ARTIFACTS_DIR / str(project_id) / str(run.id)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    diff_content = f"# Apply workspace (run {run.id}, parent {parent_id})\n\nCopied generated_code from run {parent_id} to {target_dir}\n"
    diff_path = artifact_dir / "DIFF.patch"
    diff_path.write_text(diff_content, encoding="utf-8")

    frontend_dir = _find_frontend_dir(target_dir)
    if frontend_dir is not None:
        _normalize_preview_package_json(frontend_dir)
        lock = frontend_dir / "package-lock.json"
        if lock.is_file():
            lock.unlink()

    _run_cmd(workspace_repo, "git", "add", "-A")
    _run_cmd(workspace_repo, "git", "commit", "-m", f"Apply workspace from run {parent_id} (run {run.id})", "--allow-empty")

    run.status = "completed"
    run.output_json = _json_safe({
        "summary": f"Applied parent run {parent_id} generated_code to workspace",
        "workspace_dir": str(workspace_repo),
        "target_dir": str(target_dir),
        "artifact_dir": str(artifact_dir),
    })
    session.commit()


def _execute_smoke_check(session: Session, run: Run, project_id: int) -> None:
    """Run after apply_workspace: compile backend (compileall), optional npm run build for frontend. Write SMOKE_CHECK.txt; mark run failed if any step fails."""
    import subprocess

    parent_id = run.parent_run_id
    if not parent_id:
        run.status = "failed"
        run.output_json = _json_safe({"error": "smoke_check requires parent_run_id (apply_workspace run)"})
        session.commit()
        return

    workspace_repo = WORKSPACES_DIR / str(project_id) / "repo"
    target_dir = workspace_repo / "generated_projects" / str(project_id)
    if not target_dir.is_dir():
        run.status = "failed"
        run.output_json = _json_safe({"error": f"Workspace generated dir not found: {target_dir}; run apply_workspace first"})
        session.commit()
        return

    artifact_dir = ARTIFACTS_DIR / str(project_id) / str(run.id)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    failed = False

    # Backend: python -m compileall in generated backend folder
    backend_dir = target_dir / "backend"
    if backend_dir.is_dir():
        lines.append("## Backend (python -m compileall)\n")
        code, out, err = _run_cmd_capture(backend_dir, "python", "-m", "compileall", ".", timeout=60)
        lines.append(f"Exit code: {code}\n")
        if out:
            lines.append("stdout:\n")
            lines.append(out)
        if err:
            lines.append("stderr:\n")
            lines.append(err)
        lines.append("\n")
        if code != 0:
            failed = True

    # Frontend: if package.json exists, normalize then npm install and npm run build
    frontend_dir = target_dir / "frontend"
    if not frontend_dir.is_dir():
        frontend_dir = target_dir
    package_json = frontend_dir / "package.json"
    if package_json.is_file():
        lines.append("## Frontend (npm install + npm run build)\n")
        # Apply same fixers as preview so generated code builds
        _apply_nextjs_client_directive_fix(target_dir, None)
        _ensure_app_globals_css(frontend_dir)
        _normalize_frontend_package_json_for_build(frontend_dir)
        # Remove node_modules and lockfile so install is clean
        node_modules = frontend_dir / "node_modules"
        if node_modules.is_dir():
            shutil.rmtree(node_modules, ignore_errors=True)
        lock_path = frontend_dir / "package-lock.json"
        if lock_path.is_file():
            lock_path.unlink()
        try:
            code, out, err = _run_cmd_capture(frontend_dir, "npm", "install", timeout=180)
        except subprocess.TimeoutExpired:
            code = -1
            out = ""
            err = "npm install timed out after 180s"
        lines.append("npm install:\n")
        lines.append(f"Exit code: {code}\n")
        if out:
            lines.append(out[:4096] + ("..." if len(out) > 4096 else "") + "\n")
        if err:
            lines.append("stderr: " + err[:2048] + ("..." if len(err) > 2048 else "") + "\n")
        lines.append("\n")
        if code != 0:
            failed = True
        else:
            try:
                code, out, err = _run_cmd_capture(frontend_dir, "npm", "-s", "run", "build", timeout=120)
            except subprocess.TimeoutExpired:
                code = -1
                out = ""
                err = "Command timed out after 120s"
            lines.append(f"npm run build exit code: {code}\n")
            if out:
                lines.append("stdout:\n")
                lines.append(out)
            if err:
                lines.append("stderr:\n")
                lines.append(err)
            lines.append("\n")
            if code != 0:
                failed = True
    else:
        lines.append("## Frontend\n\nNo package.json found; skipping npm build.\n\n")

    smoke_path = artifact_dir / "SMOKE_CHECK.txt"
    smoke_path.write_text("".join(lines), encoding="utf-8")
    rel_dir = f"{run.project_id}/{run.id}"
    session.add(Artifact(run_id=run.id, project_id=run.project_id, path=f"{rel_dir}/SMOKE_CHECK.txt"))

    if failed:
        run.status = "failed"
        run.output_json = _json_safe({"error": "Smoke check failed (compile or build)", "artifact_dir": str(artifact_dir)})
    else:
        run.status = "completed"
        run.output_json = _json_safe({"summary": "Smoke check passed", "artifact_dir": str(artifact_dir)})
    session.commit()


def _execute_open_pr(session: Session, run: Run, project_id: int) -> dict:
    """Ensure workspace has commits, create branch, write PR_LINK.md. Returns dict for run.output_json; raises on failure."""
    parent_id = run.parent_run_id
    if not parent_id:
        raise ValueError("open_pr requires parent_run_id")

    parent = session.get(Run, parent_id)
    if not parent:
        raise ValueError(f"Parent run {parent_id} not found")

    workspace_repo = WORKSPACES_DIR / str(project_id) / "repo"
    if not workspace_repo.is_dir():
        raise ValueError(f"Workspace not found at {workspace_repo}; run apply_workspace first")

    git_dir = workspace_repo / ".git"
    if not git_dir.exists():
        raise ValueError("Workspace has no .git; run apply_workspace first")

    try:
        _run_cmd(workspace_repo, "git", "rev-parse", "HEAD")
    except RuntimeError:
        raise ValueError("Workspace has no commits; run apply_workspace first")

    artifact_dir = ARTIFACTS_DIR / str(project_id) / str(run.id)
    artifact_dir.mkdir(parents=True, exist_ok=True)

    target_dir = workspace_repo / "generated_projects" / str(project_id)
    if target_dir.is_dir():
        frontend_dir = _find_frontend_dir(target_dir)
        if frontend_dir is not None:
            _normalize_preview_package_json(frontend_dir)
            lock = frontend_dir / "package-lock.json"
            if lock.is_file():
                lock.unlink()
            _run_cmd(workspace_repo, "git", "add", "-A")
            code, _, _ = _run_cmd_capture(workspace_repo, "git", "diff", "--staged", "--quiet")
            if code != 0:
                _run_cmd(workspace_repo, "git", "commit", "-m", "Normalize Next/React dependencies")

    branch_name = f"ai/project-{project_id}-run-{parent_id}"
    _run_cmd(workspace_repo, "git", "checkout", "-b", branch_name)

    pr_link_md = artifact_dir / "PR_LINK.md"
    pr_url = os.getenv("GITHUB_REPO_URL", "")
    if pr_url:
        pr_url = pr_url.rstrip("/")
        if pr_url.endswith(".git"):
            pr_url = pr_url[:-4]
        pr_compare = f"{pr_url}/compare/main...{branch_name}" if pr_url else ""
    else:
        pr_compare = ""
    content = f"# Open PR (run {run.id}, parent {parent_id})\n\nBranch: `{branch_name}`\n\n"
    if pr_compare:
        content += f"PR link: {pr_compare}\n"
    else:
        content += "Set GITHUB_REPO_URL and push to create PR link.\n"
    pr_link_md.write_text(content, encoding="utf-8")

    return {
        "summary": f"Created branch {branch_name} for parent run {parent_id}",
        "workspace_dir": str(workspace_repo),
        "branch": branch_name,
        "artifact_dir": str(artifact_dir),
    }


def _find_frontend_dir(root: Path) -> Path | None:
    """Return directory containing package.json (root or frontend/app/web subdir)."""
    if (root / "package.json").is_file():
        return root
    for sub in ("frontend", "app", "web"):
        d = root / sub
        if (d / "package.json").is_file():
            return d
    return None


def _find_backend_dir(root: Path) -> Path | None:
    """Return directory containing requirements.txt and main.py or FastAPI app."""
    def has_backend(d: Path) -> bool:
        if not (d / "requirements.txt").is_file():
            return False
        if (d / "main.py").is_file():
            return True
        for f in d.rglob("*.py"):
            if f.is_file():
                try:
                    t = f.read_text(encoding="utf-8", errors="replace")
                    if "FastAPI" in t or "from fastapi" in t.lower():
                        return True
                except Exception:
                    pass
        return False
    if has_backend(root):
        return root
    for sub in ("backend", "api", "server"):
        d = root / sub
        if d.is_dir() and has_backend(d):
            return d
    return None


def _next_major(ver: str) -> int | None:
    """Parse major version from a semver-like string (e.g. 14.2.35, ^14.0.0)."""
    if not ver or not isinstance(ver, str):
        return None
    ver = ver.strip().lstrip("^~>=<")
    part0 = ver.split(".")[0].split("-")[0]
    try:
        return int(part0)
    except ValueError:
        return None


def _normalize_preview_package_json(frontend_dir: Path) -> list[str]:
    """
    Load package.json, normalize react/react-dom/next for Next 14; write back.
    Force next=14.2.35, react=18.2.0, react-dom=18.2.0 when next major is 14 or next missing.
    Return list of change descriptions.
    """
    pkg_path = frontend_dir / "package.json"
    if not pkg_path.is_file():
        return []
    try:
        data = json.loads(pkg_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(data, dict):
        return []
    deps = data.get("dependencies")
    if deps is None:
        deps = {}
        data["dependencies"] = deps
    elif not isinstance(deps, dict):
        return []

    next_ver = deps.get("next")
    next_major = _next_major(next_ver) if next_ver else None
    apply = next_major == 14 or next_ver is None
    if next_ver is not None and next_major is not None and next_major != 14:
        apply = False

    if not apply:
        return []

    changes: list[str] = []
    TARGET = {"next": "14.2.35", "react": "18.2.0", "react-dom": "18.2.0"}
    for key, target_val in TARGET.items():
        current = deps.get(key)
        if current != target_val:
            deps[key] = target_val
            changes.append(f"- Set `{key}` to `{target_val}`" + (f" (was `{current}`)" if current else " (added)"))

    if not changes:
        return []

    pkg_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return changes


def _normalize_frontend_package_json_for_build(frontend_dir: Path) -> list[str]:
    """
    Ensure package.json has scripts (dev, build, start) and compatible dependency versions
    for Next 14 (next ^14.2.0, react/react-dom ^18.2.0). Used before npm install in smoke_check.
    Returns list of change descriptions.
    """
    pkg_path = frontend_dir / "package.json"
    if not pkg_path.is_file():
        return []
    try:
        data = json.loads(pkg_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(data, dict):
        return []
    changes: list[str] = []

    # Ensure scripts
    scripts = data.get("scripts")
    if scripts is None:
        scripts = {}
        data["scripts"] = scripts
    elif not isinstance(scripts, dict):
        return []
    required_scripts = {"dev": "next dev", "build": "next build", "start": "next start"}
    for name, cmd in required_scripts.items():
        if scripts.get(name) != cmd:
            scripts[name] = cmd
            changes.append(f"- Set script `{name}` to `{cmd}`")

    # Normalize dependencies for Next 14 compatibility
    deps = data.get("dependencies")
    if deps is None:
        deps = {}
        data["dependencies"] = deps
    elif not isinstance(deps, dict):
        return changes
    target_versions = {"next": "^14.2.0", "react": "^18.2.0", "react-dom": "^18.2.0"}
    for key, target_val in target_versions.items():
        current = deps.get(key)
        if current != target_val:
            deps[key] = target_val
            changes.append(f"- Set `{key}` to `{target_val}`" + (f" (was `{current}`)" if current else " (added)"))

    if not changes:
        return []
    pkg_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return changes


def _execute_preview_start(session: Session, run: Run, project_id: int) -> None:
    """
    Find parent run's generated_code, copy to workspaces/<project_id>/previews/<parent_run_id>/,
    detect frontend (package.json) and/or backend (requirements.txt + main.py), start frontend
    dev server on port 3100 + project_id, write PREVIEW.json with ui_url, port, cwd, pid; set output_json same.
    """
    parent_id = run.parent_run_id
    if not parent_id:
        run.status = "failed"
        run.output_json = _json_safe({"error": "preview_start requires parent_run_id"})
        session.commit()
        return

    parent = session.get(Run, parent_id)
    if not parent:
        run.status = "failed"
        run.output_json = _json_safe({"error": f"Parent run {parent_id} not found"})
        session.commit()
        return

    parent_artifact_dir = ARTIFACTS_DIR / str(project_id) / str(parent_id)
    generated_code_src = parent_artifact_dir / "generated_code"
    if not generated_code_src.is_dir():
        run.status = "failed"
        run.output_json = _json_safe({"error": f"Parent run has no generated_code at {generated_code_src}"})
        session.commit()
        return

    preview_dir = WORKSPACES_DIR / str(project_id) / "previews" / str(parent_id)
    if preview_dir.exists():
        shutil.rmtree(preview_dir)
    shutil.copytree(generated_code_src, preview_dir)

    frontend_dir = _find_frontend_dir(preview_dir)
    backend_dir = _find_backend_dir(preview_dir)

    port = 3100 + project_id
    ui_url: str | None = None
    cwd: str | None = None
    pid: int | None = None

    if frontend_dir is not None:
        # Add "use client"; to frontend/app *.{ts,tsx} that use hooks, before npm install
        _apply_nextjs_client_directive_fix(preview_dir, None)
        # Fix linked routes like /submit when code mistakenly generates app/submit.tsx
        _ensure_nextjs_linked_routes(frontend_dir)
        # Ensure app/globals.css exists if layout.tsx imports it (avoid build failure)
        _ensure_app_globals_css(frontend_dir)
        # Normalize package.json versions (next 14.2.35, react/react-dom 18.2.0) before npm install
        changes = _normalize_preview_package_json(frontend_dir)
        lock_path = frontend_dir / "package-lock.json"
        if lock_path.is_file():
            lock_path.unlink()
        # Log dependency changes to artifact
        artifact_dir = ARTIFACTS_DIR / str(project_id) / str(run.id)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        rel_dir = f"{project_id}/{run.id}"
        if changes:
            md_lines = ["# Preview dependencies", "", "Normalized versions for Next 14 compatibility:", ""] + changes
            (artifact_dir / "PREVIEW_DEPENDENCIES.md").write_text("\n".join(md_lines), encoding="utf-8")
            session.add(Artifact(run_id=run.id, project_id=project_id, path=f"{rel_dir}/PREVIEW_DEPENDENCIES.md"))

        code, _, err = _run_cmd_capture(frontend_dir, "npm", "install", timeout=180)
        if code != 0:
            run.status = "failed"
            run.output_json = _json_safe({"error": f"npm install failed: {err or 'non-zero exit'}"})
            session.commit()
            return
        # Optional next_build_check: run npm run build; if it fails, capture error and mark run failed
        if os.getenv("NEXT_BUILD_CHECK", "").lower() in ("1", "true", "yes"):
            build_code, build_out, build_err = _run_cmd_capture(frontend_dir, "npm", "run", "build", timeout=300)
            if build_code != 0:
                artifact_dir = ARTIFACTS_DIR / str(project_id) / str(run.id)
                artifact_dir.mkdir(parents=True, exist_ok=True)
                rel_dir = f"{project_id}/{run.id}"
                error_content = f"# Next.js build failed (exit code {build_code})\n\n## stdout\n\n{build_out}\n\n## stderr\n\n{build_err}"
                (artifact_dir / "BUILD_ERROR.txt").write_text(error_content, encoding="utf-8")
                session.add(Artifact(run_id=run.id, project_id=project_id, path=f"{rel_dir}/BUILD_ERROR.txt"))
                run.status = "failed"
                run.output_json = _json_safe({
                    "error": "Next.js build failed",
                    "build_stdout": build_out,
                    "build_stderr": build_err,
                })
                session.commit()
                return
        proc = subprocess.Popen(
            ["npm", "run", "dev", "--", "-p", str(port)],
            cwd=str(frontend_dir),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        ui_url = f"http://localhost:{port}"
        cwd = str(frontend_dir)
        pid = proc.pid

    artifact_dir = ARTIFACTS_DIR / str(project_id) / str(run.id)
    if not artifact_dir.exists():
        artifact_dir.mkdir(parents=True, exist_ok=True)
    rel_dir = f"{project_id}/{run.id}"

    preview_payload = {
        "ui_url": ui_url,
        "port": port,
        "cwd": cwd,
        "pid": pid,
    }
    preview_path = artifact_dir / "PREVIEW.json"
    preview_path.write_text(json.dumps(preview_payload, indent=2), encoding="utf-8")
    session.add(Artifact(run_id=run.id, project_id=project_id, path=f"{rel_dir}/PREVIEW.json"))

    run.status = "completed"
    run.output_json = _json_safe(preview_payload)
    session.commit()


def _execute_ship(session: Session, run: Run, project_id: int) -> dict:
    """Create GitHub repo from workspace and push main. Returns dict with repo_url."""
    workspace_repo = WORKSPACES_DIR / str(project_id) / "repo"
    target_dir = workspace_repo / "generated_projects" / str(project_id)
    if not target_dir.is_dir():
        raise ValueError(f"Workspace generated dir not found: {target_dir}; run apply_workspace first")

    project = session.get(Project, project_id)
    repo_name = (project.github_repo if project else None) or f"factory-project-{project_id}"
    repo = ensure_repo(repo_name, private=True)
    default_branch = repo.default_branch

    files_uploaded = 0
    for f in target_dir.rglob("*"):
        if not f.is_file():
            continue
        rel = f.relative_to(target_dir)
        path_str = str(rel).replace("\\", "/")
        try:
            content = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        try:
            upsert_file(repo, default_branch, path_str, content, f"Ship from run {run.id}")
            files_uploaded += 1
        except Exception as e:
            raise RuntimeError(f"Failed to upsert {path_str}: {e}") from e

    repo_url = repo.html_url
    if project:
        project.github_repo = repo.name
        project.github_repo_url = repo_url
        project.github_owner = repo.owner.login
        project.github_default_branch = default_branch
        session.flush()

    artifact_dir = ARTIFACTS_DIR / str(project_id) / str(run.id)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    ship_json = artifact_dir / "SHIP_REPO.json"
    ship_json.write_text(
        json.dumps({"repo_url": repo_url, "files_uploaded": files_uploaded}, indent=2),
        encoding="utf-8",
    )
    rel_dir = f"{project_id}/{run.id}"
    session.add(Artifact(run_id=run.id, project_id=project_id, path=f"{rel_dir}/SHIP_REPO.json"))

    return {
        "summary": f"Shipped to {repo_url}",
        "repo_url": repo_url,
        "files_uploaded": files_uploaded,
    }


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
            run.output_json = _json_safe({"error": "Project not found"})
            session.commit()
            return

        if run.agent_key == "apply_workspace":
            try:
                _execute_apply_workspace(session, run, project)
            except Exception as e:
                run.status = "failed"
                run.output_json = _json_safe({"error": str(e)})
                session.commit()
            return

        if run.agent_key == "open_pr":
            try:
                result = _execute_open_pr(session, run, run.project_id)
                run.status = "completed"
                run.output_json = _json_safe(result)
                session.commit()
            except Exception as e:
                run.status = "failed"
                run.output_json = _json_safe({"error": str(e)})
                session.commit()
            return

        if run.agent_key == "smoke_check":
            try:
                _execute_smoke_check(session, run, run.project_id)
            except Exception as e:
                run.status = "failed"
                run.output_json = _json_safe({"error": str(e)})
                session.commit()
            return

        if run.agent_key == "preview_start":
            try:
                _execute_preview_start(session, run, run.project_id)
            except Exception as e:
                run.status = "failed"
                run.output_json = _json_safe({"error": str(e)})
                session.commit()
            return

        if run.agent_key == "ship":
            try:
                result = _execute_ship(session, run, run.project_id)
                run.status = "completed"
                run.output_json = _json_safe(result)
                session.commit()
            except Exception as e:
                run.status = "failed"
                run.output_json = _json_safe({"error": str(e)})
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
            if run.agent_key == "ai_development":
                artifact_dir = ARTIFACTS_DIR / str(run.project_id) / str(run.id)
                artifact_dir.mkdir(parents=True, exist_ok=True)
                last_raw = getattr(e, "last_raw", None) or ""
                max_raw_len = 50_000
                raw_preview = last_raw[:max_raw_len] + ("...[truncated]" if len(last_raw) > max_raw_len else "")
                error_content = f"# LLM Error\n\n{str(e)}\n\n## Last raw model output\n\n```\n{raw_preview}\n```\n"
                (artifact_dir / "LLM_ERROR.md").write_text(error_content, encoding="utf-8")
                rel_dir = f"{run.project_id}/{run.id}"
                session.add(Artifact(run_id=run.id, project_id=run.project_id, path=f"{rel_dir}/LLM_ERROR.md"))
                run.output_json = _json_safe({"error": str(e), "artifact_dir": str(artifact_dir)})
            else:
                run.output_json = _json_safe({"error": str(e)})
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

            if run.agent_key == "ai_development" and isinstance(agent_result.get("files"), list) and len(agent_result["files"]) > 0:
                # ai_development: overwrite generated_code, safe paths, WRITE_SUMMARY.md
                written_rel = _write_generated_code(
                    dir_path, agent_result["files"], rel_dir, session, run.id, run.project_id
                )
                generated_files_index = [f"{rel_dir}/generated_code/{p}" for p in written_rel]
                # Next.js client directive fixer: add "use client"; to frontend app files that use hooks
                _apply_nextjs_client_directive_fix(dir_path / "generated_code", dir_path / "WRITE_SUMMARY.md")
                gen_code = dir_path / "generated_code"
                frontend_dir = _find_frontend_dir(gen_code)
                if frontend_dir is not None:
                    # Fix linked routes like /submit when code mistakenly generates app/submit.tsx
                    _ensure_nextjs_linked_routes(frontend_dir)
                    # Ensure app/globals.css exists if layout imports it
                    _ensure_app_globals_css(frontend_dir)
                    # Ensure package.json has dev/build/start scripts and compatible dependency versions
                    _normalize_frontend_package_json_for_build(frontend_dir)
            elif file_items:
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
        # 3) output_json: use agent's output_json when present (e.g. ai_development), else minimal
        output_json: dict = (
            result.get("output_json") if isinstance(result, dict) else {}
        )
        if not output_json:
            output_json = {
                "summary": result.get("summary", "") if isinstance(result, dict) else str(result),
            }
        output_json["artifact_dir"] = artifact_dir
        output_json["generated_code_dir"] = os.path.join(artifact_dir, "generated_code")
        gen_code_path = dir_path / "generated_code"
        output_json["build_type"] = _detect_build_type(gen_code_path)
        out = output_json
        out = _json_safe(out)
        run.output_json = out
        session.commit()
    finally:
        session.close()
