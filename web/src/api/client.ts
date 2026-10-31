import type { Clause, DocumentRecord, ReviewResult, TraceStep } from '../types'

const BASE = (import.meta.env.VITE_API_BASE ?? '').replace(/\/+$/, '')

export interface User {
  id: string
  /** 用用户名注册时邮箱为空 */
  email: string | null
  username: string | null
  name: string
}

export interface ServiceModel {
  id: string
  name: string
  description: string
  base_url: string
  key_hint: string
  configured: boolean
  is_active: boolean
  capability: string
  verified_at: string | null
}

export interface ServiceView {
  id: string
  name: string
  kind: string
  models: ServiceModel[]
}

export interface ModelInput {
  name: string
  description: string
  base_url: string
  api_key: string
}

export interface PresetView {
  id: string
  label: string
  base_url: string
}

export interface PresetInput {
  label: string
  base_url: string
}

export interface RecallModelOption {
  id: string
  name: string
  base_url: string
  service: string
  configured: boolean
  capability: string
}

export interface RecallSettings {
  settings: { enabled: boolean; model_id: string; threshold: number }
  models: RecallModelOption[]
  bounds: { min: number; max: number; default: number }
}

export interface RecallSettingsInput {
  enabled: boolean
  model_id: string
  threshold: number
}

export interface RecallProbeItem {
  format: string
  ok: boolean
  dimensions?: number
  detail: string
}

export interface RecallProbeResult {
  model: string
  results: RecallProbeItem[]
}

export interface SimilarCase {
  clause_id: string
  document_name: string
  title: string
  risk: string
  decision: string
  decision_label: string
  comment: string
  reject_reason: string
  excerpt: string
  score: number
  updated_at: string | null
}

export interface LlmUsageTotals {
  calls: number
  ok: number
  failed: number
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  avg_duration_ms: number
  p95_duration_ms: number
}

export interface LlmUsageDay {
  date: string
  calls: number
  failed: number
  total_tokens: number
}

export interface LlmUsageModel {
  model: string
  calls: number
  failed: number
  total_tokens: number
  avg_duration_ms: number
}

export interface LlmUsageRecord {
  id: number
  document_id: string | null
  purpose: string
  purpose_label: string
  model: string
  total_tokens: number
  duration_ms: number
  ok: boolean
  error: string
  created_at: string
}

export interface LlmUsage {
  days: number
  since: string
  totals: LlmUsageTotals
  by_day: LlmUsageDay[]
  by_model: LlmUsageModel[]
  recent: LlmUsageRecord[]
}

export class ApiError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

/** 401 统一上报给会话层，避免每个组件各自处理登录失效 */
let unauthorizedHandler: (() => void) | null = null
export function setUnauthorizedHandler(handler: (() => void) | null) {
  unauthorizedHandler = handler
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(BASE + path, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    })
  } catch {
    throw new ApiError('后端未连接：先运行 run_local.ps1 启动 127.0.0.1:8103 服务', 0)
  }

  if (response.status === 401) {
    unauthorizedHandler?.()
  }
  if (!response.ok) {
    let detail = `请求失败（HTTP ${response.status}）`
    try {
      const body = (await response.json()) as { detail?: unknown }
      if (typeof body.detail === 'string') detail = body.detail
    } catch {
      // 非 JSON 响应，保留默认文案
    }
    throw new ApiError(detail, response.status)
  }
  return (await response.json()) as T
}

function parseSseChunk(chunk: string): { event: string; data: unknown } | null {
  let event = 'message'
  const dataLines: string[] = []
  for (const line of chunk.split('\n')) {
    if (line.startsWith('event: ')) event = line.slice(7).trim()
    else if (line.startsWith('data: ')) dataLines.push(line.slice(6))
  }
  if (dataLines.length === 0) return null
  try {
    return { event, data: JSON.parse(dataLines.join('\n')) }
  } catch {
    return null
  }
}

interface ServiceList {
  services: ServiceView[]
  presets: PresetView[]
  kinds: string[]
}

