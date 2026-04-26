import { createContext, useContext, useReducer, type ReactNode } from 'react'
import type {
  UploadResponse,
  ConfigureResponse,
  TransformResponse,
  LoadResponse,
  StatsResponse,
  PreExtractResponse,
  SchemaEditState,
} from '../types/api'

export const PHASES = ['pre-extract', 'upload', 'edit', 'schema-edit', 'configure', 'transform', 'load', 'stats'] as const
export type Phase = (typeof PHASES)[number]

export type AppMode = 'landing' | 'project' | 'guest'

interface PipelineState {
  mode: AppMode
  phase: Phase
  sessionId: string | null
  projectId: string | null
  projectName: string | null
  preExtractResult: PreExtractResponse | null
  uploadResult: UploadResponse | null
  configureResult: ConfigureResponse | null
  transformResult: TransformResponse | null
  loadResult: LoadResponse | null
  statsResult: StatsResponse | null
  loading: boolean
  error: string | null
  schemaEditState?: SchemaEditState
}

type Action =
  | { type: 'SET_LOADING'; loading: boolean }
  | { type: 'SET_ERROR'; error: string | null }
  | { type: 'SET_PROJECT'; projectId: string; projectName: string }
  | { type: 'START_GUEST' }
  | { type: 'RESTORE_PROJECT'; projectId: string; projectName: string; sessionId: string; phase: Phase; uploadResult: UploadResponse | null; configureResult: ConfigureResponse | null; transformResult: TransformResponse | null; loadResult: LoadResponse | null; statsResult: StatsResponse | null }
  | { type: 'SET_PRE_EXTRACT'; result: PreExtractResponse }
  | { type: 'CONFIRM_PRE_EXTRACT'; selectedTables: string[] }
  | { type: 'SKIP_PRE_EXTRACT' }
  | { type: 'SET_UPLOAD'; result: UploadResponse }
  | { type: 'DONE_EDIT' }
  | { type: 'SET_CONFIGURE'; result: ConfigureResponse }
  | { type: 'SET_TRANSFORM'; result: TransformResponse }
  | { type: 'SET_LOAD'; result: LoadResponse }
  | { type: 'SET_STATS'; result: StatsResponse }
  | { type: 'GO_TO_PHASE'; phase: Phase }
  | { type: 'SCHEMA_EDIT_INIT'; payload: { inferred_schema: Record<string, import('../types/api').TableSchema> } }
  | { type: 'SCHEMA_EDIT_RENAME_TABLE'; payload: { tableName: string; newName: string } }
  | { type: 'SCHEMA_EDIT_DROP_TABLE'; payload: { tableName: string } }
  | { type: 'SCHEMA_EDIT_RENAME_COLUMN'; payload: { tableName: string; colName: string; newName: string } }
  | { type: 'SCHEMA_EDIT_DROP_COLUMN'; payload: { tableName: string; colName: string } }
  | { type: 'SCHEMA_EDIT_TOGGLE_NULLABLE'; payload: { tableName: string; colName: string; nullable: boolean } }
  | { type: 'SCHEMA_EDIT_REORDER_COLUMN'; payload: { tableName: string; colName: string; direction: 'up' | 'down' } }
  | { type: 'SCHEMA_EDIT_APPLY_DDL'; payload: import('../types/api').DDLUploadResponse }
  | { type: 'SCHEMA_EDIT_APPLY' }
  | { type: 'SCHEMA_EDIT_SKIP' }
  | { type: 'RESET' }

const initialState: PipelineState = {
  mode: 'landing',
  phase: 'pre-extract',
  sessionId: null,
  projectId: null,
  projectName: null,
  preExtractResult: null,
  uploadResult: null,
  configureResult: null,
  transformResult: null,
  loadResult: null,
  statsResult: null,
  loading: false,
  error: null,
}

