# DDL Upload Feature — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow users to upload DDL (CREATE TABLE) SQL files so the app uses declared schema definitions instead of inferring types from data, with original SQL types preserved for accurate SQL output.

**Architecture:** Extend `SQLParser` with a `parse_ddl()` method that extracts table/column/type info from CREATE TABLE statements. Add two new backend endpoints (`upload-ddl`, `apply-ddl`) for configure-phase DDL management. Auto-detect DDL at upload time. Frontend gets a DDL upload section in ConfigurePhase and an info notice in UploadPhase. Loader emits CREATE TABLE when DDL types are available.

**Tech Stack:** Python/FastAPI (backend), React/TypeScript/Tailwind (frontend), regex-based SQL parsing

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `backend/utils/sql_parser.py` | Add `parse_ddl()` method and type normalization mapping |
| Modify | `backend/models/schemas.py` | Add DDL-related Pydantic models and response schemas |
| Modify | `backend/main.py` | Add `upload-ddl` and `apply-ddl` endpoints, extend upload to detect DDL |
| Modify | `backend/core/extractor.py` | Surface DDL schemas from SQL files during extraction |
| Modify | `backend/core/loader.py` | Emit CREATE TABLE using original DDL types in SQL output |
| Modify | `frontend/src/types/api.ts` | Add DDL TypeScript interfaces |
| Modify | `frontend/src/api/client.ts` | Add `uploadDDL()` and `applyDDL()` API functions |
| Modify | `frontend/src/components/UploadPhase.tsx` | Show DDL detection notice |
| Modify | `frontend/src/components/ConfigurePhase.tsx` | Add DDL upload dropzone, table selection, apply flow |

---

### Task 1: DDL Parser — `parse_ddl()` method

**Files:**
- Modify: `backend/utils/sql_parser.py:1-95`

- [ ] **Step 1: Add type normalization mapping**

Add this constant at module level (after the imports, before the class):

```python
# Normalized type mapping: SQL type prefix → internal type
DDL_TYPE_MAP: Dict[str, str] = {
    "varchar": "string",
    "text": "string",
    "char": "string",
    "nvarchar": "string",
    "nchar": "string",
    "clob": "string",
    "character varying": "string",
    "character": "string",
    "int": "integer",
    "integer": "integer",
    "bigint": "integer",
    "smallint": "integer",
    "tinyint": "integer",
    "serial": "integer",
    "bigserial": "integer",
    "decimal": "float",
    "numeric": "float",
    "real": "float",
    "double": "float",
    "double precision": "float",
    "float": "float",
    "money": "float",
    "boolean": "boolean",
    "bool": "boolean",
    "date": "date",
    "datetime": "date",
    "timestamp": "date",
    "timestamptz": "date",
    "time": "date",
}
```

- [ ] **Step 2: Add `_normalize_type` static method to `SQLParser`**

Add after the `_cast` method (after line 94):

```python
@staticmethod
def _normalize_type(raw_type: str) -> str:
    """Map a SQL type like 'VARCHAR(255)' to an internal type like 'string'."""
    # Strip parenthesized precision/length: "DECIMAL(10,2)" → "DECIMAL"
    base = re.sub(r"\(.*\)", "", raw_type).strip().lower()
    # Try exact match first
    if base in DDL_TYPE_MAP:
        return DDL_TYPE_MAP[base]
    # Try prefix match for multi-word types like "double precision"
    for key, val in DDL_TYPE_MAP.items():
        if base.startswith(key):
            return val
    return "string"
```

- [ ] **Step 3: Add `parse_ddl()` method to `SQLParser`**

Add after the `parse()` method (after line 51):

