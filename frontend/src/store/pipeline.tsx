import { createContext, useContext, useReducer, type ReactNode } from 'react'
import type {
  UploadResponse,
  ConfigureResponse,
  ValidateResponse,
  TransformResponse,
  LoadResponse,
  StatsResponse,
  PreExtractResponse,
} from '../types/api'

export const PHASES = ['pre-extract', 'upload', 'edit', 'configure', 'validate', 'transform', 'load', 'stats'] as const
export type Phase = (typeof PHASES)[number]

interface PipelineState {
  phase: Phase
  sessionId: string | null
  preExtractResult: PreExtractResponse | null
  uploadResult: UploadResponse | null
  configureResult: ConfigureResponse | null
  validateResult: ValidateResponse | null
  transformResult: TransformResponse | null
  loadResult: LoadResponse | null
  statsResult: StatsResponse | null
  loading: boolean
  error: string | null
}

type Action =
  | { type: 'SET_LOADING'; loading: boolean }
  | { type: 'SET_ERROR'; error: string | null }
  | { type: 'SET_PRE_EXTRACT'; result: PreExtractResponse }
  | { type: 'CONFIRM_PRE_EXTRACT'; selectedTables: string[] }
  | { type: 'SKIP_PRE_EXTRACT' }
  | { type: 'SET_UPLOAD'; result: UploadResponse }
  | { type: 'DONE_EDIT' }
  | { type: 'SET_CONFIGURE'; result: ConfigureResponse }
  | { type: 'SET_VALIDATE'; result: ValidateResponse }
  | { type: 'SET_TRANSFORM'; result: TransformResponse }
  | { type: 'SET_LOAD'; result: LoadResponse }
  | { type: 'SET_STATS'; result: StatsResponse }
  | { type: 'GO_TO_PHASE'; phase: Phase }
  | { type: 'RESET' }

const initialState: PipelineState = {
  phase: 'pre-extract',
  sessionId: null,
  preExtractResult: null,
  uploadResult: null,
  configureResult: null,
  validateResult: null,
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
      return { ...state, configureResult: action.result, phase: 'validate', loading: false }
    case 'SET_VALIDATE':
      return { ...state, validateResult: action.result, phase: 'transform', loading: false }
    case 'SET_TRANSFORM':
      return { ...state, transformResult: action.result, phase: 'load', loading: false }
    case 'SET_LOAD':
      return { ...state, loadResult: action.result, phase: 'stats', loading: false }
    case 'SET_STATS':
      return { ...state, statsResult: action.result, loading: false }
    case 'GO_TO_PHASE':
      return { ...state, phase: action.phase }
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
