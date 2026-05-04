"""SQL statements and shell command templates used across the backend.

Importers do `from definitions import GET_PROJECT` and run via
`cur.execute(GET_PROJECT, (pid,))` or `subprocess.run(ISQL_EXTRACT_CMD)`.
"""

# --- Schema setup (used by persistence/db.py:init_db) ---

CREATE_PROJECTS_TABLE = """
    CREATE TABLE IF NOT EXISTS projects (
        id          TEXT PRIMARY KEY,
        name        TEXT NOT NULL,
        username    TEXT NOT NULL DEFAULT 'admin',
        phase       TEXT NOT NULL DEFAULT 'upload',
        created_at  TEXT NOT NULL,
        updated_at  TEXT NOT NULL,
        UNIQUE(name, username)
    )
"""

CREATE_PIPELINE_RUNS_TABLE = """
    CREATE TABLE IF NOT EXISTS pipeline_runs (
        id          TEXT PRIMARY KEY,
        project_id  TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        phase       TEXT NOT NULL,
        status      TEXT NOT NULL DEFAULT 'running',
        rows_affected INTEGER NOT NULL DEFAULT 0,
        note        TEXT NOT NULL DEFAULT '',
        started_at  TEXT NOT NULL,
        finished_at TEXT,
        FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
    )
"""

CREATE_AUDIT_EVENTS_TABLE = """
    CREATE TABLE IF NOT EXISTS audit_events (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id  TEXT NOT NULL,
        run_id      TEXT,
        event_type  TEXT NOT NULL,
        table_name  TEXT,
        column_name TEXT,
        detail      TEXT NOT NULL DEFAULT '',
        created_at  TEXT NOT NULL,
        FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
        FOREIGN KEY (run_id) REFERENCES pipeline_runs(id) ON DELETE CASCADE
    )
"""

CREATE_INDEX_PIPELINE_RUNS_PROJECT = (
    "CREATE INDEX IF NOT EXISTS idx_pipeline_runs_project ON pipeline_runs(project_id)"
)
CREATE_INDEX_AUDIT_EVENTS_PROJECT = (
    "CREATE INDEX IF NOT EXISTS idx_audit_events_project ON audit_events(project_id)"
)
CREATE_INDEX_AUDIT_EVENTS_RUN = (
    "CREATE INDEX IF NOT EXISTS idx_audit_events_run ON audit_events(run_id)"
)

CREATE_ERPNEXT_CREDS_TABLE = """
    CREATE TABLE IF NOT EXISTS erpnext_credentials (
        project_id    TEXT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
        url           TEXT NOT NULL,
        api_key       TEXT NOT NULL,
        api_secret    TEXT NOT NULL,
        company       TEXT,
        company_abbr  TEXT,
        updated_at    TEXT NOT NULL
    )
"""

UPSERT_ERPNEXT_CREDS = """
    INSERT INTO erpnext_credentials (project_id, url, api_key, api_secret, company, company_abbr, updated_at)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(project_id) DO UPDATE SET
        url = excluded.url,
        api_key = excluded.api_key,
        api_secret = excluded.api_secret,
        company = excluded.company,
        company_abbr = excluded.company_abbr,
        updated_at = excluded.updated_at
"""

GET_ERPNEXT_CREDS = """
    SELECT url, api_key, api_secret, company, company_abbr, updated_at
    FROM erpnext_credentials WHERE project_id = ?
"""

CREATE_ERPNEXT_IMPORTS_TABLE = """
    CREATE TABLE IF NOT EXISTS erpnext_imports (
        project_id     TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        file_name      TEXT NOT NULL,
        doctype        TEXT NOT NULL,
        imported_count INTEGER NOT NULL DEFAULT 0,
        completed_at   TEXT NOT NULL,
        PRIMARY KEY (project_id, file_name)
    )
"""

UPSERT_ERPNEXT_IMPORT = """
    INSERT INTO erpnext_imports (project_id, file_name, doctype, imported_count, completed_at)
    VALUES (?, ?, ?, ?, ?)
    ON CONFLICT(project_id, file_name) DO UPDATE SET
        doctype = excluded.doctype,
        imported_count = excluded.imported_count,
        completed_at = excluded.completed_at
"""

LIST_ERPNEXT_IMPORTS = """
    SELECT file_name, doctype, imported_count, completed_at
    FROM erpnext_imports WHERE project_id = ?
"""