```python
def parse_ddl(self) -> Dict[str, Dict[str, Dict[str, Any]]]:
    """Parse CREATE TABLE statements and return structured schema.

    Returns:
        {
            "table_name": {
                "column_name": {
                    "inferred_type": "float",
                    "original_type": "DECIMAL(10,2)",
                    "nullable": True
                }
            }
        }
    """
    from typing import Any

    result: Dict[str, Dict[str, Dict[str, Any]]] = {}

    # Match CREATE TABLE with multi-dialect identifiers
    create_re = re.compile(
        r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?'
        r'[`"\[\']?(\w+)[`"\]\']?\s*\((.+?)\)\s*[;)]',
        re.IGNORECASE | re.DOTALL,
    )

    for m in create_re.finditer(self.content):
        table_name = m.group(1)
        body = m.group(2)

        columns: Dict[str, Dict[str, Any]] = {}
        for line in body.split(","):
            line = line.strip()
            if not line:
                continue
            # Skip constraints: PRIMARY KEY, FOREIGN KEY, UNIQUE, CHECK, CONSTRAINT, INDEX
            upper = line.upper().lstrip()
            if any(upper.startswith(kw) for kw in (
                "PRIMARY", "FOREIGN", "UNIQUE", "CHECK", "CONSTRAINT", "INDEX", "KEY",
            )):
                continue

            # Parse: [identifier] TYPE [(precision)] [NOT NULL] [DEFAULT ...] [constraints...]
            col_re = re.compile(
                r'[`"\[\']?(\w+)[`"\]\']?\s+'
                r'([A-Za-z][A-Za-z0-9_ ]*(?:\([^)]*\))?)',
                re.IGNORECASE,
            )
            col_match = col_re.match(line)
            if not col_match:
                continue

            col_name = col_match.group(1)
            original_type = col_match.group(2).strip()
            nullable = "NOT NULL" not in line.upper()
            inferred = self._normalize_type(original_type)

            columns[col_name] = {
                "inferred_type": inferred,
                "original_type": original_type,
                "nullable": nullable,
            }

        if columns:
            result[table_name] = columns

    return result
```

- [ ] **Step 4: Verify parse works manually**

Run from the backend directory:

```bash
cd /Users/mohammadshweiki/Downloads/Iztech/etl_studio/backend && python -c "
from utils.sql_parser import SQLParser
ddl = '''
CREATE TABLE products (
    id INT NOT NULL,
    name VARCHAR(255),
    price DECIMAL(10,2) NOT NULL,
    active BOOLEAN,
    created_at TIMESTAMP
);
'''
p = SQLParser(ddl)
import json
print(json.dumps(p.parse_ddl(), indent=2))
"
```

Expected output:
```json
{
  "products": {
    "id": { "inferred_type": "integer", "original_type": "INT", "nullable": false },
    "name": { "inferred_type": "string", "original_type": "VARCHAR(255)", "nullable": true },
    "price": { "inferred_type": "float", "original_type": "DECIMAL(10,2)", "nullable": false },
    "active": { "inferred_type": "boolean", "original_type": "BOOLEAN", "nullable": true },
    "created_at": { "inferred_type": "date", "original_type": "TIMESTAMP", "nullable": true }
  }
}
```

- [ ] **Step 5: Commit**

```bash
git add backend/utils/sql_parser.py
git commit -m "feat: add DDL parser with type normalization to SQLParser"
```

---

### Task 2: Pydantic Models for DDL Endpoints

**Files:**
- Modify: `backend/models/schemas.py:1-86`

- [ ] **Step 1: Add DDL-related models**

Add at the end of `backend/models/schemas.py` (after line 85):

```python
class DDLColumnSchema(BaseModel):
    inferred_type: str
    original_type: str
    nullable: bool


class DDLUploadResponse(BaseModel):
    ok: bool
    ddl_schema: Dict[str, Dict[str, DDLColumnSchema]]
    matching_tables: List[str]


class ApplyDDLRequest(BaseModel):
    tables: List[str]


class ApplyDDLTableResult(BaseModel):
    table: str
    applied: bool
    errors: List[str] = []


