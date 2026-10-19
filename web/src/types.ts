export type Risk = 'high' | 'medium' | 'low'

export interface Clause {
  id: string
  document_id: string
  title: string
  risk: Risk
  excerpt: string
  /** 正文的精确切片，必须满足 text.slice(start_offset, end_offset) === original */
  original: string
  reason: string
  recommend: string
  start_offset: number
  end_offset: number
  accepted: number
  comment: string
}

export type DocumentStatus = 'pending' | 'reviewed'

export interface DocumentRecord {
  id: string
  name: string
  owner: string
  status: DocumentStatus
  source_type: string
  text_length: number
  created_at: string
  clauses?: Clause[]
}

export type TraceStatus = 'success' | 'skipped' | 'error' | 'running'

export interface TraceStep {
  step: string
  status: TraceStatus
  detail: string
  duration_ms?: number
}

export interface TokenUsage {
  prompt_tokens?: number
  completion_tokens?: number
  total_tokens?: number
}

export interface ModelMeta {
  provider: string
  model: string
  usage?: TokenUsage
  duration_ms?: number
}

export type ReviewMode = 'demo' | 'deepseek'

export interface ReviewResult {
  document: DocumentRecord
  trace: TraceStep[]
  tool_calls: string[]
  mode: ReviewMode
  model_error: string | null
  model_meta: ModelMeta | null
  /** 本次审阅沿用了几条上次的人工处置（采纳/批注） */
  kept?: number
  duration_ms: number
}

export const RISK_LABEL: Record<Risk, string> = {
  high: '高风险',
  medium: '中风险',
  low: '低风险',
}

/** 排序用：高风险在前 */
export const RISK_WEIGHT: Record<Risk, number> = { high: 0, medium: 1, low: 2 }

export type RiskFilter = 'all' | Risk
