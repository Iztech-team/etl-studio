from pydantic import BaseModel
from typing import Any, Dict, List, Optional


class ColumnTransform(BaseModel):
    op: str
    params: Dict[str, Any] = {}


class FKHop(BaseModel):
    """One step in a multi-hop FK chain.

    Read the previous-step value, look it up in `table` where
    `match_column` equals it, and emit `source_column` as the new value.
    """

    table: str
    match_column: str
    source_column: str


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
    # Multi-hop FK: traverse a chain of joins. Cannot be used together
    # with the single-hop `fk_source_*` fields. The first hop reads
    # `fk_local_column` from the source row; each subsequent hop uses the
    # previous hop's `source_column` value as its lookup key. The last
    # hop's `source_column` is what lands in the output.
    #
    # Example — Payment Entry party (POSPAYST → invoice → customer):
    #   fk_local_column = "DOCSERIAL"
    #   fk_chain = [
    #     {table: "CATESINVDOCT", match_column: "DOCSERIAL", source_column: "ACCOUNTID"},
    #     {table: "ACCOUNTT",     match_column: "ACCOUNTID", source_column: "NAME"},
    #   ]
    fk_chain: Optional[List[FKHop]] = None
    transforms: List[ColumnTransform] = []


class FilterCondition(BaseModel):
    """One predicate inside a `RowFilter`. All conditions in a filter are ANDed."""

    column: str
    op: str  # eq | ne | in | not_in | gt | lt | ge | le | is_null | is_not_null | contains | starts_with
    value: Optional[Any] = None


class RowFilter(BaseModel):
    """Drop or keep rows that match the predicate.

    `mode='keep'`  — keep only rows where every condition is true.
    `mode='drop'`  — drop rows where every condition is true; keep the rest.
    """

    mode: str = "keep"
    conditions: List[FilterCondition] = []


class AggregateSpec(BaseModel):
    """SQL-style GROUP BY for the source table before column transforms run.

    `group_by`: source columns to group on. Empty list = DISTINCT-rows reduction
        (every column is part of the key, duplicates are collapsed).
    `aggregations`: per-source-column aggregator. Default for non-grouped
        columns is "first" (take the value from the first row in the group).
        Supported ops: "first", "last", "sum", "count", "min", "max",
        "concat" (string-join with separator from `concat_separator`).
    `concat_separator`: separator for the "concat" aggregator (default ", ").

    Example — Brand seed from CATEGORYT:
        {group_by: ["MANUFACTURER"], aggregations: {}}
        Produces one output row per unique manufacturer.

    Example — Mode of Payment seed from POSPAYST:
        {group_by: ["PAYTYPE"], aggregations: {"PAYAMOUNT": "sum"}}
        One row per payment method with the running total.
    """

    group_by: List[str] = []
    aggregations: Dict[str, str] = {}
    concat_separator: str = ", "


class TableConfig(BaseModel):
    source_table: str
    target_table: Optional[str] = None
    columns: List[ColumnConfig] = []
    primary_key: Optional[str] = None
    load_order: int = 0
    on_duplicate: str = "drop"  # "drop" | "suffix" — dedup strategy
    duplicate_suffix_column: Optional[str] = None
    duplicate_suffix_format: str = "{value}_{n}"
    # Drop the table entirely from output; overrides every other field.
    drop_table: bool = False
    # Filter rows in or out of the output. Applied after per-row column
    # transforms so filters can reference renamed (target) column names.
    row_filter: Optional[RowFilter] = None
    # Pre-aggregate source rows (DISTINCT / GROUP BY) before column-level
    # processing. Used to produce seed records like one Brand per unique
    # manufacturer, or one Payment Entry per receipt.
    aggregate: Optional[AggregateSpec] = None
    # Explicit cross-table dependencies for the load-order step. Names
    # listed here are target_table names that must be loaded BEFORE this
    # table. Augments dependencies the transformer derives from FK columns.
    # Example: ERPnext's Item depends on UOM and Item Group even if you
    # don't model an FK column between the targets.
    load_after: List[str] = []
    # For self-referential targets (e.g. tabAccount whose parent_account
    # points to another tabAccount row), name the column on the OUTPUT row
    # that holds the parent's identifier. The loader will sort rows within
    # this table so parents are inserted before children.
    self_reference_parent_column: Optional[str] = None


class GlobalColumn(BaseModel):
    """Column injected into every (or selected) target table.

    Spec 7.2 — shopId, createdBy, updatedBy, deletedAt; spec 6 — migration_source_id.
    Pick one of `value` (static) or `source_column` (copy from the source row).
    """

    name: str
    value: Optional[Any] = None
    source_column: Optional[str] = None
    apply_to: Optional[List[str]] = None  # target table names; None = all
    exclude_tables: List[str] = []
    overwrite: bool = False


class ConfigureRequest(BaseModel):
    tables: List[TableConfig] = []
    encoding: str = "utf-8"
    null_values: List[str] = ["", "NULL", "null", "N/A", "n/a"]
    global_columns: List[GlobalColumn] = []


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


class DDLTemplate(BaseModel):
    id: str
    project_id: str
    name: str
    ddl_content: str
    created_at: str
    created_by: Optional[str] = None


class CreateTemplateRequest(BaseModel):
    name: str
    ddl_content: str
    created_by: Optional[str] = None


class UpdateTemplateRequest(BaseModel):
    name: Optional[str] = None
    ddl_content: Optional[str] = None


class TemplateListResponse(BaseModel):
    templates: List[DDLTemplate]
    total: int
