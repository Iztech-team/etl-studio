from pydantic import BaseModel
from typing import Any, Dict, List, Optional


class ColumnTransform(BaseModel):
    op: str
    params: Dict[str, Any] = {}


class ColumnConfig(BaseModel):
    name: str
    target_name: Optional[str] = None
    data_type: str = "string"
    nullable: bool = True
    include: bool = True
    reference_map: Optional[Dict[str, Any]] = None
    is_new: bool = False
    default_value: Optional[Any] = None
    fk_source_table: Optional[str] = None
    fk_source_column: Optional[str] = None
    fk_match_column: Optional[str] = None
    fk_local_column: Optional[str] = None
    transforms: List[ColumnTransform] = []


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


class TransformResponse(BaseModel):
    ok: bool
    tables_transformed: int
    total_rows: int
    encoding_conversions: int
    type_conversions: int
    reference_mappings: int
    null_normalizations: int
    dedup_removed: int = 0
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
    ddl_schema: Dict[str, Any] = {}


class EditDataRequest(BaseModel):
    tables: Dict[str, List[Dict[str, Any]]]


class EditDataResponse(BaseModel):
    ok: bool
    stats: Dict[str, Any]


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