CLEAR_ERPNEXT_IMPORTS = "DELETE FROM erpnext_imports WHERE project_id = ?"

# --- Project queries ---

INSERT_PROJECT = (
    "INSERT INTO projects (id, name, username, phase, created_at, updated_at) "
    "VALUES (?, ?, ?, 'upload', ?, ?)"
)
LIST_PROJECTS_BY_USER = (
    "SELECT * FROM projects WHERE username = ? ORDER BY updated_at DESC"
)
GET_PROJECT = "SELECT * FROM projects WHERE id = ?"
GET_PROJECT_USERNAME = "SELECT username FROM projects WHERE id = ?"
UPDATE_PROJECT_PHASE = "UPDATE projects SET phase = ?, updated_at = ? WHERE id = ?"
RENAME_PROJECT = "UPDATE projects SET name = ?, updated_at = ? WHERE id = ?"
DELETE_PROJECT = "DELETE FROM projects WHERE id = ?"

# --- Pipeline run queries ---

INSERT_PIPELINE_RUN = (
    "INSERT INTO pipeline_runs (id, project_id, phase, status, started_at) "
    "VALUES (?, ?, ?, 'running', ?)"
)
INSERT_BACKFILLED_EXTRACT_RUN = (
    "INSERT INTO pipeline_runs (id, project_id, phase, status, rows_affected, note, started_at, finished_at) "
    "VALUES (?, ?, 'extract', 'done', ?, ?, ?, ?)"
)
INSERT_BACKFILLED_TRANSFORM_RUN = (
    "INSERT INTO pipeline_runs (id, project_id, phase, status, rows_affected, note, started_at, finished_at) "
    "VALUES (?, ?, 'transform', 'done', ?, ?, ?, ?)"
)
INSERT_BACKFILLED_LOAD_RUN = (
    "INSERT INTO pipeline_runs (id, project_id, phase, status, rows_affected, note, started_at, finished_at) "
    "VALUES (?, ?, 'load', ?, ?, ?, ?, ?)"
)
GET_PIPELINE_RUN = "SELECT * FROM pipeline_runs WHERE id = ?"
FINISH_PIPELINE_RUN = (
    "UPDATE pipeline_runs SET status = ?, rows_affected = ?, note = ?, finished_at = ? "
    "WHERE id = ?"
)
LIST_PIPELINE_RUNS = (
    "SELECT * FROM pipeline_runs WHERE project_id = ? ORDER BY started_at DESC"
)
LIST_PROJECTS_FOR_BACKFILL = "SELECT id, phase, created_at, updated_at FROM projects"
CHECK_PIPELINE_RUN_EXISTS = "SELECT 1 FROM pipeline_runs WHERE project_id = ? LIMIT 1"

GET_DASHBOARD_STATS = """
    SELECT
        COUNT(DISTINCT r.project_id) AS projects_with_data,
        COALESCE(SUM(r.rows_affected), 0) AS total_rows_migrated
    FROM pipeline_runs r
    JOIN projects p ON p.id = r.project_id
    WHERE p.username = ?
      AND r.phase = 'load'
      AND r.status = 'done'
"""

# --- Audit event queries ---

INSERT_AUDIT_EVENT = (
    "INSERT INTO audit_events (project_id, run_id, event_type, table_name, column_name, detail, created_at) "
    "VALUES (?, ?, ?, ?, ?, ?, ?)"
)
INSERT_AUDIT_EVENT_BATCH = (
    "INSERT INTO audit_events (project_id, run_id, event_type, table_name, column_name, detail, created_at) "
    "VALUES (:project_id, :run_id, :event_type, :table_name, :column_name, :detail, :created_at)"
)
LIST_AUDIT_EVENTS = (
    "SELECT * FROM audit_events WHERE project_id = ? "
    "ORDER BY created_at DESC LIMIT ?"
)

# --- SQLite PRAGMAs ---

PRAGMA_JOURNAL_MODE_WAL = "PRAGMA journal_mode=WAL"
PRAGMA_FOREIGN_KEYS_ON = "PRAGMA foreign_keys=ON"

# --- Shell commands ---

# InterBase / Firebird ISQL invocation: pass the SQL script via -i flag.
# The script itself is built dynamically (CONNECT + queries + EXIT).
ISQL_RUN_SCRIPT_ARGS = ["-i", "{script_path}"]
