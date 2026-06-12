import type {
  DocumentListResponse,
  GraphData,
  JobStatusResponse,
  PathogenHypothesis,
  PathogenResearch,
  PathogenSources,
  PathogensResponse,
  PathogenTrendsData,
  PipelineStatus,
  TriggerResponse,
} from '../types'

const BASE = (import.meta.env.VITE_API_BASE_URL ?? '') + '/api/v1'

async function get<T>(path: string): Promise<T> {
  const res = await fetch(BASE + path)
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`${res.status}: ${text || res.statusText}`)
  }
  return res.json() as Promise<T>
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(BASE + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data?.detail ?? `${res.status}: ${res.statusText}`)
  }
  return res.json() as Promise<T>
}

export const api = {
  getPathogens: (limit = 200) =>
    get<PathogensResponse>(`/agents/pathogens?limit=${limit}`),

  getResearch: (name: string) =>
    get<PathogenResearch>(`/agents/research/${encodeURIComponent(name)}`),

  getHypothesis: (name: string) =>
    get<PathogenHypothesis>(`/agents/hypothesis/${encodeURIComponent(name)}`),

  getSources: (name: string) =>
    get<PathogenSources>(`/agents/sources/${encodeURIComponent(name)}`),

  getGraph: () => get<GraphData>('/agents/graph'),

  getPipelineStatus: () => get<PipelineStatus>('/agents/pipeline-status'),

  getTrends: (days = 30) => get<PathogenTrendsData>(`/agents/pathogen-trends?days=${days}`),

  getDocuments: (params: { source?: string; limit?: number; offset?: number } = {}) => {
    const q = new URLSearchParams()
    if (params.source) q.set('source', params.source)
    q.set('limit', String(params.limit ?? 50))
    q.set('offset', String(params.offset ?? 0))
    return get<DocumentListResponse>(`/documents?${q}`)
  },

  triggerPipeline: () =>
    post<TriggerResponse>('/agents/trigger/run-pipeline', {}),

  getJobStatus: (jobId: string) =>
    get<JobStatusResponse>(`/ingestion/jobs/${jobId}`),

  subscribe: (name: string, email: string) =>
    post<{ message: string }>('/newsletter/subscribe', { name, email }),

  unsubscribe: (token: string) =>
    post<{ message: string }>('/newsletter/unsubscribe', { token }),
}
