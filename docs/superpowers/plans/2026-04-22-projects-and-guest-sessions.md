# Projects & Guest Sessions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add named projects with persistent state and guest sessions to ETL Studio, so users can save progress and resume later.

**Architecture:** SQLite stores project metadata (id, name, username, phase, timestamps). Pipeline state (config, validation results, DDL info, load results) is serialized to `state.json` on the filesystem. Row data is never serialized — it's re-extracted from source files on resume, and transform data is re-computed. Guest sessions remain fully in-memory and ephemeral. A landing page lets users create/open projects or start a guest session.

**Tech Stack:** Python `sqlite3` (stdlib), FastAPI, React + TypeScript, Tailwind CSS, existing UI component library.

---

## File Structure

### Backend — New Files

| File | Responsibility |
|---|---|
| `backend/db.py` | SQLite connection, schema init, all project CRUD queries |
| `backend/project_state.py` | Read/write `state.json`, hydrate session from saved state + re-extraction |
| `backend/models/project_schemas.py` | Pydantic models for project API requests/responses |

### Backend — Modified Files

| File | Changes |
|---|---|
| `backend/main.py` | New project API endpoints, auto-save hooks on existing pipeline endpoints, `data/` directory structure, guest session tagging |

### Frontend — New Files

| File | Responsibility |
|---|---|
| `frontend/src/components/LandingPage.tsx` | Landing page with Create Project / Open Project / Guest Session |
| `frontend/src/api/projects.ts` | API client functions for project endpoints |
| `frontend/src/types/project.ts` | TypeScript interfaces for project data |

### Frontend — Modified Files

| File | Changes |
|---|---|
| `frontend/src/store/pipeline.tsx` | Add `mode`, `projectId`, `projectName` to state; add `SET_PROJECT`, `RESTORE_PROJECT` actions |
| `frontend/src/App.tsx` | Conditionally render LandingPage vs pipeline; add Save button + project name in header |
| `frontend/src/api/client.ts` | Add optional `projectId` param to `uploadFiles` and `preExtract` |

---

## Task 1: SQLite Database Layer

**Files:**
- Create: `backend/db.py`

- [ ] **Step 1: Create `backend/db.py` with schema init and CRUD functions**

```python
import sqlite3
import os
import uuid
from datetime import datetime, timezone

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "etl_studio.db")


def _get_conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    conn = _get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS projects (
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            username    TEXT NOT NULL,
            phase       TEXT NOT NULL DEFAULT 'upload',
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL,
            UNIQUE(name, username)
        )
    """)
    conn.commit()
    conn.close()


def create_project(name: str, username: str) -> dict:
    conn = _get_conn()
    project_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    try:
        conn.execute(
            "INSERT INTO projects (id, name, username, phase, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (project_id, name, username, "upload", now, now),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        raise ValueError(f"Project '{name}' already exists for user '{username}'")
    conn.close()
    return {"id": project_id, "name": name, "username": username, "phase": "upload", "created_at": now, "updated_at": now}


def list_projects(username: str) -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, name, username, phase, created_at, updated_at FROM projects WHERE username = ? ORDER BY updated_at DESC",
        (username,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_project(project_id: str) -> dict | None:
    conn = _get_conn()
    row = conn.execute(
        "SELECT id, name, username, phase, created_at, updated_at FROM projects WHERE id = ?",
        (project_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def update_project_phase(project_id: str, phase: str) -> None:
    conn = _get_conn()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE projects SET phase = ?, updated_at = ? WHERE id = ?",
        (phase, now, project_id),
    )
    conn.commit()
    conn.close()


def rename_project(project_id: str, new_name: str) -> None:
    conn = _get_conn()
    now = datetime.now(timezone.utc).isoformat()
    row = conn.execute("SELECT username FROM projects WHERE id = ?", (project_id,)).fetchone()
    if not row:
        conn.close()
        raise ValueError("Project not found")
    try:
        conn.execute(
            "UPDATE projects SET name = ?, updated_at = ? WHERE id = ?",
            (new_name, now, project_id),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        raise ValueError(f"Project '{new_name}' already exists for this user")
    conn.close()


def delete_project(project_id: str) -> None:
    conn = _get_conn()
    conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    conn.commit()
    conn.close()


def check_username_exists(username: str) -> bool:
    conn = _get_conn()
    row = conn.execute(
        "SELECT 1 FROM projects WHERE username = ? LIMIT 1",
        (username,),
    ).fetchone()
    conn.close()
    return row is not None
```

- [ ] **Step 2: Verify the module imports cleanly**

Run: `cd /Users/mohammadshweiki/Downloads/Iztech/etl_studio/backend && python -c "from db import init_db; init_db(); print('OK')"`
Expected: `OK` and `data/etl_studio.db` file created.

- [ ] **Step 3: Commit**

```bash
git add backend/db.py
git commit -m "feat: add SQLite database layer for project management"
```

---

## Task 2: Project State Persistence

**Files:**
- Create: `backend/project_state.py`

- [ ] **Step 1: Create `backend/project_state.py`**