export const api = {
  auth: {
    me: () => request<{ user: User }>('/api/auth/me'),
    login: (account: string, password: string) =>
      request<{ user: User }>('/api/auth/login', {
        method: 'POST',
        body: JSON.stringify({ account, password }),
      }),
    register: (account: string, password: string, name: string) =>
      request<{ user: User }>('/api/auth/register', {
        method: 'POST',
        body: JSON.stringify({ account, password, name }),
      }),
    logout: () => request<{ status: string }>('/api/auth/logout', { method: 'POST' }),
  },

  documents: () => request<DocumentRecord[]>('/api/documents'),
  text: (id: string) =>
    request<{ id: string; name: string; text: string }>(
      `/api/documents/${encodeURIComponent(id)}/text`,
    ),
  review: (id: string) =>
    request<ReviewResult>(`/api/documents/${encodeURIComponent(id)}/review`, { method: 'POST' }),
  remove: (id: string) =>
    request<{ status: string }>(`/api/documents/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  audit: (id: string) =>
    request<{ id: number; action: string; payload: Record<string, unknown>; created_at: string }[]>(
      `/api/documents/${encodeURIComponent(id)}/audit`,
    ),

  upload: (name: string, text: string) =>
    request<DocumentRecord>('/api/documents/upload', {
      method: 'POST',
      body: JSON.stringify({ name, text, owner: '当前用户' }),
    }),

  uploadFile: async (file: File) => {
    const form = new FormData()
    form.append('file', file)
    // 不能手写 Content-Type，浏览器要自己加 boundary
    const response = await fetch(`${BASE}/api/documents/upload-file`, {
      method: 'POST',
      body: form,
    })
    if (response.status === 401) unauthorizedHandler?.()
    if (!response.ok) {
      let detail = `上传失败（HTTP ${response.status}）`
      try {
        const body = (await response.json()) as { detail?: unknown }
        if (typeof body.detail === 'string') detail = body.detail
      } catch {
        // ignore
      }
      throw new ApiError(detail, response.status)
    }
    return (await response.json()) as DocumentRecord
  },

  approve: (clauseId: string, accepted: boolean) =>
    request<{ status: string; clause: Clause; replayed: boolean }>(
      `/api/clauses/${encodeURIComponent(clauseId)}/approve`,
      { method: 'POST', body: JSON.stringify({ accepted }) },
    ),

  reject: (clauseId: string, reason: string) =>
    request<{ status: string; clause: Clause; replayed: boolean }>(
      `/api/clauses/${encodeURIComponent(clauseId)}/reject`,
      { method: 'POST', body: JSON.stringify({ reason }) },
    ),

  execute: (clauseId: string) =>
    request<{ status: string; clause: Clause; replayed: boolean }>(
      `/api/clauses/${encodeURIComponent(clauseId)}/execute`,
      {
        method: 'POST',
        // 幂等键：同一波点击重复提交时后端只处理一次
        headers: { 'Idempotency-Key': `${clauseId}-execute-${Date.now()}` },
      },
    ),

  similar: (clauseId: string, limit = 3) =>
    request<{ cases: SimilarCase[]; note: string }>(
      `/api/clauses/${encodeURIComponent(clauseId)}/similar?limit=${limit}`,
    ),

  comment: (clauseId: string, comment: string) =>
    request<{ status: string; clause: Clause }>(
      `/api/clauses/${encodeURIComponent(clauseId)}/comment`,
      { method: 'POST', body: JSON.stringify({ comment }) },
    ),

  exportUrl: (docId: string, format: 'md' | 'docx') =>
    `${BASE}/api/report/${encodeURIComponent(docId)}/export?format=${format}`,

  services: {
    list: () => request<ServiceList>('/api/settings/services'),
    create: (input: { name: string; kind: string }) =>
      request<{ services: ServiceView[] }>('/api/settings/services', {
        method: 'POST',
        body: JSON.stringify(input),
      }),
    update: (id: string, input: { name: string; kind: string }) =>
      request<{ services: ServiceView[] }>(
        `/api/settings/services/${encodeURIComponent(id)}`,
        { method: 'PUT', body: JSON.stringify(input) },
      ),
    remove: (id: string) =>
      request<{ services: ServiceView[] }>(
        `/api/settings/services/${encodeURIComponent(id)}`,
        { method: 'DELETE' },
      ),
    addModel: (serviceId: string, input: ModelInput) =>
      request<{ services: ServiceView[] }>(
        `/api/settings/services/${encodeURIComponent(serviceId)}/models`,
        { method: 'POST', body: JSON.stringify(input) },
      ),
    updateModel: (serviceId: string, modelId: string, input: ModelInput) =>
      request<{ services: ServiceView[] }>(
        `/api/settings/services/${encodeURIComponent(serviceId)}/models/${encodeURIComponent(modelId)}`,
        { method: 'PUT', body: JSON.stringify(input) },
      ),
    removeModel: (serviceId: string, modelId: string) =>
      request<{ services: ServiceView[] }>(
        `/api/settings/services/${encodeURIComponent(serviceId)}/models/${encodeURIComponent(modelId)}`,
        { method: 'DELETE' },
      ),
    activateModel: (serviceId: string, modelId: string) =>
      request<{ services: ServiceView[] }>(
        `/api/settings/services/${encodeURIComponent(serviceId)}/models/${encodeURIComponent(modelId)}/activate`,
        { method: 'POST' },
      ),
    testModel: (serviceId: string, modelId: string) =>
      request<{ ok: boolean; model: string; duration_ms: number; services: ServiceView[] }>(
        `/api/settings/services/${encodeURIComponent(serviceId)}/models/${encodeURIComponent(modelId)}/test`,
        { method: 'POST' },
      ),
  },

  presets: {
    create: (input: PresetInput) =>
      request<{ presets: PresetView[] }>('/api/settings/presets', {
        method: 'POST',
        body: JSON.stringify(input),
      }),    update: (id: string, input: PresetInput) =>
      request<{ presets: PresetView[] }>(
        `/api/settings/presets/${encodeURIComponent(id)}`,
        { method: 'PUT', body: JSON.stringify(input) },
      ),
    remove: (id: string) =>
      request<{ presets: PresetView[]; services: ServiceView[]; deleted_services: number }>(
        `/api/settings/presets/${encodeURIComponent(id)}`,
        { method: 'DELETE' },
      ),
  },

  metrics: {
    llm: (days = 7) => request<LlmUsage>(`/api/metrics/llm?days=${days}`),
  },

  recall: {
    get: () => request<RecallSettings>('/api/settings/recall'),
    save: (input: RecallSettingsInput) =>
      request<RecallSettings>('/api/settings/recall', {
        method: 'PUT',
        body: JSON.stringify(input),
      }),
    probe: (modelId: string) =>
      request<RecallProbeResult>('/api/settings/recall/probe', {
        method: 'POST',
        body: JSON.stringify({ enabled: true, model_id: modelId, threshold: 0.82 }),
      }),
  },

  /**
   * 流式审阅：逐步回调每个步骤；服务端不支持 SSE 时自动退回普通接口。
   */
  async reviewStream(id: string, onStep: (step: TraceStep) => void): Promise<ReviewResult> {
    let response: Response
    try {
      response = await fetch(`${BASE}/api/documents/${encodeURIComponent(id)}/review/stream`, {
        headers: { Accept: 'text/event-stream' },
      })
    } catch {
      throw new ApiError('后端未连接', 0)
    }

    const isStream = response.headers.get('content-type')?.includes('text/event-stream')
    if (response.status === 401) {
      unauthorizedHandler?.()
      throw new ApiError('登录已过期', 401)
    }
    if (!response.ok || !isStream || !response.body) {
      return api.review(id)
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let result: ReviewResult | null = null
    let failure: string | null = null

    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      let boundary = buffer.indexOf('\n\n')
      while (boundary >= 0) {
        const chunk = buffer.slice(0, boundary)
        buffer = buffer.slice(boundary + 2)
        const parsed = parseSseChunk(chunk)
        if (parsed?.event === 'step') onStep(parsed.data as TraceStep)
        else if (parsed?.event === 'result') result = parsed.data as ReviewResult
        else if (parsed?.event === 'error') {
          failure = String((parsed.data as { detail?: string }).detail ?? '审阅失败')
        }
        boundary = buffer.indexOf('\n\n')
      }
    }

    if (failure) throw new ApiError(failure, 502)
    if (!result) throw new ApiError('审阅中断：没有收到结果', 502)
    return result
  },
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message
  if (error instanceof Error) return error.message
  return '未知错误'
}