function reducer(state: PipelineState, action: Action): PipelineState {
  switch (action.type) {
    case 'SET_LOADING':
      return { ...state, loading: action.loading, error: null }
    case 'SET_ERROR':
      return { ...state, error: action.error, loading: false }
    case 'SET_PROJECT':
      return { ...state, mode: 'project', projectId: action.projectId, projectName: action.projectName, phase: 'pre-extract' }
    case 'START_GUEST':
      return { ...state, mode: 'guest', phase: 'pre-extract' }
    case 'RESTORE_PROJECT':
      return {
        ...state,
        mode: 'project',
        projectId: action.projectId,
        projectName: action.projectName,
        sessionId: action.sessionId,
        phase: action.phase,
        uploadResult: action.uploadResult,
        configureResult: action.configureResult,
        transformResult: action.transformResult,
        loadResult: action.loadResult,
        statsResult: action.statsResult,
        loading: false,
        error: null,
      }
    case 'SET_PRE_EXTRACT':
      return {
        ...state,
        preExtractResult: action.result,
        sessionId: action.result.session_id,
        phase: 'pre-extract',
        loading: false,
      }
    case 'CONFIRM_PRE_EXTRACT': {
      const r = state.preExtractResult
      if (!r) return state
      const selected = new Set(action.selectedTables)
      const filteredPreview: Record<string, Record<string, unknown>[]> = {}
      const filteredSchema: Record<string, Record<string, import('../types/api').ColumnSchema>> = {}
      const filteredStats: Record<string, { row_count: number }> = {}
      const filteredFiles: { name: string; path: string; size: number }[] = []
      for (const table of action.selectedTables) {
        if (r.preview[table]) filteredPreview[table] = r.preview[table]
        if (r.inferred_schema[table]) filteredSchema[table] = r.inferred_schema[table]
        if (r.stats[table]) filteredStats[table] = r.stats[table]
        filteredFiles.push({ name: `${table}.csv`, path: '', size: 0 })
      }
      return {
        ...state,
        uploadResult: {
          session_id: r.session_id,
          files: filteredFiles,
          preview: filteredPreview,
          inferred_schema: filteredSchema,
          stats: filteredStats,
          ddl_schema: r.ddl_schema,
        },
        phase: 'edit',
        loading: false,
      }
    }
    case 'SKIP_PRE_EXTRACT':
      return { ...state, phase: 'upload', loading: false }
    case 'SET_UPLOAD':
      return { ...state, uploadResult: action.result, sessionId: action.result.session_id, phase: 'edit', loading: false }
    case 'DONE_EDIT':
      return { ...state, phase: 'configure', loading: false }
    case 'SET_CONFIGURE':
      return { ...state, configureResult: action.result, phase: 'transform', loading: false }
    case 'SET_TRANSFORM':
      return { ...state, transformResult: action.result, phase: 'load', loading: false }
    case 'SET_LOAD':
      return { ...state, loadResult: action.result, phase: 'stats', loading: false }
    case 'SET_STATS':
      return { ...state, statsResult: action.result, loading: false }
    case 'GO_TO_PHASE':
      return { ...state, phase: action.phase }
    case 'SCHEMA_EDIT_INIT':
      return {
        ...state,
        phase: 'schema-edit',
        schemaEditState: {
          originalSchema: action.payload.inferred_schema || {},
          editedSchema: action.payload.inferred_schema || {},
          selectedTable: null,
          expandedTables: new Set(),
          searchFilter: '',
          droppedTables: new Set(),
          droppedColumns: new Map(),
          renamedTables: new Map(),
          renamedColumns: new Map(),
          reorderedColumns: new Map(),
          nullableOverrides: new Map(),
          ddlApplied: false,
          ddlSource: null,
          modified: false
        }
      }
    case 'SCHEMA_EDIT_RENAME_TABLE':
      return {
        ...state,
        schemaEditState: {
          ...state.schemaEditState!,
          renamedTables: new Map(state.schemaEditState!.renamedTables).set(
            action.payload.tableName,
            action.payload.newName
          ),
          modified: true
        }
      }
    case 'SCHEMA_EDIT_DROP_TABLE':
      return {
        ...state,
        schemaEditState: {
          ...state.schemaEditState!,
          droppedTables: new Set(
            state.schemaEditState!.droppedTables.has(action.payload.tableName)
              ? [...state.schemaEditState!.droppedTables].filter(t => t !== action.payload.tableName)
              : [...state.schemaEditState!.droppedTables, action.payload.tableName]
          ),
          modified: true
        }
      }
    case 'SCHEMA_EDIT_APPLY':
      return {
        ...state,
        phase: 'configure',
        schemaEditState: {
          ...state.schemaEditState!,
          modified: false
        }
      }
    case 'SCHEMA_EDIT_SKIP':
      return {
        ...state,
        phase: 'configure'
      }
    case 'SCHEMA_EDIT_RENAME_COLUMN':
      return {
        ...state,
        schemaEditState: {
          ...state.schemaEditState!,
          renamedColumns: new Map(state.schemaEditState!.renamedColumns).set(
            action.payload.tableName,
            new Map((state.schemaEditState!.renamedColumns.get(action.payload.tableName) || new Map()))
              .set(action.payload.colName, action.payload.newName)
          ),
          modified: true
        }
      }
    case 'SCHEMA_EDIT_DROP_COLUMN': {
      const droppedCols = new Map(state.schemaEditState!.droppedColumns)
      const tableDropped = droppedCols.get(action.payload.tableName) || new Set()
      const newTableDropped = new Set(tableDropped)
      if (newTableDropped.has(action.payload.colName)) {
        newTableDropped.delete(action.payload.colName)
      } else {
        newTableDropped.add(action.payload.colName)
      }
      droppedCols.set(action.payload.tableName, newTableDropped)

      return {
        ...state,
        schemaEditState: {
          ...state.schemaEditState!,
          droppedColumns: droppedCols,
          modified: true
        }
      }
    }
    case 'SCHEMA_EDIT_TOGGLE_NULLABLE': {
      const nullableOverrides = new Map(state.schemaEditState!.nullableOverrides)
      const tableNullable = nullableOverrides.get(action.payload.tableName) || new Set()
      const newTableNullable = new Set(tableNullable)
      if (action.payload.nullable) {
        newTableNullable.add(action.payload.colName)
      } else {
        newTableNullable.delete(action.payload.colName)
      }
      nullableOverrides.set(action.payload.tableName, newTableNullable)

      return {
        ...state,
        schemaEditState: {
          ...state.schemaEditState!,
          nullableOverrides: nullableOverrides,
          modified: true
        }
      }
    }
    case 'SCHEMA_EDIT_REORDER_COLUMN':
      return {
        ...state,
        schemaEditState: {
          ...state.schemaEditState!,
          modified: true
        }
      }
    case 'SCHEMA_EDIT_APPLY_DDL':
      return {
        ...state,
        schemaEditState: {
          ...state.schemaEditState!,
          ddlApplied: true,
          ddlSource: 'uploaded_ddl',
          modified: true
        }
      }
    case 'RESET':
      return initialState
  }
}

const PipelineContext = createContext<{
  state: PipelineState
  dispatch: React.Dispatch<Action>
} | null>(null)

export function PipelineProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, initialState)
  return (
    <PipelineContext.Provider value={{ state, dispatch }}>
      {children}
    </PipelineContext.Provider>
  )
}

export function usePipeline() {
  const ctx = useContext(PipelineContext)
  if (!ctx) throw new Error('usePipeline must be used within PipelineProvider')
  return ctx
}