```python
import json
import os
from core.extractor import Extractor
from core.transformer import Transformer

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

# Keys from the session dict that get persisted to state.json
# (everything except row data, class instances, and file metadata)
PERSIST_KEYS = [
    "phase",
    "ddl_schema",
    "applied_ddl",
    "config",
    "validation",
    "load_result",
    "pre_extract",
]


def project_dir(project_id: str) -> str:
    return os.path.join(DATA_DIR, "projects", project_id)


def project_uploads_dir(project_id: str) -> str:
    return os.path.join(project_dir(project_id), "uploads")


def project_outputs_dir(project_id: str) -> str:
    return os.path.join(project_dir(project_id), "outputs")


def state_path(project_id: str) -> str:
    return os.path.join(project_dir(project_id), "state.json")


def ensure_project_dirs(project_id: str) -> None:
    os.makedirs(project_uploads_dir(project_id), exist_ok=True)
    os.makedirs(project_outputs_dir(project_id), exist_ok=True)


def save_state(project_id: str, session: dict) -> None:
    """Extract persistable fields from the in-memory session and write state.json."""
    state = {}
    for key in PERSIST_KEYS:
        if key in session:
            state[key] = session[key]
    with open(state_path(project_id), "w") as f:
        json.dump(state, f, indent=2, default=str)


def load_state(project_id: str) -> dict:
    """Read state.json, re-extract from source files, merge saved state on top.

    Returns a fully hydrated session dict ready to be placed into the sessions store.
    """
    sp = state_path(project_id)
    saved = {}
    if os.path.exists(sp):
        with open(sp) as f:
            saved = json.load(f)

    uploads_dir = project_uploads_dir(project_id)
    session: dict = {}

    # Re-extract from source files
    if os.path.isdir(uploads_dir) and os.listdir(uploads_dir):
        extractor = Extractor(uploads_dir)
        raw = extractor.extract_all()
        session["extractor"] = extractor
        session["raw"] = raw
        session["files"] = [
            {
                "name": fname,
                "path": os.path.join(uploads_dir, fname),
                "size": os.path.getsize(os.path.join(uploads_dir, fname)),
            }
            for fname in os.listdir(uploads_dir)
        ]
    else:
        session["raw"] = {"tables": {}, "schema": {}, "stats": {}, "preview": {}}
        session["files"] = []

    # Restore saved state on top
    for key in PERSIST_KEYS:
        if key in saved:
            session[key] = saved[key]

    # If DDL was applied, re-apply DDL schema overrides onto the extracted schema
    if session.get("applied_ddl") and session.get("ddl_schema"):
        for table in session["applied_ddl"]:
            if table in session["ddl_schema"]:
                session["raw"].setdefault("schema", {})[table] = session["ddl_schema"][table]

    # If phase is past transform, re-run transformer to rebuild transformed data
    phase = saved.get("phase", "upload")
    phase_order = ["upload", "edit", "configure", "validate", "transform", "load", "stats"]
    if phase in phase_order and phase_order.index(phase) >= phase_order.index("transform"):
        config = session.get("config", {})
        transformer = Transformer(session["raw"], config)
        result = transformer.run()
        session["transformed"] = result
        session["transformer"] = transformer

    return session


def delete_project_files(project_id: str) -> None:
    """Remove the entire project directory from disk."""
    import shutil
    pdir = project_dir(project_id)
    if os.path.isdir(pdir):
        shutil.rmtree(pdir)
```

- [ ] **Step 2: Verify the module imports cleanly**

Run: `cd /Users/mohammadshweiki/Downloads/Iztech/etl_studio/backend && python -c "from project_state import save_state, load_state; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/project_state.py
git commit -m "feat: add project state persistence (save/load state.json)"
```

---

## Task 3: Project Pydantic Models

**Files:**
- Create: `backend/models/project_schemas.py`

- [ ] **Step 1: Create `backend/models/project_schemas.py`**

```python
from pydantic import BaseModel
from typing import Optional


class CreateProjectRequest(BaseModel):
    name: str
    username: str


class RenameProjectRequest(BaseModel):
    name: str


class ProjectResponse(BaseModel):
    id: str
    name: str
    username: str
    phase: str
    created_at: str
    updated_at: str


class ProjectListResponse(BaseModel):
    projects: list[ProjectResponse]


class ResumeProjectResponse(BaseModel):
    session_id: str
    project: ProjectResponse
    phase: str
    # The rest of the pipeline state is returned as untyped dicts
    # since it varies by phase
    files: list[dict]
    preview: dict
    inferred_schema: dict
    stats: dict
    ddl_schema: dict
    config: Optional[dict] = None
    validation: Optional[dict] = None
    transform: Optional[dict] = None
    load_result: Optional[dict] = None
```

- [ ] **Step 2: Commit**

```bash
git add backend/models/project_schemas.py
git commit -m "feat: add Pydantic models for project API"
```

---

## Task 4: Backend API Endpoints for Projects

**Files:**
- Modify: `backend/main.py`

This is the largest task. It adds project CRUD endpoints, the resume/save endpoints, and auto-save hooks to existing pipeline endpoints.

- [ ] **Step 1: Add imports and init_db call at startup**

At the top of `backend/main.py`, add these imports after the existing ones:

