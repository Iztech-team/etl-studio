# Backend Reorganization Design

Date: 2026-04-27
Branch: `reactor`

## Goals

1. Reorganize backend so business logic doesn't live inside route handlers.
2. Reduce LOC where possible without changing business logic.
3. Make every public function `async def`.

Out of scope: `backend/scripts/` (preset builders), frontend reorg, tests.

## Decisions

- **Service layer**: modules of functions, not classes. No DI, no repositories.
- **Verification**: manual (no test suite).
- **Deletion appetite**: aggressive. Specific deletions greenlit per item.
- **Session state**: wrap in helper module (`state/session_store.py`, `state/extraction_store.py`). Dict still lives module-level; all access goes through named functions.
- **Async policy**: every public function in `api/`, `services/`, `state/`, `persistence/` is `async def`. `core/` public methods are `async def` (CPU work wrapped in `asyncio.to_thread`); private helpers inside core class bodies stay sync to avoid N thread-switches and `_sync` shadow methods. New deps: `aiosqlite`, `aiofiles`.
- **Landing**: incremental commits on `reactor`; one push at the end; user opens PR.

## Removed features

- DDL upload + apply (`/api/upload-ddl/*`, `/api/apply-ddl/*`, frontend DDL UI in `RlExport`, related session keys, `utils/sql_parser.py` DDL parsing).
- Templates (`/api/projects/{pid}/templates/*`, `templates` SQLite table + `init_templates_table`, `frontend/src/retro/Templates.tsx`, templates route + nav).

## File layout

```
backend/
├── main.py                       # ~50 lines: app + router includes + lifespan
├── startup.py                    # NEW: replaces module-load side effects
├── definitions.py                # NEW: every SQL statement + shell command as constant
├── api/                          # NEW: thin async route handlers
│   ├── system.py / projects.py / uploads.py / extract.py
│   ├── tables.py / transform.py / presets.py / load.py
│   ├── downloads.py / dashboard.py
├── services/                     # NEW: async function modules
│   ├── extraction_service.py / transform_service.py / load_service.py
│   ├── project_service.py / preset_service.py
├── state/                        # NEW: in-memory dict wrappers (async API)
│   ├── session_store.py / extraction_store.py
├── persistence/                  # NEW: relocated infra (uses aiosqlite + aiofiles)
│   ├── db.py / project_state.py / presets.py
├── core/                         # REGROUPED by stage
│   ├── extract/{extractor,db_extractor,ib_isql_extract}.py
│   ├── transform/{transformer,column_transforms}.py
│   └── load/loader.py
├── models/                       # unchanged
└── utils/                        # deletion sweep + inline single-callers
```

## Route handler shape (rule for every endpoint)

```python
@router.get("/transform/{session_id}")
async def transform(session_id: str):
    if not await session_store.exists(session_id):
        raise HTTPException(404, "Session not found")
    return await transform_service.run(session_id)
```

Rules:
1. No direct `sessions[sid]` access — only `state.session_store`.
2. No `Transformer`/`Loader`/`Extractor` instantiation — only services.
3. No nested helper functions — promote to private service-module functions.

## Transformer rewrite

- Remove explanatory comments (keep only WHY for non-obvious invariants).
- Split 484-line `run()` into private methods: `_build_fk_graph`, `_index_configs`, `_plan_targets`, `_process_table`, `_process_row`, `_finalize`.
- Collapse 5 separate passes over `table_configs_list` into 1.
- Remove dead branches confirmed unused by current presets.

## `definitions.py` shape

Module-level constants. Importers do `from definitions import GET_PROJECT` and execute via `cur.execute(GET_PROJECT, ...)` or `subprocess.run(ISQL_EXTRACT_CMD, ...)`. Sections: schema setup, project queries, pipeline runs, source-DB extraction queries, shell commands.

## Branch sequence (commits on `reactor`)

Each commit leaves the server working for manual verification.

1. **Frontend cleanup** — delete templates UI, delete DDL UI, remove their API/types.
2. **Backend kill DDL + templates** — delete endpoints, handlers, db init, `utils/sql_parser.py` DDL parts.
3. **`state/`** — `session_store.py` + `extraction_store.py` (async API), migrate every `sessions[sid]` access.
4. **`persistence/`** — relocate `db.py`/`project_state.py`/`presets.py`, swap to `aiosqlite` + `aiofiles`.
5. **`definitions.py`** — extract all SQL + shell-command strings.
6. **`services/`** — move route-handler bodies into service functions; route handlers shrink to the standard 3-line shape.
7. **`core/` regroup** — into `extract/`, `transform/`, `load/` subpackages; `core/` public methods become `async def` with `to_thread` wrappers.
8. **`api/` routers** — split `main.py` into router modules.
9. **`startup.py`** — module-load side effects → FastAPI lifespan hook.
10. **Transformer rewrite** — comment trim + method split + single-pass setup + dead-branch removal.
11. **Final cleanup** — straggler unused imports/files/utilities.

## Frontend cleanup riding along

Required so deleted backend endpoints aren't called:
- Delete `frontend/src/retro/Templates.tsx`.
- Remove `templates` from Route union in `RetroApp.tsx`; remove templates nav in `Topbar.tsx`.
- Remove DDL upload from `RlExport` in `Pipeline.tsx`.
- Remove template + DDL functions from `frontend/src/api/client.ts`; clean `types/api.ts`.

## LOC expectation

- Reductions: dead code, DDL/templates deletion, transformer comment+pass collapse, deletion sweep.
- Additions: async wrappers, router files, service module boilerplate.
- Net: cautiously expect a small reduction; the bigger win is structural, not LOC.