class ApplyDDLResponse(BaseModel):
    ok: bool
    results: List[ApplyDDLTableResult]
```

- [ ] **Step 2: Commit**

```bash
git add backend/models/schemas.py
git commit -m "feat: add Pydantic models for DDL upload and apply endpoints"
```

---

### Task 3: Extractor — Surface DDL Schemas from SQL Files

**Files:**
- Modify: `backend/core/extractor.py:67-71`

- [ ] **Step 1: Add DDL storage and extraction**

Add a `_ddl_schema` dict to `__init__` (line 16, after `self._stats`):

```python
self._ddl_schema: Dict[str, Any] = {}
```

- [ ] **Step 2: Update `_extract_sql` to also parse DDL**

Replace the `_extract_sql` method (lines 67-71) with:

```python
def _extract_sql(self, path: str, fname: str):
    content, _enc = detect_and_convert(path)
    parser = SQLParser(content)
    tables = parser.parse()
    self._raw_tables.update(tables)
    # Also extract DDL schemas from CREATE TABLE statements
    ddl = parser.parse_ddl()
    # Only keep DDL for tables that have no data rows (DDL-only files)
    for table_name, columns in ddl.items():
        if table_name not in self._raw_tables or not self._raw_tables[table_name]:
            self._ddl_schema[table_name] = columns
```

- [ ] **Step 3: Include DDL schema in `extract_all` return value**

Update the return dict in `extract_all()` (lines 34-39) to include `ddl_schema`:

```python
return {
    "tables": self._raw_tables,
    "schema": self._schema,
    "stats": self._stats,
    "preview": {t: rows[:5] for t, rows in self._raw_tables.items()},
    "ddl_schema": self._ddl_schema,
}
```

- [ ] **Step 4: Commit**

```bash
git add backend/core/extractor.py
git commit -m "feat: extract DDL schemas from SQL files during upload"
```

---

### Task 4: Backend Endpoints — Upload DDL and Apply DDL

**Files:**
- Modify: `backend/main.py:1-138`

- [ ] **Step 1: Update imports**

Add the new schema imports at the top (update lines 10-18):

```python
from models.schemas import (
    ConfigureRequest,
    ConfigureResponse,
    ValidateResponse,
    TransformResponse,
    LoadRequest,
    LoadResponse,
    StatsResponse,
    DDLUploadResponse,
    ApplyDDLRequest,
    ApplyDDLResponse,
    ApplyDDLTableResult,
)
```

- [ ] **Step 2: Update upload endpoint to return DDL schema**

Update the return dict in `upload_files` (lines 60-66) to include `ddl_schema`:

```python
return {
    "session_id": session_id,
    "files": saved,
    "preview": result.get("preview", {}),
    "inferred_schema": result.get("schema", {}),
    "stats": result.get("stats", {}),
    "ddl_schema": result.get("ddl_schema", {}),
}
```

Also store `ddl_schema` in the session (update line 58):

```python
sessions[session_id] = {
    "extractor": extractor,
    "raw": result,
    "files": saved,
    "ddl_schema": result.get("ddl_schema", {}),
    "applied_ddl": [],
}
```

- [ ] **Step 3: Add `upload-ddl` endpoint**

Add after the `configure` endpoint (after line 74):

```python
@app.post("/api/upload-ddl/{session_id}", response_model=DDLUploadResponse)
async def upload_ddl(session_id: str, files: List[UploadFile] = File(...)):
    if session_id not in sessions:
        raise HTTPException(404, "Session not found")

    from utils.sql_parser import SQLParser
    from utils.encoding import detect_and_convert

    s = sessions[session_id]
    ddl_schema = s.get("ddl_schema", {})
    data_tables = set(s["raw"].get("tables", {}).keys())

    for f in files:
        content = (await f.read()).decode("utf-8", errors="replace")
        parser = SQLParser(content)
        parsed = parser.parse_ddl()
        ddl_schema.update(parsed)

    s["ddl_schema"] = ddl_schema
    matching = [t for t in ddl_schema if t in data_tables]

    return DDLUploadResponse(
        ok=True,
        ddl_schema=ddl_schema,
        matching_tables=matching,
    )