```python
from db import init_db, create_project, list_projects, get_project, rename_project, delete_project, update_project_phase
from project_state import (
    save_state,
    load_state,
    ensure_project_dirs,
    project_uploads_dir,
    project_outputs_dir,
    delete_project_files,
)
from models.project_schemas import (
    CreateProjectRequest,
    RenameProjectRequest,
    ProjectResponse,
    ProjectListResponse,
    ResumeProjectResponse,
)
```

Add after `os.makedirs(OUTPUT_DIR, exist_ok=True)`:

```python
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
GUEST_DIR = os.path.join(DATA_DIR, "guest")
os.makedirs(GUEST_DIR, exist_ok=True)
init_db()
```

- [ ] **Step 2: Add auto-save helper function**

Add this helper after the `sessions` dict definition:

```python
def _auto_save(session_id: str, phase: str) -> None:
    """If the session is linked to a project, persist state and update phase."""
    s = sessions.get(session_id)
    if not s or not s.get("project_id"):
        return
    project_id = s["project_id"]
    s["phase"] = phase
    save_state(project_id, s)
    update_project_phase(project_id, phase)
```

- [ ] **Step 3: Add project CRUD endpoints**

Add these endpoints after the `health` endpoint:

```python
@app.post("/api/projects", response_model=ProjectResponse)
async def create_project_endpoint(body: CreateProjectRequest):
    try:
        project = create_project(body.name, body.username)
    except ValueError as e:
        raise HTTPException(409, str(e))
    ensure_project_dirs(project["id"])
    return ProjectResponse(**project)


@app.get("/api/projects", response_model=ProjectListResponse)
async def list_projects_endpoint(username: str):
    projects = list_projects(username)
    return ProjectListResponse(projects=[ProjectResponse(**p) for p in projects])


@app.get("/api/projects/{project_id}", response_model=ProjectResponse)
async def get_project_endpoint(project_id: str):
    project = get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return ProjectResponse(**project)


@app.patch("/api/projects/{project_id}", response_model=ProjectResponse)
async def rename_project_endpoint(project_id: str, body: RenameProjectRequest):
    try:
        rename_project(project_id, body.name)
    except ValueError as e:
        raise HTTPException(409, str(e))
    project = get_project(project_id)
    return ProjectResponse(**project)


@app.delete("/api/projects/{project_id}")
async def delete_project_endpoint(project_id: str):
    project = get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    # Remove from in-memory sessions if loaded
    to_remove = [sid for sid, s in sessions.items() if s.get("project_id") == project_id]
    for sid in to_remove:
        del sessions[sid]
    delete_project_files(project_id)
    delete_project(project_id)
    return {"ok": True}
```

- [ ] **Step 4: Add resume and save endpoints**

```python
@app.post("/api/projects/{project_id}/resume")
async def resume_project(project_id: str):
    project = get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    session_id = str(uuid.uuid4())
    session = load_state(project_id)
    session["project_id"] = project_id
    sessions[session_id] = session

    raw = session.get("raw", {})
    return {
        "session_id": session_id,
        "project": project,
        "phase": project["phase"],
        "files": session.get("files", []),
        "preview": raw.get("preview", {}),
        "inferred_schema": raw.get("schema", {}),
        "stats": raw.get("stats", {}),
        "ddl_schema": session.get("ddl_schema", {}),
        "config": session.get("config"),
        "validation": session.get("validation"),
        "transform": session.get("transformed"),
        "load_result": session.get("load_result"),
    }


@app.post("/api/projects/{project_id}/save")
async def save_project(project_id: str):
    project = get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    # Find the active session for this project
    session = None
    for s in sessions.values():
        if s.get("project_id") == project_id:
            session = s
            break
    if not session:
        raise HTTPException(400, "No active session for this project")
    save_state(project_id, session)
    return {"ok": True}
```

- [ ] **Step 5: Modify upload endpoints to support project_id**

Update `pre_extract` to accept optional `project_id` form field and use project directory:

In the `pre_extract` function, after `session_id = str(uuid.uuid4())`, add logic to choose directory:

```python
# After: session_id = str(uuid.uuid4())
# Add project_id parameter to function signature: project_id: str | None = Form(None)
# Then:
if project_id:
    session_dir = project_uploads_dir(project_id)
    os.makedirs(session_dir, exist_ok=True)
else:
    session_dir = os.path.join(GUEST_DIR, session_id)
    os.makedirs(session_dir, exist_ok=True)
```

In the session dict assignment, add `"project_id": project_id`.

Same pattern for `upload_files` — add optional `project_id: str | None = Form(None)` parameter, choose directory accordingly, and tag the session.

For `upload_files`, since it uses `File(...)`, the `project_id` must be sent as a form field:

```python
@app.post("/api/upload")
async def upload_files(files: List[UploadFile] = File(...), project_id: str | None = Form(None)):
    session_id = str(uuid.uuid4())
    if project_id:
        session_dir = project_uploads_dir(project_id)
    else:
        session_dir = os.path.join(GUEST_DIR, session_id)
    os.makedirs(session_dir, exist_ok=True)
    # ... rest stays the same, but add to session dict:
    # "project_id": project_id,
```

- [ ] **Step 6: Add auto-save hooks to existing pipeline endpoints**

Add `_auto_save(session_id, "<phase>")` call at the end of each pipeline endpoint, just before the return:

