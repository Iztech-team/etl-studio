from pydantic import BaseModel
from typing import Any, Dict, List, Optional


class ColumnConfig(BaseModel):
    name: str
    target_name: Optional[str] = None
    data_type: str = "string"
    nullable: bool = True
    include: bool = True
    reference_map: Optional[Dict[str, Any]] = None


class TableConfig(BaseModel):
    source_table: str
    target_table: Optional[str] = None
    columns: List[ColumnConfig] = []
    primary_key: Optional[str] = None
    load_order: int = 0


class ConfigureRequest(BaseModel):
    tables: List[TableConfig] = []
    encoding: str = "utf-8"
    null_values: List[str] = ["", "NULL", "null", "N/A", "n/a"]


class ConfigureResponse(BaseModel):
    ok: bool
    message: str


class ValidationIssue(BaseModel):
    level: str  # "error" | "warning" | "info"
    table: str
    column: Optional[str] = None
    message: str
    count: Optional[int] = None


class ValidateResponse(BaseModel):
    passed: bool
    record_counts: Dict[str, int]
    financial_totals: Dict[str, Any]
    duplicate_counts: Dict[str, int]
    truncation_risks: List[Dict[str, Any]]
    issues: List[ValidationIssue]
    spot_checks: List[Dict[str, Any]]


class TransformResponse(BaseModel):
    ok: bool
    tables_transformed: int
    total_rows: int
    encoding_conversions: int
    type_conversions: int
    reference_mappings: int
    null_normalizations: int
    warnings: List[str]
    preview: Dict[str, Any]


class LoadRequest(BaseModel):
    output_format: str = "json"  # "json" | "sql"
    target_db_url: Optional[str] = None  # for staging
    use_staging: bool = False
    respect_fk_order: bool = True


class LoadResponse(BaseModel):
    ok: bool
    output_files: List[str]
    rows_written: Dict[str, int]
    staging_used: bool
    transaction_wrapped: bool
    errors: List[str]


class StatsResponse(BaseModel):
    pipeline_stage: str
    total_records_in: int
    total_records_out: int
    tables: Dict[str, Any]
    timing: Dict[str, Any]
    quality_score: float


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