```

- [ ] **Step 4: Add `apply-ddl` endpoint**

Add after the `upload-ddl` endpoint:

```python
@app.post("/api/apply-ddl/{session_id}", response_model=ApplyDDLResponse)
async def apply_ddl(session_id: str, body: ApplyDDLRequest):
    if session_id not in sessions:
        raise HTTPException(404, "Session not found")

    s = sessions[session_id]
    ddl_schema = s.get("ddl_schema", {})
    data_tables = s["raw"].get("tables", {})
    inferred_schema = s["raw"].get("schema", {})
    results = []

    for table in body.tables:
        errors = []

        if table not in ddl_schema:
            errors.append(f"No DDL definition found for table '{table}'")
            results.append(ApplyDDLTableResult(table=table, applied=False, errors=errors))
            continue

        if table not in data_tables or not data_tables[table]:
            errors.append(f"No data found for table '{table}'")
            results.append(ApplyDDLTableResult(table=table, applied=False, errors=errors))
            continue

        # Strict column match (case-insensitive)
        ddl_cols = {c.lower() for c in ddl_schema[table]}
        data_cols = {c.lower() for c in data_tables[table][0].keys()}

        ddl_only = ddl_cols - data_cols
        data_only = data_cols - ddl_cols

        if ddl_only or data_only:
            if ddl_only:
                errors.append(f"Columns in DDL but not in data: {', '.join(sorted(ddl_only))}")
            if data_only:
                errors.append(f"Columns in data but not in DDL: {', '.join(sorted(data_only))}")
            results.append(ApplyDDLTableResult(table=table, applied=False, errors=errors))
            continue

        # Apply DDL schema — overwrite inferred schema for this table
        inferred_schema[table] = ddl_schema[table]
        if table not in s.get("applied_ddl", []):
            s.setdefault("applied_ddl", []).append(table)

        results.append(ApplyDDLTableResult(table=table, applied=True, errors=[]))

    all_ok = all(r.applied for r in results)
    return ApplyDDLResponse(ok=all_ok, results=results)
```

- [ ] **Step 5: Verify endpoints manually**

Start the backend:

```bash
cd /Users/mohammadshweiki/Downloads/Iztech/etl_studio/backend && uvicorn main:app --reload --port 8000
```

Check the docs at `http://localhost:8000/docs` — the new endpoints should appear.

- [ ] **Step 6: Commit**

```bash
git add backend/main.py
git commit -m "feat: add upload-ddl and apply-ddl endpoints, return DDL in upload response"
```

---

### Task 5: Loader — Emit CREATE TABLE with Original DDL Types

**Files:**
- Modify: `backend/core/loader.py:1-98`

- [ ] **Step 1: Update `__init__` to accept DDL schema**

Replace the `__init__` method (lines 9-12):

```python
def __init__(self, transformed: Dict[str, Any], config: Dict[str, Any], out_dir: str,
             ddl_schema: Dict[str, Any] | None = None):
    self.tables: Dict[str, List[Dict]] = transformed.get("tables", {})
    self.config = config
    self.out_dir = out_dir
    self.ddl_schema = ddl_schema or {}
```

- [ ] **Step 2: Add `_create_table_sql` method**

Add before the `_sql_val` method (before line 83):

```python
def _create_table_sql(self, table: str, cols: List[str]) -> List[str]:
    """Generate CREATE TABLE statement using original DDL types if available."""
    if table not in self.ddl_schema:
        return []
    schema = self.ddl_schema[table]
    lines = [f'CREATE TABLE IF NOT EXISTS "{table}" (']
    col_defs = []
    for col in cols:
        col_info = schema.get(col, {})
        col_type = col_info.get("original_type", "TEXT")
        nullable = col_info.get("nullable", True)
        null_str = "" if nullable else " NOT NULL"
        col_defs.append(f'  "{col}" {col_type}{null_str}')
    lines.append(",\n".join(col_defs))
    lines.append(");")
    return ["\n".join(lines), ""]
```