| Endpoint | Phase string |
|---|---|
| `upload_files` (after session creation) | `"edit"` |
| `pre_extract` (after session creation) | `"pre-extract"` |
| `pre_extract_select` | `"edit"` |
| `save_table_data` | `"edit"` |
| `configure` | `"configure"` |
| `validate` | `"validate"` |
| `transform` | `"transform"` |
| `load` | `"load"` |

Example for `configure`:
```python
@app.post("/api/configure/{session_id}", response_model=ConfigureResponse)
async def configure(session_id: str, body: ConfigureRequest):
    if session_id not in sessions:
        raise HTTPException(404, "Session not found")
    sessions[session_id]["config"] = body.dict()
    _auto_save(session_id, "configure")
    return ConfigureResponse(ok=True, message="Configuration saved")
```

- [ ] **Step 7: Update output directory for load endpoint**

In the `load` endpoint, use project output dir when the session is linked to a project:

```python
s = sessions[session_id]
if s.get("project_id"):
    out_dir = project_outputs_dir(s["project_id"])
else:
    out_dir = os.path.join(OUTPUT_DIR, session_id)
os.makedirs(out_dir, exist_ok=True)
```

- [ ] **Step 8: Verify server starts**

Run: `cd /Users/mohammadshweiki/Downloads/Iztech/etl_studio/backend && python -c "from main import app; print('OK')"`
Expected: `OK`

- [ ] **Step 9: Commit**

```bash
git add backend/main.py backend/models/project_schemas.py
git commit -m "feat: add project API endpoints and auto-save hooks"
```

---

## Task 5: Frontend TypeScript Types and API Client

**Files:**
- Create: `frontend/src/types/project.ts`
- Create: `frontend/src/api/projects.ts`
- Modify: `frontend/src/api/client.ts`

- [ ] **Step 1: Create `frontend/src/types/project.ts`**

```typescript
export interface Project {
  id: string
  name: string
  username: string
  phase: string
  created_at: string
  updated_at: string
}

export interface ResumeResponse {
  session_id: string
  project: Project
  phase: string
  files: { name: string; path: string; size: number }[]
  preview: Record<string, Record<string, unknown>[]>
  inferred_schema: Record<string, Record<string, import('./api').ColumnSchema>>
  stats: Record<string, { row_count: number }>
  ddl_schema: Record<string, Record<string, import('./api').ColumnSchema>>
  config: Record<string, unknown> | null
  validation: Record<string, unknown> | null
  transform: Record<string, unknown> | null
  load_result: Record<string, unknown> | null
}
```

- [ ] **Step 2: Create `frontend/src/api/projects.ts`**

```typescript
import axios from 'axios'
import type { Project, ResumeResponse } from '../types/project'

const api = axios.create({ baseURL: '/api' })

api.interceptors.response.use(
  (res) => res,
  (err) => {
    const message = err.response?.data?.detail ?? err.message
    return Promise.reject(new Error(message))
  },
)

export async function createProject(name: string, username: string): Promise<Project> {
  const { data } = await api.post<Project>('/projects', { name, username })
  return data
}

export async function listProjects(username: string): Promise<Project[]> {
  const { data } = await api.get<{ projects: Project[] }>('/projects', { params: { username } })
  return data.projects
}

export async function getProject(projectId: string): Promise<Project> {
  const { data } = await api.get<Project>(`/projects/${projectId}`)
  return data
}

export async function renameProject(projectId: string, name: string): Promise<Project> {
  const { data } = await api.patch<Project>(`/projects/${projectId}`, { name })
  return data
}

export async function deleteProject(projectId: string): Promise<void> {
  await api.delete(`/projects/${projectId}`)
}

export async function resumeProject(projectId: string): Promise<ResumeResponse> {
  const { data } = await api.post<ResumeResponse>(`/projects/${projectId}/resume`)
  return data
}

export async function saveProject(projectId: string): Promise<void> {
  await api.post(`/projects/${projectId}/save`)
}
```

- [ ] **Step 3: Update `frontend/src/api/client.ts` to support project_id**

Modify `uploadFiles` to accept optional `projectId`:

```typescript
export async function uploadFiles(files: File[], projectId?: string): Promise<UploadResponse> {
  const form = new FormData()
  for (const f of files) form.append('files', f)
  if (projectId) form.append('project_id', projectId)
  const { data } = await api.post<UploadResponse>('/upload', form)
  return data
}
```

Modify `preExtract` to accept optional `projectId`:

```typescript
export async function preExtract(
  file: File,
  password?: string,
  onProgress?: (percent: number) => void,
  projectId?: string,
): Promise<PreExtractResponse> {
  const form = new FormData()
  form.append('file', file)
  if (password) form.append('password', password)
  if (projectId) form.append('project_id', projectId)
  const { data } = await api.post<PreExtractResponse>('/pre-extract', form, {
    onUploadProgress: (e) => {
      if (onProgress && e.total) {
        onProgress(Math.round((e.loaded / e.total) * 100))
      }
    },
  })
  return data
}
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/types/project.ts frontend/src/api/projects.ts frontend/src/api/client.ts
git commit -m "feat: add frontend project types and API client"
```

---

## Task 6: Update Pipeline Store for Projects

**Files:**
- Modify: `frontend/src/store/pipeline.tsx`

- [ ] **Step 1: Add project fields to PipelineState and new actions**

