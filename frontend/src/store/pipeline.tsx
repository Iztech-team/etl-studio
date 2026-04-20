import { createContext, useContext, useReducer, type ReactNode } from 'react'
import type {
  UploadResponse,
  ConfigureResponse,
  ValidateResponse,
  TransformResponse,
  LoadResponse,
  StatsResponse,
} from '../types/api'

export const PHASES = ['upload', 'configure', 'validate', 'transform', 'load', 'stats'] as const
export type Phase = (typeof PHASES)[number]

interface PipelineState {
  phase: Phase
  sessionId: string | null
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
  | { type: 'SET_UPLOAD'; result: UploadResponse }
  | { type: 'SET_CONFIGURE'; result: ConfigureResponse }
  | { type: 'SET_VALIDATE'; result: ValidateResponse }
  | { type: 'SET_TRANSFORM'; result: TransformResponse }
  | { type: 'SET_LOAD'; result: LoadResponse }
  | { type: 'SET_STATS'; result: StatsResponse }
  | { type: 'GO_TO_PHASE'; phase: Phase }
  | { type: 'RESET' }

const initialState: PipelineState = {
  phase: 'upload',
  sessionId: null,
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
    case 'SET_UPLOAD':
      return { ...state, uploadResult: action.result, sessionId: action.result.session_id, phase: 'configure', loading: false }
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
