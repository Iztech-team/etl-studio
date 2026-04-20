# ETL Studio Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the complete ETL Studio frontend — a 6-phase wizard UI with dark theme, acid green accents, and step progress bar.

**Architecture:** Single-page React app using Context for pipeline state. Each pipeline phase is its own component gated by session state. Axios client talks to FastAPI backend through Vite's `/api` proxy.

**Tech Stack:** React 18, TypeScript, Vite, Tailwind CSS, Axios, react-dropzone

---

## File Structure

| File | Responsibility |
|------|---------------|
| `src/types/api.ts` | TypeScript interfaces matching all backend request/response schemas |
| `src/api/client.ts` | Typed axios functions for each endpoint |
| `src/store/pipeline.tsx` | React Context + provider: session state, current phase, API response data |
| `src/components/ui/index.tsx` | Shared primitives: Button, Card, Badge, Spinner, DataTable, ProgressSteps |
| `src/components/UploadPhase.tsx` | Dropzone file upload, file list, schema preview table |
| `src/components/ConfigurePhase.tsx` | Per-table column config: rename, type, include/exclude, null values |
| `src/components/ValidatePhase.tsx` | Run validation, display issues, record counts, duplicates |
| `src/components/TransformPhase.tsx` | Trigger transform, show stats counters, before/after preview |
| `src/components/LoadPhase.tsx` | Format picker (JSON/SQL), run load, download links |
| `src/components/StatsPhase.tsx` | Pipeline summary: quality score, per-table stats, stage indicator |
| `src/App.tsx` | Top-level layout: header, ProgressSteps bar, phase router |
| `src/main.tsx` | React entry point (exists) |
| `src/index.css` | Tailwind directives (exists) |

---

### Task 1: TypeScript Types

**Files:**
- Create: `src/types/api.ts`

- [ ] **Step 1: Create all API types**

Types mirror backend `models/schemas.py` exactly:
- `UploadResponse` (session_id, files[], preview, inferred_schema, stats)
- `ColumnConfig`, `TableConfig`, `ConfigureRequest`, `ConfigureResponse`
- `ValidationIssue`, `ValidateResponse`
- `TransformResponse`
- `LoadRequest`, `LoadResponse`
- `StatsResponse`

---

### Task 2: API Client

**Files:**
- Create: `src/api/client.ts`

- [ ] **Step 1: Create typed axios client**

Functions:
- `uploadFiles(files: File[]): Promise<UploadResponse>` — multipart POST to `/api/upload`
- `configure(sessionId, data): Promise<ConfigureResponse>` — POST `/api/configure/{sessionId}`
- `validate(sessionId): Promise<ValidateResponse>` — GET `/api/validate/{sessionId}`
- `transform(sessionId): Promise<TransformResponse>` — GET `/api/transform/{sessionId}`
- `load(sessionId, data): Promise<LoadResponse>` — POST `/api/load/{sessionId}`
- `stats(sessionId): Promise<StatsResponse>` — GET `/api/stats/{sessionId}`
- `downloadUrl(sessionId, filename): string` — returns URL string

---

### Task 3: Pipeline Store (React Context)

**Files:**
- Create: `src/store/pipeline.tsx`

- [ ] **Step 1: Create PipelineContext and PipelineProvider**

State shape:
```typescript
{
  phase: 'upload' | 'configure' | 'validate' | 'transform' | 'load' | 'stats'
  sessionId: string | null
  uploadResult: UploadResponse | null
  configureResult: ConfigureResponse | null
  validateResult: ValidateResponse | null
  transformResult: TransformResponse | null
  loadResult: LoadResponse | null
  statsResult: StatsResponse | null
  loading: boolean
  error: string | null
}
```

Actions dispatch API calls, store responses, and advance phase on success.

---

### Task 4: Shared UI Components

**Files:**
- Create: `src/components/ui/index.tsx`

- [ ] **Step 1: Build UI primitives**

Components:
- `Button` — acid green bg, ink text, loading spinner state, disabled state
- `Card` — ink-700 bg, ink-600 border, rounded, padding
- `Badge` — color-coded (acid=success, ember=warning, frost=info)
- `Spinner` — acid green animated ring
- `DataTable` — scrollable table with ink-800 header row, alternating row stripes
- `ProgressSteps` — horizontal step bar, 6 steps, acid green for completed/active, ink-500 for pending

---

### Task 5: UploadPhase

**Files:**
- Create: `src/components/UploadPhase.tsx`

- [ ] **Step 1: Build upload phase**

- react-dropzone area with dashed acid border
- Accepted: .csv, .xlsx, .xls, .sql
- On drop: call `uploadFiles`, store result, show file list + inferred schema preview table
- "Continue" button advances to configure phase

---

### Task 6: ConfigurePhase

**Files:**
- Create: `src/components/ConfigurePhase.tsx`

- [ ] **Step 1: Build configure phase**

- Reads `uploadResult.inferred_schema` to list tables and columns
- Per-column row: checkbox (include), source name, target name input, type dropdown (string/integer/float/boolean/date)
- Null values input (comma-separated, prefilled with defaults)
- "Save & Continue" calls `configure` then advances

---

### Task 7: ValidatePhase

**Files:**
- Create: `src/components/ValidatePhase.tsx`

- [ ] **Step 1: Build validate phase**

- "Run Validation" button calls `validate`
- Shows: passed/failed badge, record counts per table, duplicate counts, truncation risks
- Issues list with warning/error badges
- "Continue" button

---

### Task 8: TransformPhase

**Files:**
- Create: `src/components/TransformPhase.tsx`

- [ ] **Step 1: Build transform phase**

- "Run Transform" button calls `transform`
- Stats cards: encoding conversions, type conversions, reference mappings, null normalizations
- Preview table of first 5 rows per transformed table
- Warnings list if any
- "Continue" button

---

### Task 9: LoadPhase

**Files:**
- Create: `src/components/LoadPhase.tsx`

- [ ] **Step 1: Build load phase**

- Format radio: JSON / SQL
- FK order toggle
- "Generate Output" calls `load`
- Shows output file list with download links (`/api/download/{sessionId}/{filename}`)
- "View Stats" button advances to stats

---

### Task 10: StatsPhase

**Files:**
- Create: `src/components/StatsPhase.tsx`

- [ ] **Step 1: Build stats phase**

- Calls `stats` on mount
- Quality score as large number with color coding (>80 acid, >50 ember, else red)
- Pipeline stage badge
- Records in/out counters
- Per-table breakdown: rows in, rows out, columns, duplicates
- "Start Over" button resets pipeline to upload phase

---

### Task 11: App Shell & Integration

**Files:**
- Modify: `src/App.tsx`

- [ ] **Step 1: Wire everything together**

- Wrap in PipelineProvider
- Header with "ETL Studio" branding
- ProgressSteps bar showing current phase
- Render current phase component
- Error toast area for API errors