Add to `PipelineState`:

```typescript
mode: 'landing' | 'project' | 'guest'
projectId: string | null
projectName: string | null
```

Add to `Action` union:

```typescript
| { type: 'SET_PROJECT'; projectId: string; projectName: string }
| { type: 'START_GUEST' }
| { type: 'RESTORE_PROJECT'; projectId: string; projectName: string; sessionId: string; phase: Phase; uploadResult: UploadResponse | null; configureResult: ConfigureResponse | null; validateResult: ValidateResponse | null; transformResult: TransformResponse | null; loadResult: LoadResponse | null; statsResult: StatsResponse | null }
```

Update `initialState`:

```typescript
const initialState: PipelineState = {
  mode: 'landing',
  phase: 'pre-extract',
  sessionId: null,
  projectId: null,
  projectName: null,
  preExtractResult: null,
  uploadResult: null,
  configureResult: null,
  validateResult: null,
  transformResult: null,
  loadResult: null,
  statsResult: null,
  loading: false,
  error: null,
}
```

Add reducer cases:

```typescript
case 'SET_PROJECT':
  return { ...state, mode: 'project', projectId: action.projectId, projectName: action.projectName, phase: 'pre-extract' }
case 'START_GUEST':
  return { ...state, mode: 'guest', phase: 'pre-extract' }
case 'RESTORE_PROJECT':
  return {
    ...state,
    mode: 'project',
    projectId: action.projectId,
    projectName: action.projectName,
    sessionId: action.sessionId,
    phase: action.phase,
    uploadResult: action.uploadResult,
    configureResult: action.configureResult,
    validateResult: action.validateResult,
    transformResult: action.transformResult,
    loadResult: action.loadResult,
    statsResult: action.statsResult,
    loading: false,
    error: null,
  }
case 'RESET':
  return initialState
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/store/pipeline.tsx
git commit -m "feat: add project/guest mode and restore action to pipeline store"
```

---

## Task 7: Landing Page Component

**Files:**
- Create: `frontend/src/components/LandingPage.tsx`

- [ ] **Step 1: Create the landing page with three cards**

The landing page has three sections:

1. **Create Project** — form with username + project name inputs, submit calls `createProject` API, then dispatches `SET_PROJECT`
2. **Open Project** — username input, on submit fetches `listProjects`, shows table of projects with name, phase badge, last updated. Click a row to resume. Each row has rename (inline edit) and delete (with confirmation) buttons.
3. **Guest Session** — single button, dispatches `START_GUEST`