- [ ] **Step 3: Insert CREATE TABLE before INSERTs in SQL output**

In the `run()` method, inside the `elif fmt == "sql":` block, after the `sql_lines.append(f"-- Table: {table}")` line (line 59), add the CREATE TABLE call:

```python
                sql_lines.append(f"-- Table: {table}")
                create_stmts = self._create_table_sql(table, cols)
                sql_lines.extend(create_stmts)
```

- [ ] **Step 4: Update the Loader instantiation in `main.py`**

In `backend/main.py`, update the `load` endpoint (line 112) to pass DDL schema:

```python
    ddl_schema = {t: s["raw"]["schema"].get(t, {}) for t in s["raw"].get("tables", {})
                  if t in s.get("applied_ddl", [])}
    loader = Loader(s["transformed"], body.dict(), out_dir, ddl_schema=ddl_schema)
```

- [ ] **Step 5: Commit**

```bash
git add backend/core/loader.py backend/main.py
git commit -m "feat: emit CREATE TABLE with original DDL types in SQL output"
```

---

### Task 6: Frontend Types and API Client

**Files:**
- Modify: `frontend/src/types/api.ts:1-107`
- Modify: `frontend/src/api/client.ts:1-57`

- [ ] **Step 1: Add DDL types to `api.ts`**

Add `original_type` to `ColumnSchema` (update lines 7-10):

```typescript
export interface ColumnSchema {
  inferred_type: string
  original_type?: string
  nullable: boolean
}
```

Add `ddl_schema` to `UploadResponse` (update lines 12-18):

```typescript
export interface UploadResponse {
  session_id: string
  files: UploadedFile[]
  preview: Record<string, Record<string, unknown>[]>
  inferred_schema: Record<string, Record<string, ColumnSchema>>
  stats: Record<string, { row_count: number }>
  ddl_schema?: Record<string, Record<string, ColumnSchema>>
}
```

Add new interfaces at the end of the file (after line 107):

```typescript
export interface DDLUploadResponse {
  ok: boolean
  ddl_schema: Record<string, Record<string, ColumnSchema>>
  matching_tables: string[]
}

export interface ApplyDDLTableResult {
  table: string
  applied: boolean
  errors: string[]
}

export interface ApplyDDLResponse {
  ok: boolean
  results: ApplyDDLTableResult[]
}
```

- [ ] **Step 2: Add DDL API functions to `client.ts`**

Add the new imports at the top (update lines 2-11):

```typescript
import type {
  UploadResponse,
  ConfigureRequest,
  ConfigureResponse,
  ValidateResponse,
  TransformResponse,
  LoadRequest,
  LoadResponse,
  StatsResponse,
  DDLUploadResponse,
  ApplyDDLResponse,
} from '../types/api'
```

Add at the end of the file (after line 57):

```typescript
export async function uploadDDL(sessionId: string, files: File[]): Promise<DDLUploadResponse> {
  const form = new FormData()
  for (const f of files) form.append('files', f)
  const { data } = await api.post<DDLUploadResponse>(`/upload-ddl/${sessionId}`, form)
  return data
}

export async function applyDDL(sessionId: string, tables: string[]): Promise<ApplyDDLResponse> {
  const { data } = await api.post<ApplyDDLResponse>(`/apply-ddl/${sessionId}`, { tables })
  return data
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/types/api.ts frontend/src/api/client.ts
git commit -m "feat: add DDL TypeScript types and API client functions"
```

---

### Task 7: UploadPhase — DDL Detection Notice

**Files:**
- Modify: `frontend/src/components/UploadPhase.tsx:1-124`

