# ETL Studio

A web-based ETL (Extract, Transform, Load) pipeline tool for migrating legacy databases. Upload CSV, Excel, SQL dumps, or InterBase files — configure schemas, apply advanced transformations, validate data quality, and export clean JSON or SQL output. Built for complex enterprise migrations with full data traceability.

---

## Project Structure

```
etl_studio/
├── package.json              # Root scripts — bun run dev starts both FE + BE
├── requirements.txt          # Python dependencies
├── backend/
│   ├── main.py               # FastAPI app + all routes
│   ├── models/
│   │   └── schemas.py        # Pydantic request/response models
│   ├── core/
│   │   ├── extractor.py      # File parsing, schema inference, validation
│   │   ├── transformer.py    # Column transforms, encoding fixes, mappings
│   │   ├── loader.py         # Output generation (JSON/SQL)
│   │   └── column_transforms.py  # 9+ transform operators
│   ├── utils/
│   │   ├── sql_parser.py     # SQL dump parser (INSERT/CREATE TABLE)
│   │   ├── encoding.py       # Charset detection, mojibake repair
│   │   └── stats.py          # Quality scoring, statistics
│   ├── uploads/              # Temp file storage
│   └── outputs/              # Generated output files
└── frontend/
    ├── vite.config.ts        # Vite + API proxy (:8000)
    ├── tailwind.config.js    # Retro pixel theme
    └── src/retro/
        ├── Pipeline.tsx      # Main pipeline UI + keyboard shortcuts
        ├── Projects.tsx      # Project dashboard, file management
        ├── Auth.tsx          # Session/project context
        └── icons/            # Icon components
```

---

## Getting Started

### Prerequisites

- Python 3.10+
- Bun 1.0+ (or Node.js 18+ as fallback)
- pip

### Install

```bash
cd etl_studio

# Install with Bun
bun run install:all

# Or with npm
npm run install:all
```

Installs Python deps and frontend packages.

### Run

```bash
bun run dev
# or: npm run dev
```

Starts both servers concurrently:
- **Backend** → `http://localhost:8000`
- **Frontend** → `http://localhost:5173`

---

## Core Features

### Upload & Extraction
- **Formats:** CSV (auto-detect encoding), Excel (all sheets), SQL dumps, InterBase (.ib)
- **Streaming:** Large files streamed to avoid memory overload
- **Preview:** Immediate table list with row/column counts
- **Schema Inference:** Type detection (string, integer, float, boolean, date)

### Column Transformations
9 built-in transform operators:
- `normalize_phone` — Standardize phone numbers + 4-tier country code detection
- `detect_country_code` — Fallback resolution (international → prefix table → currency → unresolved)
- `split_name` — Split full name into first/last
- `map_values` — Enum mapping (source value → target value)
- `concat_template` — String templates with row context (e.g., `"Mr. {firstName} {lastName}"`)
- `generate_uuid` — UUID v4 generation
- `default_if_null` — NULL replacement with static/dynamic values
- `conditional` — IF/THEN/ELSE logic based on field values
- `row_number` — Sequential numbering with stateful accumulation

**Transform Context:** Row data, state accumulator, exception tracking, table/column metadata available to all operators.

### Global Column Injection
Automatically inject columns across tables:
- `shopId` — Static shop identifier
- `createdBy` / `updatedBy` — User audit fields
- `migration_source_id` — Source ID traceability
- Per-table inclusion/exclusion rules
- Overwrite or preserve existing values

### Data Quality & Validation
- **Duplicate Detection** — Full-row composite key dedup with counts
- **Truncation Risk** — Flag values exceeding 255 characters
- **Financial Totals** — Sum numeric columns for spot-check audit
- **Arabic Normalization** — Digit conversion (٠-٩ → 0-9)
- **RTL/LTR Markers** — Auto-detect and strip
- **Exception Categorization** — Track review-needed rows by issue type

### Advanced Load Options
- **Counter Resets** — Update AUTO_INCREMENT sequences after load (e.g., `SET counter = MAX(id) + 1`)
- **Post-Load SQL** — Custom SQL after data insert (cleanup, reference data, computed columns)
- **FK-Safe Ordering** — Topological sort of tables by foreign key dependencies
- **ID Mapping** — Track source ID → target ID for traceability
- **Staging Tables** — Two-phase load (insert to staging, then MERGE to target)

### Exception Tracking
- Categorize exceptions during transform (country_code_unresolved, truncation_risk, etc.)
- Per-category CSV export for manual review
- Exception counts in transform stats
- Linked to source rows for follow-up

### Output Formats
- **JSON** — Per-table files + combined `all_tables.json`
- **SQL** — Single `dump.sql` with transaction wrapper, parameterized INSERT statements
- **CSV** — Exception reports grouped by category