```typescript
import { useState } from 'react'
import { usePipeline, type Phase } from '../store/pipeline'
import { createProject, listProjects, resumeProject, renameProject, deleteProject } from '../api/projects'
import type { Project } from '../types/project'
import type { UploadResponse, ValidateResponse, TransformResponse, LoadResponse } from '../types/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Spinner } from '@/components/ui'
import { FolderPlus, FolderOpen, Zap, Trash2, Pencil, Check, X } from 'lucide-react'

export default function LandingPage() {
  const { dispatch } = usePipeline()
  const [tab, setTab] = useState<'create' | 'open' | null>(null)

  // Create project state
  const [createUsername, setCreateUsername] = useState('')
  const [createName, setCreateName] = useState('')
  const [createError, setCreateError] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)

  // Open project state
  const [openUsername, setOpenUsername] = useState('')
  const [projects, setProjects] = useState<Project[]>([])
  const [loadingProjects, setLoadingProjects] = useState(false)
  const [projectsLoaded, setProjectsLoaded] = useState(false)
  const [openError, setOpenError] = useState<string | null>(null)
  const [resuming, setResuming] = useState<string | null>(null)

  // Rename state
  const [renamingId, setRenamingId] = useState<string | null>(null)
  const [renameValue, setRenameValue] = useState('')

  async function handleCreate() {
    if (!createUsername.trim() || !createName.trim()) return
    setCreating(true)
    setCreateError(null)
    try {
      const project = await createProject(createName.trim(), createUsername.trim())
      dispatch({ type: 'SET_PROJECT', projectId: project.id, projectName: project.name })
    } catch (e: any) {
      setCreateError(e.message)
    } finally {
      setCreating(false)
    }
  }

  async function handleLoadProjects() {
    if (!openUsername.trim()) return
    setLoadingProjects(true)
    setOpenError(null)
    try {
      const list = await listProjects(openUsername.trim())
      setProjects(list)
      setProjectsLoaded(true)
    } catch (e: any) {
      setOpenError(e.message)
    } finally {
      setLoadingProjects(false)
    }
  }

  async function handleResume(project: Project) {
    setResuming(project.id)
    setOpenError(null)
    try {
      const res = await resumeProject(project.id)
      dispatch({
        type: 'RESTORE_PROJECT',
        projectId: project.id,
        projectName: project.name,
        sessionId: res.session_id,
        phase: res.phase as Phase,
        uploadResult: res.files.length > 0 ? {
          session_id: res.session_id,
          files: res.files,
          preview: res.preview,
          inferred_schema: res.inferred_schema,
          stats: res.stats,
          ddl_schema: res.ddl_schema,
        } as UploadResponse : null,
        configureResult: res.config ? { ok: true, message: 'Restored' } : null,
        validateResult: res.validation as ValidateResponse | null,
        transformResult: res.transform as TransformResponse | null,
        loadResult: res.load_result as LoadResponse | null,
        statsResult: null,
      })
    } catch (e: any) {
      setOpenError(e.message)
    } finally {
      setResuming(null)
    }
  }

  async function handleRename(projectId: string) {
    if (!renameValue.trim()) return
    try {
      await renameProject(projectId, renameValue.trim())
      setProjects(projects.map(p => p.id === projectId ? { ...p, name: renameValue.trim() } : p))
      setRenamingId(null)
    } catch (e: any) {
      setOpenError(e.message)
    }
  }

  async function handleDelete(projectId: string) {
    try {
      await deleteProject(projectId)
      setProjects(projects.filter(p => p.id !== projectId))
    } catch (e: any) {
      setOpenError(e.message)
    }
  }

  return (
    <div className="min-h-screen flex flex-col items-center justify-center relative px-4">
      <div className="pointer-events-none fixed inset-0 z-[1]">
        {/* LiquidEther background will be rendered by parent */}
      </div>
      <div className="pointer-events-none fixed inset-0 z-[2] bg-background/50" />

      <div className="relative z-[5] w-full max-w-4xl space-y-8">
        <div className="text-center space-y-2">
          <div className="flex items-center justify-center gap-3 mb-4">
            <span className="inline-flex items-center justify-center w-10 h-10 rounded-md bg-primary text-primary-foreground text-lg font-bold">
              E
            </span>
            <h1 className="text-3xl font-bold text-foreground tracking-tight">ETL Studio</h1>
          </div>
          <p className="text-muted-foreground text-sm">Data Pipeline Toolkit</p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {/* Create Project */}
          <Card
            className={`cursor-pointer transition-all hover:border-primary/40 hover:shadow-md ${tab === 'create' ? 'border-primary shadow-md' : ''}`}
            onClick={() => setTab('create')}
          >
            <CardHeader className="pb-2">
              <CardTitle className="flex items-center gap-2 text-base">
                <FolderPlus className="h-5 w-5 text-primary" />
                Create Project
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-xs text-muted-foreground">Start a new ETL project with saved progress</p>
            </CardContent>
          </Card>

          {/* Open Project */}
          <Card
            className={`cursor-pointer transition-all hover:border-primary/40 hover:shadow-md ${tab === 'open' ? 'border-primary shadow-md' : ''}`}
            onClick={() => setTab('open')}
          >
            <CardHeader className="pb-2">
              <CardTitle className="flex items-center gap-2 text-base">
                <FolderOpen className="h-5 w-5 text-accent" />
                Open Project
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-xs text-muted-foreground">Resume an existing project where you left off</p>
            </CardContent>
          </Card>

          {/* Guest Session */}
          <Card
            className="cursor-pointer transition-all hover:border-primary/40 hover:shadow-md"
            onClick={() => dispatch({ type: 'START_GUEST' })}
          >
            <CardHeader className="pb-2">
              <CardTitle className="flex items-center gap-2 text-base">
                <Zap className="h-5 w-5 text-yellow-500" />
                Guest Session
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-xs text-muted-foreground">Quick session without saving — data lost on close</p>
            </CardContent>
          </Card>
        </div>

        {/* Create Project Form */}
        {tab === 'create' && (
          <Card>
            <CardContent className="pt-6 space-y-4">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label className="text-sm font-medium text-foreground block mb-1">Username</label>
                  <input
                    type="text"
                    value={createUsername}
                    onChange={e => setCreateUsername(e.target.value)}
                    placeholder="your-username"
                    className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/50"
                  />
                </div>
                <div>
                  <label className="text-sm font-medium text-foreground block mb-1">Project Name</label>
                  <input
                    type="text"
                    value={createName}
                    onChange={e => setCreateName(e.target.value)}
                    placeholder="my-etl-project"
                    className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/50"
                  />
                </div>
              </div>
              {createError && <p className="text-sm text-red-500">{createError}</p>}
              <button
                onClick={handleCreate}
                disabled={creating || !createUsername.trim() || !createName.trim()}
                className="px-4 py-2 rounded-md bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {creating ? 'Creating...' : 'Create Project'}
              </button>
            </CardContent>
          </Card>
        )}

        {/* Open Project Form */}
        {tab === 'open' && (
          <Card>
            <CardContent className="pt-6 space-y-4">
              <div className="flex gap-2">
                <input
                  type="text"
                  value={openUsername}
                  onChange={e => { setOpenUsername(e.target.value); setProjectsLoaded(false) }}
                  placeholder="Enter your username"
                  className="flex-1 rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/50"
                  onKeyDown={e => e.key === 'Enter' && handleLoadProjects()}
                />
                <button
                  onClick={handleLoadProjects}
                  disabled={loadingProjects || !openUsername.trim()}
                  className="px-4 py-2 rounded-md bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {loadingProjects ? 'Loading...' : 'Load'}
                </button>
              </div>

              {openError && <p className="text-sm text-red-500">{openError}</p>}

              {projectsLoaded && projects.length === 0 && (
                <p className="text-sm text-muted-foreground text-center py-4">No projects found for this username</p>
              )}

              {projects.length > 0 && (
                <div className="rounded-md border border-border overflow-hidden">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="bg-muted/50 border-b border-border">
                        <th className="px-3 py-2 text-left text-xs font-semibold text-muted-foreground">Project</th>
                        <th className="px-3 py-2 text-left text-xs font-semibold text-muted-foreground">Phase</th>
                        <th className="px-3 py-2 text-left text-xs font-semibold text-muted-foreground">Last Updated</th>
                        <th className="px-3 py-2 text-right text-xs font-semibold text-muted-foreground">Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {projects.map(p => (
                        <tr
                          key={p.id}
                          className="border-b border-border/40 last:border-0 hover:bg-accent/10 transition-colors cursor-pointer"
                          onClick={() => !renamingId && handleResume(p)}
                        >
                          <td className="px-3 py-2 font-medium text-foreground">
                            {renamingId === p.id ? (
                              <div className="flex items-center gap-1" onClick={e => e.stopPropagation()}>
                                <input
                                  type="text"
                                  value={renameValue}
                                  onChange={e => setRenameValue(e.target.value)}
                                  className="rounded border border-border bg-background px-2 py-1 text-sm w-40"
                                  autoFocus
                                  onKeyDown={e => { if (e.key === 'Enter') handleRename(p.id); if (e.key === 'Escape') setRenamingId(null) }}
                                />
                                <button onClick={() => handleRename(p.id)} className="p-1 text-green-500 hover:text-green-400"><Check className="h-3 w-3" /></button>
                                <button onClick={() => setRenamingId(null)} className="p-1 text-muted-foreground hover:text-foreground"><X className="h-3 w-3" /></button>
                              </div>
                            ) : p.name}
                          </td>
                          <td className="px-3 py-2">
                            <Badge variant="secondary" className="text-xs">{p.phase}</Badge>
                          </td>
                          <td className="px-3 py-2 text-muted-foreground text-xs">
                            {new Date(p.updated_at).toLocaleDateString()}
                          </td>
                          <td className="px-3 py-2 text-right" onClick={e => e.stopPropagation()}>
                            <div className="flex items-center justify-end gap-1">
                              {resuming === p.id && <Spinner size="sm" />}
                              <button
                                onClick={() => { setRenamingId(p.id); setRenameValue(p.name) }}
                                className="p-1 text-muted-foreground hover:text-foreground"
                                title="Rename"
                              >
                                <Pencil className="h-3 w-3" />
                              </button>
                              <button
                                onClick={() => { if (confirm(`Delete project "${p.name}"?`)) handleDelete(p.id) }}
                                className="p-1 text-muted-foreground hover:text-red-500"
                                title="Delete"
                              >
                                <Trash2 className="h-3 w-3" />
                              </button>
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/LandingPage.tsx
git commit -m "feat: add landing page with create/open project and guest session"
```

