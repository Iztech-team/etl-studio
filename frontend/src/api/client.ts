import axios, { AxiosError } from 'axios'
import type {
  UploadResponse,
  ConfigureRequest,
  ConfigureResponse,
  ValidateResponse,
  TransformResponse,
  LoadRequest,
  LoadResponse,
  StatsResponse,
} from '../types/api'

const api = axios.create({ baseURL: '/api' })

api.interceptors.response.use(
  (res) => res,
  (err: AxiosError<{ detail?: string }>) => {
    const message = err.response?.data?.detail ?? err.message
    return Promise.reject(new Error(message))
  },
)

export async function uploadFiles(files: File[]): Promise<UploadResponse> {
  const form = new FormData()
  for (const f of files) form.append('files', f)
  const { data } = await api.post<UploadResponse>('/upload', form)
  return data
}

export async function configure(sessionId: string, config: ConfigureRequest): Promise<ConfigureResponse> {
  const { data } = await api.post<ConfigureResponse>(`/configure/${sessionId}`, config)
  return data
}

export async function validate(sessionId: string): Promise<ValidateResponse> {
  const { data } = await api.get<ValidateResponse>(`/validate/${sessionId}`)
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
