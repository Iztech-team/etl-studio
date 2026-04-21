export interface UploadedFile {
  name: string
  path: string
  size: number
}

export interface ColumnSchema {
  inferred_type: string
  original_type?: string
  nullable: boolean
}

export interface UploadResponse {
  session_id: string
  files: UploadedFile[]
  preview: Record<string, Record<string, unknown>[]>
  inferred_schema: Record<string, Record<string, ColumnSchema>>
  stats: Record<string, { row_count: number }>
  ddl_schema?: Record<string, Record<string, ColumnSchema>>
}

export interface ColumnConfig {
  name: string
  target_name?: string
  data_type: string
  nullable: boolean
  include: boolean
  reference_map?: Record<string, unknown>
}

export interface TableConfig {
  source_table: string
  target_table?: string
  columns: ColumnConfig[]
  primary_key?: string
  load_order: number
}

export interface ConfigureRequest {
  tables: TableConfig[]
  encoding: string
  null_values: string[]
}

export interface ConfigureResponse {
  ok: boolean
  message: string
}

export interface ValidationIssue {
  level: 'error' | 'warning' | 'info'
  table: string
  column: string | null
  message: string
  count: number | null
}

export interface ValidateResponse {
  passed: boolean
  record_counts: Record<string, number>
  financial_totals: Record<string, number>
  duplicate_counts: Record<string, number>
  truncation_risks: { table: string; column: string; max_length: number; count: number }[]
  issues: ValidationIssue[]
  spot_checks: { table: string; rows: Record<string, unknown>[] }[]
}

export interface TransformResponse {
  ok: boolean
  tables_transformed: number
  total_rows: number
  encoding_conversions: number
  type_conversions: number
  reference_mappings: number
  null_normalizations: number
  warnings: string[]
  preview: Record<string, Record<string, unknown>[]>
}

export interface LoadRequest {
  output_format: 'json' | 'sql'
  target_db_url?: string
  use_staging: boolean
  respect_fk_order: boolean
}

export interface LoadResponse {
  ok: boolean
  output_files: string[]
  rows_written: Record<string, number>
  staging_used: boolean
  transaction_wrapped: boolean
  errors: string[]
}

export interface StatsResponse {
  pipeline_stage: string
  total_records_in: number
  total_records_out: number
  tables: Record<string, {
    rows_in: number
    rows_out: number
    columns: number
    duplicates: number
  }>
  timing: Record<string, unknown>
  quality_score: number
}

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