---

## Task 8: Update App.tsx for Landing Page and Project Header

**Files:**
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Update App.tsx to show landing page or pipeline based on mode**

Replace the current `PipelineApp` component:

```typescript
import { useState } from "react";
import { PipelineProvider, usePipeline } from "./store/pipeline";
import { ProgressSteps } from "./components/ui";
import LiquidEther from "./components/ui/LiquidEther";
import { Separator } from "@/components/ui/separator";
import PreExtractPhase from "./components/PreExtractPhase";
import UploadPhase from "./components/UploadPhase";
import EditPhase from "./components/EditPhase";
import ConfigurePhase from "./components/ConfigurePhase";
import ValidatePhase from "./components/ValidatePhase";
import TransformPhase from "./components/TransformPhase";
import LoadPhase from "./components/LoadPhase";
import StatsPhase from "./components/StatsPhase";
import LandingPage from "./components/LandingPage";
import { saveProject } from "./api/projects";
import type { Phase } from "./store/pipeline";

const PHASE_COMPONENTS: Record<Phase, () => JSX.Element> = {
  "pre-extract": PreExtractPhase,
  upload: UploadPhase,
  edit: EditPhase,
  configure: ConfigurePhase,
  validate: ValidatePhase,
  transform: TransformPhase,
  load: LoadPhase,
  stats: StatsPhase,
};

function PipelineApp() {
  const { state, dispatch } = usePipeline();
  const [saving, setSaving] = useState(false);

  if (state.mode === "landing") {
    return (
      <>
        <div className="pointer-events-none fixed inset-0 z-[1]">
          <LiquidEther
            colors={["#1E3A8A", "#3B82F6", "#60A5FA"]}
            mouseForce={50}
            cursorSize={150}
            resolution={0.5}
            isBounce={true}
            autoDemo={true}
            autoSpeed={1.4}
            autoIntensity={5.0}
            takeoverDuration={0.2}
            autoResumeDelay={1500}
            autoRampDuration={0.4}
          />
        </div>
        <div className="pointer-events-none fixed inset-0 z-[2] bg-background/50" />
        <LandingPage />
      </>
    );
  }

  const PhaseComponent = PHASE_COMPONENTS[state.phase];

  async function handleSave() {
    if (!state.projectId) return;
    setSaving(true);
    try {
      await saveProject(state.projectId);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="min-h-screen flex flex-col relative">
      <div className="pointer-events-none fixed inset-0 z-[1]">
        <LiquidEther
          colors={["#1E3A8A", "#3B82F6", "#60A5FA"]}
          mouseForce={50}
          cursorSize={150}
          resolution={0.5}
          isBounce={true}
          autoDemo={true}
          autoSpeed={1.4}
          autoIntensity={5.0}
          takeoverDuration={0.2}
          autoResumeDelay={1500}
          autoRampDuration={0.4}
        />
      </div>
      <div className="pointer-events-none fixed inset-0 z-[2] bg-background/50" />

      <header className="sticky top-0 z-10 bg-background/80 backdrop-blur-sm border-b border-border">
        <div className="max-w-5xl mx-auto px-6 py-4">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-3">
              <span className="inline-flex items-center justify-center w-8 h-8 rounded-md bg-primary text-primary-foreground text-sm font-bold">
                E
              </span>
              <h1 className="text-lg font-bold text-foreground tracking-tight">
                ETL Studio
              </h1>
              {state.projectName && (
                <span className="text-sm text-accent font-medium">
                  / {state.projectName}
                </span>
              )}
            </div>
            <div className="flex items-center gap-3">
              {state.mode === 'project' && (
                <button
                  onClick={handleSave}
                  disabled={saving}
                  className="px-3 py-1.5 rounded-md border border-border text-xs font-medium text-foreground hover:bg-muted/50 disabled:opacity-50"
                >
                  {saving ? 'Saving...' : 'Save'}
                </button>
              )}
              <button
                onClick={() => dispatch({ type: 'RESET' })}
                className="px-3 py-1.5 rounded-md border border-border text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-muted/50"
              >
                {state.mode === 'project' ? 'Back to Projects' : 'New Session'}
              </button>
              {state.sessionId && state.mode === 'guest' && (
                <span className="text-xs text-muted-foreground">
                  session: <span className="text-accent font-mono">{state.sessionId.slice(0, 8)}</span>
                </span>
              )}
            </div>
          </div>
          <ProgressSteps
            current={state.phase}
            onNavigate={(phase) => dispatch({ type: "GO_TO_PHASE", phase })}
          />
        </div>
      </header>

      <main className="flex-1 max-w-5xl mx-auto w-full px-6 py-8 relative z-[5]">
        <PhaseComponent />
      </main>

      <Separator />
      <footer className="py-3 text-center relative z-[5]">
        <span className="text-xs text-muted-foreground">
          ETL Studio · Data Pipeline Toolkit
        </span>
      </footer>
    </div>
  );
}

export default function App() {
  return (
    <PipelineProvider>
      <PipelineApp />
    </PipelineProvider>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/App.tsx
git commit -m "feat: integrate landing page and project header into App"
```