### Keyboard Shortcuts
**Extract Phase:**
- `↑ / ↓` — Navigate tables
- `D` / `Space` — Toggle keep/drop table
- `P` — Preview table data
- `E` — Deselect empty tables
- `A` — Toggle all tables

**Transform Phase (Columns):**
- `↑ / ↓` — Navigate columns
- `D` — Toggle DROP
- `C` — Toggle CAST type
- `R` — Focus rename field

**Transform Phase (Tables):**
- `Tab` / `Shift+Tab` — Switch tables
- `Alt+R` — Rename table

### Project Management
- Create multiple migration projects
- Rename projects in-place
- Delete projects (confirmed with themed modal)
- Download output files from project card
- Dashboard stats: total rows migrated, avg quality score

---

## Pipeline Stages

### 1. Upload
Drop files and select tables to migrate. Returns preview, inferred schema, row counts.

### 2. Extract (Pre-Processing)
Review extracted tables. Toggle inclusion, preview data, deselect empty tables.

### 3. Configure
Set column mappings:
- Rename columns/tables
- Override inferred types
- Mark columns to drop/rename/cast
- Define null value representations
- Set load order for referential integrity

### 4. Transform
Apply transformations in order:
1. Encoding detection & UTF-8 conversion (mojibake repair)
2. Null normalization
3. Reference mappings
4. Column transforms (operators chained)
5. Type coercion
6. Global column injection
7. Truncation risk flagging

Reports exception counts per category.

### 5. Load
Write output files (JSON or SQL). Options:
- `counter_resets` — Post-load sequence updates
- `post_load_sql` — Custom SQL hooks
- `use_id_mapping` — Enable temporary ID mapping table (future)
- `respect_fk_order` — Sort by FK dependencies

### 6. Stats
Quality dashboard:
- Overall score (100 - error_penalties - warning_penalties)
- Per-table row counts, duplicates
- Exception summary by category

---

## API Reference

All endpoints prefixed `/api`.

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/upload` | Upload files, extract schema |
| `POST` | `/extract/{session_id}` | Start extraction (async) |
| `GET` | `/extract/{session_id}/stream` | NDJSON event stream |
| `GET` | `/extract/{session_id}/status` | Check extraction status |
| `POST` | `/extract/{session_id}/cancel` | Cancel in-flight extraction |
| `POST` | `/pre-extract-select/{session_id}` | Select tables to keep |
| `POST` | `/configure/{session_id}` | Save column/table config |
| `GET` | `/validate/{session_id}` | Run validation |
| `GET` | `/transform/{session_id}` | Run transform pipeline |
| `POST` | `/load/{session_id}` | Generate output files |
| `GET` | `/stats/{session_id}` | Get quality metrics |
| `GET` | `/download/{session_id}/{filename}` | Download output file |
| `POST` | `/projects` | Create new project |
| `GET` | `/projects` | List user projects |
| `PATCH` | `/projects/{id}` | Rename project |
| `DELETE` | `/projects/{id}` | Delete project |
| `GET` | `/projects/{id}/outputs` | List output files |
| `GET` | `/dashboard-stats` | Global migration stats |

---

## Design Principles

- **Non-destructive** — No DROP, DELETE, TRUNCATE, or direct database writes
- **File-based** — Output written to disk; DB operations optional
- **Session-isolated** — Each upload is a UUID session; independent state
- **Encoding-safe** — chardet detection on all files; mojibake repair on strings
- **Transparent** — Every transformation counted and reported
- **Traceable** — Source ID mapping for audit trail
- **Keyboard-first** — Full UI navigable without mouse

---

## Architecture Notes

### Backend
- **Stateful Sessions:** In-memory session dict (keyed by UUID) tracks extraction, config, transform, load state
- **Streaming Extract:** File parsing on-the-fly; NDJSON events for live progress
- **No DB Dependency:** All output written to `backend/outputs/{session_id}/`
- **SQL Generation:** String-escaped INSERT statements; transaction-wrapped

### Frontend
- **Retro Pixel Theme:** Custom CSS variables for dark/amber/coral palette
- **React + TypeScript:** Context-based state, functional components
- **Keyboard-Driven:** Global event listeners for shortcut dispatch
- **Portal Modals:** All popups (delete, rename, errors) use themed custom modals

---

## Known Limitations & Roadmap

### Missing (Phase 0 - Preprocessing)
- Dedup execution with merge strategies
- Enrichment joins between tables
- Pre-load constraint pre-checks (UNIQUE, NOT NULL)

### Missing (Phase 2 - Matching)
- Deterministic matching DSL (EXACT, FUZZY, TIERED, FIFO)
- Amount splitting across multiple targets
- Synthetic row generation

### Missing (Phase 3 - Validation)
- Post-load FK orphan detection
- Balance reconciliation (AR/AP/cash)
- Circular dependency detection

See `ETL_CAPABILITIES_ROADMAP.md` for full capability matrix.

---

## License

MIT
