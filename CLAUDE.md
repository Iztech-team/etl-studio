# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ETL Studio is a web-based Extract-Transform-Load tool. Users upload data files (CSV, Excel, SQL dumps), configure column mappings and transformations, validate data quality, and export cleaned data as JSON or SQL.

## Commands

```bash
# Install all dependencies (Python + Node)
npm run install:all

# Run both backend and frontend concurrently
npm run dev

# Run backend only (FastAPI on port 8000)
cd backend && uvicorn main:app --reload --port 8000

# Run frontend only (Vite on port 5173)
cd frontend && npm run dev

# Build frontend
cd frontend && npm run build
```

There are no test suites configured.

## Architecture

### Backend (Python / FastAPI)

Stateful session-based API. Sessions are stored **in-memory** in `backend/main.py:sessions` dict, keyed by UUID. Each session tracks its pipeline state through stages: extracted → validated → transformed → loaded.

**Pipeline flow** (each step is a separate API call):

1. `POST /api/upload` → `Extractor.extract_all()` — reads CSV/Excel/SQL files, infers schema, computes basic stats
2. `POST /api/configure/{session_id}` — saves column mappings, type overrides, null values config
3. `GET /api/validate/{session_id}` → `Extractor.validate()` — checks duplicates, truncation risks, financial totals
4. `GET /api/transform/{session_id}` → `Transformer.run()` — encoding fixes, null normalization, type coercion, reference mappings
5. `POST /api/load/{session_id}` → `Loader.run()` — writes JSON files or SQL INSERT dump to `outputs/{session_id}/`
6. `GET /api/download/{session_id}/{filename}` — serves output files

**Key modules:**

- `core/extractor.py` — file parsing (CSV via stdlib, Excel via openpyxl, SQL via custom regex parser), schema inference, validation
- `core/transformer.py` — data cleaning pipeline (encoding fix → null normalization → reference mapping → type coercion)
- `core/loader.py` — output generation (JSON or SQL INSERT statements), no direct DB writes
- `utils/sql_parser.py` — regex-based parser for INSERT and CREATE TABLE statements
- `utils/encoding.py` — charset detection (chardet) and mojibake repair (latin-1 → utf-8 re-encode)
- `utils/stats.py` — computes pipeline statistics and quality score (100 minus penalties for errors/warnings)
- `models/schemas.py` — all Pydantic request/response models

### Frontend (React + TypeScript + Vite + Tailwind)

Single-page app at `frontend/`. Uses axios for API calls. Styled with Tailwind CSS. File uploads via react-dropzone.

### Important Design Decisions

- **No database**: all state lives in the in-memory `sessions` dict — data is lost on server restart
- **File-based output only**: the Loader writes to disk (JSON/SQL files), never connects to a target database
- **CORS**: backend allows only `http://localhost:5173`
- **SQL generation uses string escaping** (`_sql_val` in loader.py) — single-quote escaping only, not parameterized
- **FK ordering** in loader is alphabetical sort (stub), not real dependency resolution