---

## Task 9: Update Upload Phases to Pass project_id

**Files:**
- Modify: `frontend/src/components/UploadPhase.tsx`
- Modify: `frontend/src/components/PreExtractPhase.tsx`

- [ ] **Step 1: Update UploadPhase to pass projectId**

In `UploadPhase.tsx`, where `uploadFiles(acceptedFiles)` is called, change to:

```typescript
const result = await uploadFiles(acceptedFiles, state.projectId ?? undefined)
```

This requires importing `usePipeline` (likely already imported) and reading `state.projectId`.

- [ ] **Step 2: Update PreExtractPhase to pass projectId**

In `PreExtractPhase.tsx`, where `preExtract(file, password)` is called, change to:

```typescript
const result = await preExtract(file, password || undefined, onProgress, state.projectId ?? undefined)
```

- [ ] **Step 3: Verify the frontend builds**

Run: `cd /Users/mohammadshweiki/Downloads/Iztech/etl_studio/frontend && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/UploadPhase.tsx frontend/src/components/PreExtractPhase.tsx
git commit -m "feat: pass project_id to upload endpoints"
```

---

## Task 10: End-to-End Manual Testing

- [ ] **Step 1: Start backend and frontend**

Run: `cd /Users/mohammadshweiki/Downloads/Iztech/etl_studio && npm run dev`

- [ ] **Step 2: Test guest session flow**

1. Open `http://localhost:5173`
2. Verify landing page appears with three cards
3. Click "Guest Session"
4. Verify the pipeline loads as before (pre-extract phase)
5. Upload a test CSV file, walk through configure/validate/transform/load
6. Click "New Session" to return to landing

- [ ] **Step 3: Test create project flow**

1. Click "Create Project"
2. Enter username "testuser" and project name "my-project"
3. Click "Create Project" button
4. Verify pipeline loads
5. Upload a CSV file, configure columns, run validate
6. Click "Save" button — verify no error
7. Click "Back to Projects" to return to landing

- [ ] **Step 4: Test resume project flow**

1. Click "Open Project"
2. Enter "testuser" and click Load
3. Verify "my-project" appears in the list with phase "validate"
4. Click the project row
5. Verify pipeline loads at the validate phase with data intact

- [ ] **Step 5: Test rename and delete**

1. Go to Open Project, load "testuser" projects
2. Click the rename icon on "my-project", rename to "renamed-project", press Enter
3. Verify name updates
4. Click delete icon, confirm — verify project disappears

- [ ] **Step 6: Test duplicate project name rejection**

1. Create a project "test-dup" for "testuser"
2. Try creating another project "test-dup" for "testuser"
3. Verify error message appears