- [ ] **Step 1: Add DDL detection notice**

After the uploaded files card (after line 100, before the preview map), add:

```tsx
          {state.uploadResult.ddl_schema && Object.keys(state.uploadResult.ddl_schema).length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="text-xs">
                  DDL Definitions Detected
                  <span className="text-primary/40 ml-2">
                    [{Object.keys(state.uploadResult.ddl_schema).length} tables]
                  </span>
                </CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-[10px] text-muted-foreground retro mb-2">
                  <span className="text-primary/40">// </span>
                  Schema definitions found. You can apply them in the Configure step.
                </p>
                <div className="space-y-1">
                  {Object.keys(state.uploadResult.ddl_schema).map((table) => (
                    <div key={table} className="text-xs retro py-1 px-1">
                      <span className="text-primary/40 mr-2">{'>'}</span>
                      {table}
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/UploadPhase.tsx
git commit -m "feat: show DDL detection notice in upload phase"
```

---

### Task 8: ConfigurePhase — DDL Upload, Selection, and Apply

**Files:**
- Modify: `frontend/src/components/ConfigurePhase.tsx:1-176`

This is the largest frontend change. The ConfigurePhase needs:
1. A DDL upload dropzone
2. A matching table list with checkboxes
3. An "Apply DDL" button
4. Visual indicators for DDL-applied tables
5. `original_type` display in the column config table

- [ ] **Step 1: Add imports**

Update the imports at the top of the file. Add `useCallback` to the React import (line 1), add `useDropzone` (new import), and add the DDL API functions:

```typescript
import { useState, useCallback } from 'react'
import { useDropzone } from 'react-dropzone'
import { usePipeline } from '../store/pipeline'
import { configure, uploadDDL, applyDDL } from '../api/client'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/8bit/card'
import { Button } from '@/components/ui/8bit/button'
import { Input } from '@/components/ui/8bit/input'
import { Checkbox } from '@/components/ui/8bit/checkbox'
import {
  Select, SelectTrigger, SelectValue, SelectContent, SelectItem,
} from '@/components/ui/8bit/select'
import { PhaseHeader } from './ui'
import type { TableConfig, ColumnConfig, ColumnSchema } from '../types/api'
```

- [ ] **Step 2: Add DDL state variables**

Inside the `ConfigurePhase` component, after the existing state declarations (after line 33), add:

```typescript
  const [ddlSchema, setDdlSchema] = useState<Record<string, Record<string, ColumnSchema>>>(
    () => state.uploadResult?.ddl_schema ?? {}
  )
  const [matchingTables, setMatchingTables] = useState<string[]>(() => {
    const ddl = state.uploadResult?.ddl_schema ?? {}
    return Object.keys(ddl).filter((t) => t in schema)
  })
  const [selectedDdlTables, setSelectedDdlTables] = useState<Set<string>>(new Set())
  const [appliedDdlTables, setAppliedDdlTables] = useState<Set<string>>(new Set())
  const [ddlError, setDdlError] = useState<string | null>(null)
  const [ddlApplyResults, setDdlApplyResults] = useState<{ table: string; applied: boolean; errors: string[] }[]>([])
```

- [ ] **Step 3: Add DDL upload handler and dropzone**

After the DDL state variables, add:

