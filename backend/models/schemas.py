from pydantic import BaseModel
from typing import Any, Dict, List, Optional


class TransformResponse(BaseModel):
    ok: bool
    tables_transformed: int
    total_rows: int
    encoding_conversions: int = 0
    type_conversions: int = 0
    reference_mappings: int = 0
    null_normalizations: int = 0
    dedup_removed: int = 0
    warnings: List[str] = []
    preview: Dict[str, Any] = {}
    # Strategy outputs (populated when /api/transform dispatched through a strategy).
    strategy_name: Optional[str] = None
    strategy_label: Optional[str] = None
    strategy_stats: Dict[str, Any] = {}
    output_doctypes: Dict[str, int] = {}
    audit_report: Optional[Dict[str, Any]] = None
    setup_checklist_md: Optional[str] = None
    bucket_coverage_md: Optional[str] = None


class CounterReset(BaseModel):
    """Spec 7.5 — push a counter past MAX(number) of migrated rows so new orders
    don't collide. Emitted in SQL output only."""

    counter_table: str
    counter_column: str = "value"
    source_table: str
    source_column: str
    where_clause: Optional[str] = None


class LoadRequest(BaseModel):
    output_format: str = "json"  # "json" | "sql" | "csv"
    target_db_url: Optional[str] = None
    use_staging: bool = False
    respect_fk_order: bool = True
    counter_resets: List[CounterReset] = []
    post_load_sql: List[str] = []  # raw SQL appended verbatim after data + resets


class LoadResponse(BaseModel):
    ok: bool
    output_files: List[str]
    rows_written: Dict[str, int]
    staging_used: bool
    transaction_wrapped: bool
    errors: List[str]
    exceptions_written: List[str] = []


class StatsResponse(BaseModel):
    pipeline_stage: str
    total_records_in: int
    total_records_out: int
    tables: Dict[str, Any]
    timing: Dict[str, Any]
    quality_score: float


DB_TYPE_EXTENSIONS = {
    "sqlite": [".sqlite", ".sqlite3", ".db"],
    "firebird": [".fdb", ".gdb", ".ib"],
    "access": [".mdb", ".accdb"],
    "dbase": [".dbf"],
}


class PreExtractFileInfo(BaseModel):
    name: str
    path: str
    size: int
    db_type: str


class PreExtractResponse(BaseModel):
    ok: bool
    session_id: str
    file: PreExtractFileInfo
    tables_extracted: List[str]
    csv_files: List[str]
    preview: Dict[str, Any]
    inferred_schema: Dict[str, Any]
    stats: Dict[str, Any]


class TableSelectionRequest(BaseModel):
    tables: List[str]


class EntitySelectionRequest(BaseModel):
    entities: List[str]


class EditDataRequest(BaseModel):
    tables: Dict[str, List[Dict[str, Any]]]


class EditDataResponse(BaseModel):
    ok: bool
    stats: Dict[str, Any]
