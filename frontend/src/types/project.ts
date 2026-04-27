import type { ColumnSchema } from './api'

export interface Project {
  id: string
  name: string
  username: string
  phase: string
  created_at: string
  updated_at: string
}

export interface ResumeResponse {
  session_id: string
  project: Project
  phase: string
  files: { name: string; path: string; size: number }[]
  preview: Record<string, Record<string, unknown>[]>
  inferred_schema: Record<string, Record<string, ColumnSchema>>
  stats: Record<string, { row_count: number }>
  config: Record<string, unknown> | null
  transform: Record<string, unknown> | null
  load_result: Record<string, unknown> | null
}
