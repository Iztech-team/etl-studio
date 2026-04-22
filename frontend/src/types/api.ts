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

export interface PreExtractFileInfo {
  name: string
  path: string
  size: number
  db_type: string
}

export interface PreExtractResponse {
  ok: boolean
  session_id: string
  file: PreExtractFileInfo
  tables_extracted: string[]
  csv_files: string[]
  preview: Record<string, Record<string, unknown>[]>
  inferred_schema: Record<string, Record<string, ColumnSchema>>
  stats: Record<string, { row_count: number }>
  ddl_schema?: Record<string, Record<string, ColumnSchema>>
}

export interface TableDataResponse {
  tables: Record<string, Record<string, unknown>[]>
  schema: Record<string, Record<string, ColumnSchema>>
}

export interface EditDataResponse {
  ok: boolean
  stats: Record<string, { row_count: number }>
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
