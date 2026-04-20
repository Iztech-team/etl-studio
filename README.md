# ETL Studio

A local ETL (Extract, Transform, Load) pipeline tool with a React frontend and FastAPI backend. Drop in CSV, Excel, or SQL dump files — configure, validate, transform, and export clean JSON or SQL output. No destructive database operations. Ever.

---

## Project Structure

```
etl_studio/
├── package.json              # Root scripts — npm run dev starts both FE + BE
├── requirements.txt          # Python dependencies
├── backend/
│   ├── main.py               # FastAPI app + all routes
│   ├── models/
│   │   └── schemas.py        # Pydantic request/response models
│   ├── core/
│   │   ├── extractor.py      # Extractor class
│   │   ├── transformer.py    # Transformer class
│   │   └── loader.py         # Loader class
│   ├── utils/
│   │   ├── sql_parser.py     # SQL dump parser
│   │   ├── encoding.py       # Encoding detection + UTF-8 conversion
│   │   └── stats.py          # Statistics engine
│   ├── uploads/              # Temp storage for uploaded files
│   └── outputs/              # Generated output files land here
└── frontend/
    ├── vite.config.ts        # Vite + proxy to backend on :8000
    ├── tailwind.config.js    # Dark design token system
    └── src/
        ├── main.tsx
        ├── App.tsx
        ├── types/api.ts      # TypeScript mirrors of all Pydantic models
        ├── api/client.ts     # Axios calls for all backend endpoints
        ├── store/pipeline.tsx # Global state via useReducer + Context
        └── components/
            ├── ui/           # Badge, Card, StepBar, StatCard, DataTable, CodeBlock
            └── phases/       # UploadPhase, ConfigurePhase, ValidatePhase,
                              # TransformPhase, LoadPhase, StatsPhase
```

---

## Getting Started

### Prerequisites

- Python 3.10+
- Node.js 18+
- pip

### Install

```bash
# Clone or unzip the project
cd etl_studio

# Install everything
npm run install:all
```

This runs `pip install -r requirements.txt` and `cd frontend && npm install`.

### Run

```bash
npm run dev
```

This starts both servers concurrently:
- **Backend** → `http://localhost:8000`
- **Frontend** → `http://localhost:5173`

---

## Pipeline Stages

### 1. Upload
Drop in one or more files. Supported formats:
- `.csv` — auto-detects encoding
- `.xlsx` / `.xls` — all sheets extracted
- `.sql` — parses `INSERT INTO` statements

Each file becomes one or more named tables. A preview and inferred schema are returned immediately.

### 2. Configure
Review the inferred column types and adjust:
- Rename columns or tables
- Override data types (`string`, `integer`, `float`, `boolean`, `date`)
- Mark columns as excluded
- Set reference maps for value substitution
- Define null representations
- Set load order for referential integrity

### 3. Validate
Runs the full validation suite before any data is changed:
- **Record counts** per table
- **Financial totals** on numeric columns
- **Duplicate detection** (full-row composite key)
- **Truncation risk** — flags any value exceeding 255 characters
- **Spot checks** — first 3 rows of each table for manual review
- Issues are graded `error`, `warning`, or `info`

### 4. Transform
Applies all transformations in order:
1. Encoding detection and UTF-8 conversion (mojibake repair included)
2. Null normalisation against configured null values list
3. Reference mapping (e.g. `"Y" → true`, `"US" → "United States"`)
4. Type coercion to target data types
5. Column renaming and exclusions

A summary reports counts of each transformation type applied.

### 5. Load
Writes output files to `backend/outputs/<session_id>/`. No database writes unless explicitly configured.

**Output formats:**
- `json` — one `.json` file per table + a combined `all_tables.json`
- `sql` — a single `dump.sql` wrapped in `BEGIN` / `COMMIT` with `INSERT INTO` statements

Options:
- `respect_fk_order` — sorts tables alphabetically as a FK-safe load order proxy
- `use_staging` — flag for future staging table support

### 6. Stats Dashboard
Available at any point after upload. Reports:
- Current pipeline stage
- Total records in vs. out
- Per-table row counts, column counts, duplicate counts
- Overall data quality score (starts at 100, penalised per error/warning)

---

## API Reference

All endpoints are prefixed `/api`.

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/upload` | Upload files, returns session_id + preview |
| `POST` | `/configure/{session_id}` | Save column/table configuration |
| `GET` | `/validate/{session_id}` | Run validation suite |
| `GET` | `/transform/{session_id}` | Run transformations |
| `POST` | `/load/{session_id}` | Generate output files |
| `GET` | `/stats/{session_id}` | Get pipeline statistics |
| `GET` | `/download/{session_id}/{filename}` | Download an output file |

---

## Design Principles

- **Non-destructive** — no DROP, DELETE, or TRUNCATE anywhere in the codebase
- **Staging-first** — output files are written locally before any optional DB load
- **Session-isolated** — each upload gets a UUID session; sessions are independent
- **Encoding-safe** — chardet detection on every file; mojibake repair on string values
- **Transparent** — every transformation is counted and reported back to the UI

---

## Frontend Notes (Claude Code Continuation)

The backend is complete. The frontend config is in place (Vite, Tailwind, TypeScript). To finish the frontend in Claude Code, open the project root and prompt:

> "Complete the ETL Studio frontend. Build out `frontend/src/` with: `index.html`, `main.tsx`, `App.tsx`, `types/api.ts`, `api/client.ts`, `store/pipeline.tsx`, `components/ui/index.tsx`, and phase components: `UploadPhase`, `ConfigurePhase`, `ValidatePhase`, `TransformPhase`, `LoadPhase`, `StatsPhase`. Dark theme — acid green (#00ff88) accents on near-black background, JetBrains Mono font, step progress bar at top."

---

## License

MIT
