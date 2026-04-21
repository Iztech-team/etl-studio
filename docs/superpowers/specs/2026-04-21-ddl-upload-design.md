# DDL Upload Feature — Design Spec

## Summary

Add the ability to upload DDL (CREATE TABLE) SQL files so the app uses declared schema definitions instead of inferring types from data. DDL can be provided at upload time (auto-detected) or at the configure step (explicit upload). Users pick which tables to apply DDL schemas to. Column sets must match exactly (strict validation). Original SQL types are preserved for accurate SQL output generation.

## DDL Parser

Extend `backend/utils/sql_parser.py` with a `parse_ddl()` method.

**Input:** Raw SQL text containing CREATE TABLE statements.

**Parsing behavior:**
- Extract table name, column names, original SQL types, nullability (NOT NULL)
- Handle multi-dialect identifiers: backticks (MySQL), double quotes (PostgreSQL), brackets (SQL Server), bare names
- Ignore constraints (PRIMARY KEY, FOREIGN KEY, UNIQUE, CHECK, DEFAULT) — only extract column name, type, and NOT NULL

**Type normalization mapping:**
| SQL Types | Normalized Type |
|-----------|----------------|
| VARCHAR, TEXT, CHAR, NVARCHAR, NCHAR, CLOB | string |
| INT, INTEGER, BIGINT, SMALLINT, TINYINT, SERIAL, BIGSERIAL | integer |
| DECIMAL, NUMERIC, REAL, DOUBLE, DOUBLE PRECISION, FLOAT | float |
| BOOLEAN, BOOL | boolean |
| DATE, DATETIME, TIMESTAMP, TIMESTAMPTZ, TIME | date |

**Output structure:**
```python
{
    "table_name": {
        "column_name": {
            "inferred_type": "float",        # normalized
            "original_type": "DECIMAL(10,2)", # preserved from DDL
            "nullable": False                 # True unless NOT NULL present
        }
    }
}
```

## Backend Integration

### Upload phase changes (`POST /api/upload`)

After `Extractor.extract_all()`, check if any SQL files produced DDL schemas (CREATE TABLE without INSERT data for that table). Store in session under `"ddl_schema"` key. Include `ddl_schema` in the upload response.

### New endpoint: `POST /api/upload-ddl/{session_id}`

Accepts `.sql` file(s) via multipart upload. Parses CREATE TABLE statements. Merges into `session["ddl_schema"]`. Returns parsed DDL schemas and list of tables that match existing data tables.

### New endpoint: `POST /api/apply-ddl/{session_id}`

Accepts JSON body: `{"tables": ["table1", "table2"]}`.

For each requested table:
1. Check table exists in both `ddl_schema` and data tables
2. Strict column match — DDL columns must exactly match data columns (same names, same count)
3. On match: overwrite `inferred_schema` entry with DDL schema (including `original_type`)
4. On mismatch: return error details (missing/extra columns)

Returns per-table success/failure with mismatch details.

### Session structure

```python
sessions[session_id] = {
    # ...existing keys...
    "ddl_schema": {          # parsed DDL definitions (available, not yet applied)
        "table_name": { "col": { "inferred_type", "original_type", "nullable" } }
    },
    "applied_ddl": []        # list of table names where DDL was applied
}
```

## Frontend Integration

### UploadPhase.tsx

After upload, if `ddl_schema` is non-empty in the response, show an info notice: "DDL definitions found for: table_x, table_y". Informational only — no action at this stage.

### ConfigurePhase.tsx

- Add "Upload DDL" dropzone/button above table configuration cards
- On DDL upload, show panel listing DDL tables that match data tables
- Each matching table gets a checkbox for user selection
- "Apply DDL" button calls `POST /api/apply-ddl/{session_id}`
- On success: refresh schema, update column config to reflect DDL types
- On mismatch: show warning with column mismatch details
- Visual indicator (badge) on tables: "DDL schema" vs "Inferred schema"
- Column config table shows `original_type` in parentheses next to normalized type when DDL is applied

### API client additions (`client.ts`)

- `uploadDDL(sessionId: string, files: File[]): Promise<DDLUploadResponse>`
- `applyDDL(sessionId: string, tables: string[]): Promise<ApplyDDLResponse>`

### Type additions (`api.ts`)

- Add optional `ddl_schema` to `UploadResponse`
- New `DDLUploadResponse`: `{ ddl_schema, matching_tables: string[] }`
- New `ApplyDDLResponse`: `{ results: { table: string, applied: boolean, errors?: string[] }[] }`
- Extend column schema with optional `original_type: string`

## Loader Enhancement

### SQL output (`backend/core/loader.py`)

When generating SQL output for a table with applied DDL:
- Emit a `CREATE TABLE` statement before the INSERTs using the original DDL types
- Include NOT NULL constraints from DDL
- If no DDL applied, keep current behavior (INSERT-only)

## Strict Match Validation Rules

When applying DDL to a data table:
- Every DDL column must exist in the data
- Every data column must exist in the DDL
- Column count must match
- Column name comparison is case-insensitive
- Order does not need to match

Mismatches produce a clear error listing:
- Columns in DDL but not in data
- Columns in data but not in DDL