```typescript
  const onDdlDrop = useCallback(async (accepted: File[]) => {
    if (accepted.length === 0 || !state.sessionId) return
    setDdlError(null)
    try {
      const result = await uploadDDL(state.sessionId, accepted)
      setDdlSchema(result.ddl_schema)
      setMatchingTables(result.matching_tables)
      setSelectedDdlTables(new Set())
      setDdlApplyResults([])
    } catch (e: unknown) {
      setDdlError(e instanceof Error ? e.message : 'DDL upload failed')
    }
  }, [state.sessionId])

  const { getRootProps: getDdlRootProps, getInputProps: getDdlInputProps, isDragActive: isDdlDragActive } = useDropzone({
    onDrop: onDdlDrop,
    accept: {
      'application/sql': ['.sql'],
      'text/plain': ['.sql'],
    },
  })

  const toggleDdlTable = (table: string) => {
    setSelectedDdlTables((prev) => {
      const next = new Set(prev)
      if (next.has(table)) next.delete(table)
      else next.add(table)
      return next
    })
  }

  const handleApplyDdl = async () => {
    if (!state.sessionId || selectedDdlTables.size === 0) return
    setDdlError(null)
    try {
      const result = await applyDDL(state.sessionId, [...selectedDdlTables])
      setDdlApplyResults(result.results)
      const applied = new Set(appliedDdlTables)
      for (const r of result.results) {
        if (r.applied) {
          applied.add(r.table)
          // Update the column configs with DDL types
          const ddlCols = ddlSchema[r.table]
          if (ddlCols) {
            setTableConfigs((prev) => ({
              ...prev,
              [r.table]: prev[r.table].map((col) => {
                const ddlCol = Object.entries(ddlCols).find(
                  ([name]) => name.toLowerCase() === col.name.toLowerCase()
                )
                if (ddlCol) {
                  return {
                    ...col,
                    data_type: ddlCol[1].inferred_type,
                    nullable: ddlCol[1].nullable,
                  }
                }
                return col
              }),
            }))
          }
        }
      }
      setAppliedDdlTables(applied)
      setSelectedDdlTables(new Set())
    } catch (e: unknown) {
      setDdlError(e instanceof Error ? e.message : 'Apply DDL failed')
    }
  }
```

- [ ] **Step 4: Add DDL upload UI section in the JSX**

In the return JSX, after the Null Values card (after line 94, before the `<div className="space-y-4 stagger">` on line 96), add:

```tsx
      <Card>
        <CardHeader>
          <CardTitle className="text-xs">
            DDL Schema
            {appliedDdlTables.size > 0 && (
              <span className="text-primary/40 ml-2">[{appliedDdlTables.size} applied]</span>
            )}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div
            {...getDdlRootProps()}
            className={`border-y-4 border-dashed border-foreground/20 p-6 text-center cursor-pointer transition-all
              ${isDdlDragActive ? 'border-primary bg-primary/5' : 'hover:bg-primary/5'}
            `}
          >
            <div
              className="absolute inset-0 border-x-4 border-dashed -mx-1 border-foreground/20 pointer-events-none"
              aria-hidden="true"
              style={{ position: 'relative' }}
            />
            <input {...getDdlInputProps()} />
            <p className="text-muted-foreground retro text-[10px]">
              {isDdlDragActive ? '>> Drop DDL files here <<' : 'Drop .sql DDL files here, or click to browse'}
            </p>
          </div>

          {ddlError && (
            <p className="text-destructive text-[10px] retro">! {ddlError}</p>
          )}

          {matchingTables.length > 0 && (
            <div className="space-y-2">
              <p className="text-[10px] text-muted-foreground retro">
                <span className="text-primary/40">// </span>
                DDL definitions match these data tables. Select which to apply:
              </p>
              {matchingTables.map((table) => (
                <div key={table} className="flex items-center gap-2 text-xs retro py-1">
                  <Checkbox
                    checked={selectedDdlTables.has(table) || appliedDdlTables.has(table)}
                    disabled={appliedDdlTables.has(table)}
                    onCheckedChange={() => toggleDdlTable(table)}
                  />
                  <span>{table}</span>
                  {appliedDdlTables.has(table) && (
                    <span className="text-[10px] text-primary/60 retro ml-1">[DDL applied]</span>
                  )}
                </div>
              ))}
              {selectedDdlTables.size > 0 && (
                <Button onClick={handleApplyDdl} className="mt-2">
                  Apply DDL ({selectedDdlTables.size})
                </Button>
              )}
            </div>
          )}

          {Object.keys(ddlSchema).length > 0 && matchingTables.length === 0 && (
            <p className="text-[10px] text-muted-foreground retro">
              <span className="text-primary/40">// </span>
              DDL loaded but no table names match the uploaded data.
            </p>
          )}

          {ddlApplyResults.length > 0 && (
            <div className="space-y-1">
              {ddlApplyResults.map((r) => (
                <div key={r.table} className="text-[10px] retro">
                  {r.applied ? (
                    <span className="text-primary">{`> ${r.table}: DDL schema applied`}</span>
                  ) : (
                    <div>
                      <span className="text-destructive">{`! ${r.table}: failed`}</span>
                      {r.errors.map((err, i) => (
                        <p key={i} className="text-destructive/70 ml-4">{err}</p>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
```

