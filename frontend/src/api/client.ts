import axios, { AxiosError } from 'axios'
import type {
  UploadResponse,
  ConfigureRequest,
  ConfigureResponse,
  TransformResponse,
  LoadRequest,
  LoadResponse,
  StatsResponse,
  DDLUploadResponse,
  ApplyDDLResponse,
  PreExtractResponse,
  TableDataResponse,
  EditDataResponse,
} from '../types/api'

const api = axios.create({ baseURL: '/api' })

api.interceptors.response.use(
  (res) => res,
  (err: AxiosError<{ detail?: string }>) => {
    const message = err.response?.data?.detail ?? err.message
    return Promise.reject(new Error(message))
  },
)

export async function preExtract(
  file: File,
  password?: string,
  onProgress?: (percent: number) => void,
  projectId?: string,
): Promise<PreExtractResponse> {
  const form = new FormData()
  form.append('file', file)
  if (password) form.append('password', password)
  if (projectId) form.append('project_id', projectId)
  const { data } = await api.post<PreExtractResponse>('/pre-extract', form, {
    onUploadProgress: (e) => {
      if (onProgress && e.total) {
        onProgress(Math.round((e.loaded / e.total) * 100))
      }
    },
  })
  return data
}

export async function preExtractSelect(sessionId: string, tables: string[]): Promise<void> {
  await api.post(`/pre-extract-select/${sessionId}`, { tables })
}

export async function fetchTableData(sessionId: string): Promise<TableDataResponse> {
  const { data } = await api.get<TableDataResponse>(`/table-data/${sessionId}`)
  return data
}

export async function saveTableData(
  sessionId: string,
  tables: Record<string, Record<string, unknown>[]>,
): Promise<EditDataResponse> {
  const { data } = await api.post<EditDataResponse>(`/table-data/${sessionId}`, { tables })
  return data
}

export async function uploadFiles(files: File[], projectId?: string): Promise<UploadResponse> {
  const form = new FormData()
  for (const f of files) form.append('files', f)
  if (projectId) form.append('project_id', projectId)
  const { data } = await api.post<UploadResponse>('/upload', form)
  return data
}

export async function configure(sessionId: string, config: ConfigureRequest): Promise<ConfigureResponse> {
  const { data } = await api.post<ConfigureResponse>(`/configure/${sessionId}`, config)
  return data
}

export async function transform(sessionId: string): Promise<TransformResponse> {
  const { data } = await api.get<TransformResponse>(`/transform/${sessionId}`)
  return data
}

export async function load(sessionId: string, config: LoadRequest): Promise<LoadResponse> {
  const { data } = await api.post<LoadResponse>(`/load/${sessionId}`, config)
  return data
}

export async function fetchStats(sessionId: string): Promise<StatsResponse> {
  const { data } = await api.get<StatsResponse>(`/stats/${sessionId}`)
  return data
}

export function downloadUrl(sessionId: string, filename: string): string {
  return `/api/download/${sessionId}/${encodeURIComponent(filename)}`
}

export async function uploadDDL(sessionId: string, files: File[]): Promise<DDLUploadResponse> {
  const form = new FormData()
  for (const f of files) form.append('files', f)
  const { data } = await api.post<DDLUploadResponse>(`/upload-ddl/${sessionId}`, form)
  return data
}

export async function applyDDL(sessionId: string, tables: string[]): Promise<ApplyDDLResponse> {
  const { data } = await api.post<ApplyDDLResponse>(`/apply-ddl/${sessionId}`, { tables })
  return data
}