- [ ] **Step 5: Add DDL badge and original_type display to table config cards**

In the table config card header (around line 102-104), update the `CardTitle` to show DDL badge:

```tsx
                <CardTitle className="text-xs">
                  {table}
                  <span className="text-primary/40 ml-2">[{included}/{columns.length} cols]</span>
                  {appliedDdlTables.has(table) && (
                    <span className="text-xs text-primary/60 retro ml-2">[DDL]</span>
                  )}
                </CardTitle>
```

In the column type display (the `<td>` containing the `<Select>` for data_type, around line 139-153), add `original_type` display. Replace the type `<td>` with:

```tsx
                          <td className="py-2 px-2">
                            <div className="flex items-center gap-2">
                              <Select
                                value={col.data_type}
                                onValueChange={(val) => updateColumn(table, i, { data_type: val })}
                              >
                                <SelectTrigger className="w-[120px]">
                                  <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                  {DATA_TYPES.map((t) => (
                                    <SelectItem key={t} value={t}>{t}</SelectItem>
                                  ))}
                                </SelectContent>
                              </Select>
                              {appliedDdlTables.has(table) && ddlSchema[table]?.[col.name]?.original_type && (
                                <span className="text-[10px] text-muted-foreground retro">
                                  ({ddlSchema[table][col.name].original_type})
                                </span>
                              )}
                            </div>
                          </td>
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/ConfigurePhase.tsx
git commit -m "feat: add DDL upload, selection, and apply UI to configure phase"
```

---

### Task 9: Integration Test — End-to-End Manual Verification

- [ ] **Step 1: Start backend and frontend**

```bash
cd /Users/mohammadshweiki/Downloads/Iztech/etl_studio && npm run dev
```

- [ ] **Step 2: Test upload with DDL auto-detection**

Upload a `.sql` file containing only `CREATE TABLE` statements alongside a CSV with matching column names. Verify:
- Upload response includes `ddl_schema`
- UploadPhase shows "DDL Definitions Detected" notice

- [ ] **Step 3: Test DDL upload at configure step**

In the Configure phase, use the DDL upload dropzone to upload a `.sql` DDL file. Verify:
- Matching tables are listed with checkboxes
- Non-matching table names show "no match" message

- [ ] **Step 4: Test apply DDL with matching columns**

Select a matching table and click "Apply DDL". Verify:
- Table shows "[DDL applied]" badge
- Column types update to DDL-defined types
- `original_type` appears in parentheses next to the type selector

- [ ] **Step 5: Test apply DDL with mismatched columns**

Upload a DDL file where columns don't match the data. Verify:
- Error message lists missing/extra columns
- Schema is not overwritten

- [ ] **Step 6: Test SQL output with DDL types**

Run the full pipeline through to Load with SQL output format. Verify:
- Output `dump.sql` contains `CREATE TABLE` with original DDL types (e.g., `VARCHAR(255)`, `DECIMAL(10,2)`)
- `NOT NULL` constraints are preserved

- [ ] **Step 7: Final commit**

```bash
git add -A
git commit -m "feat: DDL upload feature complete"
```
